from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import re
import uuid

from app.config import settings

logger = logging.getLogger(__name__)

_INSECURE_SECRETS = ("dev-secret-change-me", "change-me-in-production", "")
_ALLOWED_ENVS = {"development", "dev", "test", "production", "prod"}


def _validate_runtime_settings() -> str:
    env = (settings.environment or "development").strip().lower()
    if env not in _ALLOWED_ENVS:
        raise RuntimeError(
            f"ENVIRONMENT must be one of {sorted(_ALLOWED_ENVS)} (got {settings.environment!r})"
        )
    secret = settings.secret_key or ""
    expire_min = int(settings.access_token_expire_minutes or 0)
    if expire_min <= 0:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be > 0")
    if expire_min > 10_080:
        msg = "ACCESS_TOKEN_EXPIRE_MINUTES exceeds 10080 (7 days)"
        if env in ("prod", "production"):
            raise RuntimeError(msg)
        logger.warning("%s — prefer shorter JWT lifetime", msg)
    if not (1 <= int(settings.max_org_members or 0) <= 10_000):
        raise RuntimeError("MAX_ORG_MEMBERS must be between 1 and 10000")
    algo = (settings.algorithm or "").strip()
    if algo and algo != "HS256":
        raise RuntimeError(f"ALGORITHM must be HS256 (got {algo!r})")
    media = (settings.media_backend or "local").strip().lower()
    if media not in ("local", "s3"):
        raise RuntimeError(f"MEDIA_BACKEND must be local or s3 (got {settings.media_backend!r})")
    if env in ("prod", "production"):
        if secret in _INSECURE_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "SECRET_KEY is insecure — set a strong SECRET_KEY (min 32 chars) in production"
            )
        if (settings.cors_origins or "").strip() == "*":
            logger.warning("CORS_ORIGINS=* in production — set explicit origins")
        if settings.trust_x_forwarded_for and not (settings.trusted_proxy_cidrs or "").strip():
            logger.warning(
                "TRUST_X_FORWARDED_FOR=true without TRUSTED_PROXY_CIDRS — "
                "spoofable client IPs; set proxy CIDRs"
            )
        if media == "s3" and not (settings.s3_bucket or "").strip():
            raise RuntimeError("MEDIA_BACKEND=s3 requires S3_BUCKET in production")
        db_url = (settings.database_url or "").strip().lower()
        if db_url.startswith("sqlite:"):
            logger.warning("DATABASE_URL uses SQLite in production — prefer PostgreSQL")
    elif secret in _INSECURE_SECRETS:
        logger.warning("SECRET_KEY is insecure — set a strong SECRET_KEY in production")
    elif media == "s3" and not (settings.s3_bucket or "").strip():
        logger.warning("MEDIA_BACKEND=s3 without S3_BUCKET — uploads may fall back to local")
    return env


_RUNTIME_ENV = _validate_runtime_settings()
_IS_PROD = _RUNTIME_ENV in ("prod", "production")

from app.alembic_runner import run_alembic_upgrade
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

Base.metadata.create_all(bind=engine)
ensure_money_record_columns()
run_alembic_upgrade()

app = FastAPI(
    title=settings.app_name,
    version="0.7.41",
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)

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
_MAX_JSON_BODY = 256 * 1024
_MAX_UPLOAD_BODY = 9 * 1024 * 1024


def _ensure_request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if existing:
        return str(existing)
    incoming = (request.headers.get("x-request-id") or "").strip()
    request_id = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
    request.state.request_id = request_id
    return request_id


def _json_error(
    status_code: int,
    detail: str,
    *,
    request: Request,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    out = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "X-Request-Id": _ensure_request_id(request),
    }
    if headers:
        out.update(headers)
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=out)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _ensure_request_id(request)
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
        if settings.enable_hsts:
            max_age = max(0, int(settings.hsts_max_age or 0))
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={max_age}; includeSubDomains",
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies (Content-Length and streamed without CL)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)
        path = request.url.path.rstrip("/")
        limit = _MAX_UPLOAD_BODY if path.endswith("/media/photo") else _MAX_JSON_BODY
        raw = request.headers.get("content-length")
        if raw and raw.isdigit():
            if int(raw) > limit:
                return _json_error(413, "Request body too large", request=request)
            return await call_next(request)

        # No Content-Length — buffer with a hard cap (JSON paths; uploads usually send CL).
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > limit:
                return _json_error(413, "Request body too large", request=request)

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
        return await call_next(request)


class PublicAuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Cheap IP limit before body parsing on public auth / upload endpoints."""

    _AUTH_PATHS = {
        "/auth/login",
        "/auth/login-form",
        "/auth/accept-invite",
        "/orgs/register",
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        from fastapi import HTTPException

        from app.services.rate_limit import client_ip, enforce_rate_limit

        path = request.url.path.rstrip("/") or "/"
        try:
            if path in self._AUTH_PATHS or request.url.path in self._AUTH_PATHS:
                enforce_rate_limit(
                    f"preauth:{request.url.path}:{client_ip(request)}",
                    limit=60,
                    window_sec=60,
                )
            if request.method == "POST" and path.endswith("/media/photo"):
                enforce_rate_limit(
                    f"upload-ip:{client_ip(request)}",
                    limit=40,
                    window_sec=60,
                )
        except HTTPException as exc:
            headers = {k: str(v) for k, v in (exc.headers or {}).items()}
            detail = exc.detail if isinstance(exc.detail, str) else "Too many attempts"
            return _json_error(exc.status_code, detail, request=request, headers=headers)
        return await call_next(request)


# Innermost → outermost via reverse add order: RequestId outermost so early
# middleware responses can still set/reuse request ids when helpers run first.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(PublicAuthRateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)

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
    request_id = _ensure_request_id(request)
    logger.exception("unhandled error request_id=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Request-Id": request_id},
    )


@app.get("/health")
def health(request: Request):
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
        "version": "0.7.41",
        "db": db_status,
        "media_backend": (settings.media_backend or "local").strip().lower(),
    }
    if db_status != "ok":
        return JSONResponse(status_code=503, content=body)
    return body
