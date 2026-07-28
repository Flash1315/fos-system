from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import re
import uuid

from app.alembic_runner import run_alembic_upgrade
from app.config import settings
from app.db import Base, engine
from app.migrate import ensure_money_record_columns
from app.routers import auth as auth_router
from app.routers import adjustments as adjustments_router
from app.routers import billing as billing_router
from app.routers import media as media_router
from app.routers import payouts as payouts_router
from app.routers import records as records_router
from app.routers import reports as reports_router
from app.routers import team as team_router
from app.routers import transfers as transfers_router

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)
ensure_money_record_columns()
run_alembic_upgrade()

app = FastAPI(title=settings.app_name, version="0.7.36")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
# Bearer-token auth does not use cookies; credentials+wildcard is unnecessary.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Request-Id",
        "Accept",
    ],
    expose_headers=["Content-Disposition", "X-Request-Id", "Retry-After"],
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = (request.headers.get("x-request-id") or "").strip()
        request_id = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # Authenticated API / media — avoid shared caches storing bearer-scoped bodies
        response.headers.setdefault("Cache-Control", "no-store")
        return response


class PublicAuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Cheap IP limit before body parsing on public auth endpoints."""

    _PATHS = {
        "/auth/login",
        "/auth/login-form",
        "/auth/accept-invite",
        "/orgs/register",
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        # login-form keeps trailing path as registered
        check = path if path in self._PATHS else request.url.path
        if check in self._PATHS or request.url.path in self._PATHS:
            from app.services.rate_limit import client_ip, enforce_rate_limit

            enforce_rate_limit(
                f"preauth:{request.url.path}:{client_ip(request)}",
                limit=60,
                window_sec=60,
            )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(PublicAuthRateLimitMiddleware)

app.include_router(auth_router.router)
app.include_router(records_router.router)
app.include_router(team_router.router)
app.include_router(reports_router.router)
app.include_router(media_router.router)
app.include_router(transfers_router.router)
app.include_router(payouts_router.router)
app.include_router(adjustments_router.router)
app.include_router(billing_router.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    from fastapi.responses import JSONResponse

    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    logger.exception("unhandled error request_id=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Request-Id": request_id},
    )


@app.get("/health")
def health(request: Request):
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.services.rate_limit import client_ip, enforce_rate_limit

    enforce_rate_limit(f"health:{client_ip(request)}", limit=120, window_sec=60)

    db_status = "ok"
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"
        logger.exception("health db check failed")
    body = {
        "ok": db_status == "ok",
        "app": settings.app_name,
        "version": "0.7.36",
        "db": db_status,
        "media_backend": (settings.media_backend or "local").strip().lower(),
    }
    if db_status != "ok":
        return JSONResponse(status_code=503, content=body)
    return body


_INSECURE_SECRETS = ("dev-secret-change-me", "change-me-in-production", "")
_env = (settings.environment or "development").strip().lower()
if settings.secret_key in _INSECURE_SECRETS:
    if _env in ("prod", "production"):
        raise RuntimeError("SECRET_KEY is insecure — set a strong SECRET_KEY in production")
    logger.warning("SECRET_KEY is insecure — set a strong SECRET_KEY in production")
if _env in ("prod", "production") and (settings.cors_origins or "").strip() == "*":
    logger.warning("CORS_ORIGINS=* in production — set explicit origins")
