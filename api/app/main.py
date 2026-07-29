from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import parse_qsl, urlparse

from app.config import settings
from app.version import APP_VERSION

logger = logging.getLogger(__name__)

_INSECURE_SECRETS = ("dev-secret-change-me", "change-me-in-production", "")
_ALLOWED_ENVS = {"development", "dev", "test", "production", "prod"}
_ALLOWED_LOG_FORMATS = {"text", "json"}
_ALLOWED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
_MAX_VALIDATION_ERRORS = 20
_MAX_VALIDATION_DETAIL = 2048


def _validate_runtime_settings() -> str:
    env = (settings.environment or "development").strip().lower()
    if env not in _ALLOWED_ENVS:
        raise RuntimeError(
            f"ENVIRONMENT must be one of {sorted(_ALLOWED_ENVS)} (got {settings.environment!r})"
        )
    secret = (settings.secret_key or "").strip()
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
    ttl = int(settings.idempotency_ttl_hours or 0)
    if ttl < 1 or ttl > 168:
        raise RuntimeError("IDEMPOTENCY_TTL_HOURS must be between 1 and 168")
    hsts = int(settings.hsts_max_age or 0)
    if hsts < 0 or hsts > 63_072_000:
        raise RuntimeError("HSTS_MAX_AGE must be between 0 and 63072000")
    if settings.enable_hsts and hsts <= 0:
        raise RuntimeError("HSTS_MAX_AGE must be > 0 when ENABLE_HSTS is true")
    log_format = (settings.log_format or "").strip().lower()
    if log_format not in _ALLOWED_LOG_FORMATS:
        raise RuntimeError("LOG_FORMAT must be text or json")
    log_level = (settings.log_level or "").strip().upper()
    if log_level not in _ALLOWED_LOG_LEVELS:
        raise RuntimeError(
            f"LOG_LEVEL must be one of {sorted(_ALLOWED_LOG_LEVELS)}"
        )
    pool_recycle = int(settings.db_pool_recycle or 0)
    if pool_recycle < 60 or pool_recycle > 86_400:
        raise RuntimeError("DB_POOL_RECYCLE must be between 60 and 86400")
    pool_timeout = int(settings.db_pool_timeout or 0)
    if pool_timeout < 1 or pool_timeout > 300:
        raise RuntimeError("DB_POOL_TIMEOUT must be between 1 and 300")
    connect_timeout = int(settings.db_connect_timeout or 0)
    if connect_timeout < 1 or connect_timeout > 120:
        raise RuntimeError("DB_CONNECT_TIMEOUT must be between 1 and 120")
    if not (1024 <= int(settings.json_body_limit_bytes or 0) <= 10 * 1024 * 1024):
        raise RuntimeError(
            "JSON_BODY_LIMIT_BYTES must be between 1024 and 10485760"
        )
    if not (
        int(settings.json_body_limit_bytes)
        <= int(settings.upload_body_limit_bytes or 0)
        <= 100 * 1024 * 1024
    ):
        raise RuntimeError(
            "UPLOAD_BODY_LIMIT_BYTES must be at least JSON_BODY_LIMIT_BYTES "
            "and at most 104857600"
        )
    if not (1 <= int(settings.media_token_expire_minutes or 0) <= 60):
        raise RuntimeError("MEDIA_TOKEN_EXPIRE_MINUTES must be between 1 and 60")
    smtp_timeout = float(settings.smtp_timeout_seconds or 0)
    if smtp_timeout < 0.5 or smtp_timeout > 60:
        raise RuntimeError("SMTP_TIMEOUT_SECONDS must be between 0.5 and 60")
    readiness_timeout = float(settings.readiness_timeout_seconds or 0)
    if readiness_timeout < 0.1 or readiness_timeout > 30:
        raise RuntimeError("READINESS_TIMEOUT_SECONDS must be between 0.1 and 30")
    if not (1 <= int(settings.smtp_port or 0) <= 65_535):
        raise RuntimeError("SMTP_PORT must be between 1 and 65535")
    algo = (settings.algorithm or "").strip()
    if algo != "HS256":
        raise RuntimeError(f"ALGORITHM must be HS256 (got {settings.algorithm!r})")
    media = (settings.media_backend or "local").strip().lower()
    if media not in ("local", "s3"):
        raise RuntimeError(f"MEDIA_BACKEND must be local or s3 (got {settings.media_backend!r})")
    s3_key = (settings.s3_access_key or "").strip()
    s3_secret = (settings.s3_secret_key or "").strip()
    if bool(s3_key) != bool(s3_secret):
        raise RuntimeError("S3_ACCESS_KEY and S3_SECRET_KEY must both be set or both empty")
    if env in ("prod", "production"):
        if not secret or secret in _INSECURE_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "SECRET_KEY is insecure — set a strong SECRET_KEY (min 32 chars) in production"
            )
        if (settings.cors_origins or "").strip() == "*":
            raise RuntimeError(
                "CORS_ORIGINS=* is not allowed in production — set explicit origins"
            )
        cors_list = [
            o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()
        ]
        if not cors_list:
            raise RuntimeError(
                "CORS_ORIGINS must list at least one origin in production"
            )
        for origin in cors_list:
            try:
                parsed = urlparse(origin)
                parsed.port
            except ValueError as exc:
                raise RuntimeError(
                    f"CORS_ORIGINS contains an invalid origin: {origin!r}"
                ) from exc
            if (
                "*" in origin
                or "?" in origin
                or "#" in origin
                or "\\" in origin
                or any(ch.isspace() for ch in origin)
                or parsed.scheme.lower() != "https"
                or not parsed.netloc
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise RuntimeError(
                    "CORS_ORIGINS entries must be absolute HTTPS origins without "
                    f"path, query, fragment, userinfo, or wildcards (got {origin!r})"
                )
        if settings.trust_x_forwarded_for:
            cidrs = (settings.trusted_proxy_cidrs or "").strip()
            if not cidrs:
                raise RuntimeError(
                    "TRUST_X_FORWARDED_FOR=true requires TRUSTED_PROXY_CIDRS in production"
                )
            from app.services.rate_limit import parse_proxy_cidrs

            if not parse_proxy_cidrs(cidrs):
                raise RuntimeError(
                    "TRUSTED_PROXY_CIDRS has no valid CIDRs/IPs — fix before enabling XFF"
                )
        if media == "s3" and not (settings.s3_bucket or "").strip():
            raise RuntimeError("MEDIA_BACKEND=s3 requires S3_BUCKET in production")
        if not settings.rate_limit_enabled:
            raise RuntimeError("RATE_LIMIT_ENABLED must be true in production")
        db_url = (settings.database_url or "").strip().lower()
        if db_url.startswith("sqlite:"):
            raise RuntimeError(
                "DATABASE_URL must be PostgreSQL in production (sqlite is local/dev only)"
            )
        pool_size = int(settings.db_pool_size or 0)
        max_overflow = int(settings.db_max_overflow or 0)
        if pool_size < 1 or pool_size > 100:
            raise RuntimeError("DB_POOL_SIZE must be between 1 and 100")
        if max_overflow < 0 or max_overflow > 100:
            raise RuntimeError("DB_MAX_OVERFLOW must be between 0 and 100")
        if not (settings.metrics_token or "").strip():
            raise RuntimeError(
                "METRICS_TOKEN is required in production (protect GET /metrics)"
            )
        if len((settings.metrics_token or "").strip()) < 32:
            raise RuntimeError("METRICS_TOKEN must be at least 32 characters in production")
        try:
            parsed_db = urlparse((settings.database_url or "").strip())
        except ValueError as exc:
            raise RuntimeError("DATABASE_URL is invalid") from exc
        if parsed_db.scheme.lower().startswith("postgres"):
            query = {
                key.lower(): value.lower()
                for key, value in parse_qsl(parsed_db.query, keep_blank_values=True)
            }
            sslmode = query.get("sslmode", "")
            if sslmode not in ("require", "verify-ca", "verify-full") and query.get(
                "ssl"
            ) != "true":
                raise RuntimeError(
                    "Production PostgreSQL DATABASE_URL must include "
                    "sslmode=require, verify-ca, or verify-full (or ssl=true)"
                )
        if (settings.smtp_host or "").strip() and not settings.smtp_use_tls:
            raise RuntimeError(
                "SMTP_USE_TLS must be true when SMTP_HOST is configured in production"
            )
        endpoint = (settings.s3_endpoint_url or "").strip()
        if endpoint:
            try:
                parsed_endpoint = urlparse(endpoint)
            except ValueError as exc:
                raise RuntimeError("S3_ENDPOINT_URL is invalid") from exc
            if parsed_endpoint.scheme.lower() != "https" or not parsed_endpoint.netloc:
                raise RuntimeError(
                    "S3_ENDPOINT_URL must be an absolute HTTPS URL in production"
                )
    elif not secret or secret in _INSECURE_SECRETS:
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

# Dev/SQLite: create_all + additive migrate helpers. Production: Alembic only.
if not _IS_PROD:
    Base.metadata.create_all(bind=engine)
    ensure_money_record_columns()
run_alembic_upgrade()


def _configure_logging() -> None:
    level_name = (settings.log_level or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = (settings.log_format or "text").strip().lower()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level)
    root.setLevel(level)
    if fmt == "json":
        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                import json
                from datetime import datetime, timezone

                payload = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info:
                    payload["exc_info"] = self.formatException(record.exc_info)
                return json.dumps(payload, ensure_ascii=False)

        for h in root.handlers:
            h.setFormatter(_JsonFormatter())


_configure_logging()

# Best-effort: prune expired idempotency rows once at boot (also happens on store).
try:
    from app.db import SessionLocal
    from app.services.idempotency import prune_expired_idem

    with SessionLocal() as _boot_db:
        _pruned = prune_expired_idem(_boot_db)
        if _pruned:
            logger.info("startup pruned %s expired idempotency row(s)", _pruned)
except Exception:  # noqa: BLE001
    logger.warning("startup idempotency prune skipped", exc_info=True)

app = FastAPI(
    title=settings.app_name,
    version=APP_VERSION,
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
        "X-Metrics-Token",
        "Accept",
    ],
    expose_headers=["Content-Disposition", "X-Request-Id", "Retry-After"],
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def _security_headers() -> dict[str, str]:
    """Headers shared by normal, validation, and early middleware responses."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "X-Permitted-Cross-Domain-Policies": "none",
        "Content-Security-Policy": "default-src 'none'",
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Expires": "0",
    }


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
    out = _security_headers()
    out["X-Request-Id"] = _ensure_request_id(request)
    if headers:
        out.update(headers)
    if settings.enable_hsts:
        max_age = max(0, int(settings.hsts_max_age or 0))
        out.setdefault(
            "Strict-Transport-Security",
            f"max-age={max_age}; includeSubDomains",
        )
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=out)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _ensure_request_id(request)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


class RequestLogMetricsMiddleware(BaseHTTPMiddleware):
    """Structured request log + in-process metrics (no Sentry/OTel required)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        import json
        import time

        from app.services.metrics import observe_request

        request_id = _ensure_request_id(request)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = int(response.status_code)
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            from app.services.metrics import normalize_path

            raw_path = request.url.path
            path = normalize_path(raw_path)
            method = request.method
            try:
                observe_request(
                    method=method, path=raw_path, status=status, duration_ms=duration_ms
                )
            except Exception:  # noqa: BLE001
                pass
            payload = {
                "ts": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
                "level": "INFO",
                "msg": "request",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": round(duration_ms, 2),
            }
            if (settings.log_format or "text").strip().lower() == "json":
                logger.info("%s", json.dumps(payload, ensure_ascii=False))
            else:
                logger.info(
                    "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                    request_id,
                    method,
                    path,
                    status,
                    duration_ms,
                )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _security_headers().items():
            response.headers.setdefault(name, value)
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
        limit = (
            int(settings.upload_body_limit_bytes)
            if path.endswith("/media/photo")
            else int(settings.json_body_limit_bytes)
        )
        raw = request.headers.get("content-length")
        if raw is not None:
            if not re.fullmatch(r"[0-9]+", raw):
                return _json_error(400, "Invalid Content-Length", request=request)
            try:
                content_length = int(raw)
            except (ValueError, OverflowError):
                return _json_error(400, "Invalid Content-Length", request=request)
            if content_length > limit:
                return _json_error(413, "Request body too large", request=request)
            return await call_next(request)

        # No Content-Length — buffer with a hard cap (JSON paths; uploads usually send CL).
        chunks: list[bytes] = []
        body_size = 0
        async for chunk in request.stream():
            body_size += len(chunk)
            if body_size > limit:
                return _json_error(413, "Request body too large", request=request)
            chunks.append(chunk)
        body = b"".join(chunks)

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
app.add_middleware(RequestLogMetricsMiddleware)
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
    return _json_error(500, "Internal server error", request=request)


from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Flatten Pydantic errors to a single detail string (mobile-friendly)."""
    parts: list[str] = []
    errors = exc.errors()
    for err in errors[:_MAX_VALIDATION_ERRORS]:
        loc = err.get("loc") or ()
        # Skip leading "body" / "query" / "path"
        fields = [str(x) for x in loc if x not in ("body", "query", "path", "header")]
        where = ".".join(fields)
        msg = str(err.get("msg") or "invalid")
        parts.append(f"{where}: {msg}" if where else msg)
    if len(errors) > _MAX_VALIDATION_ERRORS:
        parts.append(f"{len(errors) - _MAX_VALIDATION_ERRORS} more error(s)")
    detail = "; ".join(parts) if parts else "Validation error"
    if len(detail) > _MAX_VALIDATION_DETAIL:
        detail = detail[: _MAX_VALIDATION_DETAIL - 1] + "…"
    return _json_error(422, detail, request=request)


def _db_ping() -> str:
    from sqlalchemy import text

    from app.db import SessionLocal

    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001
        logger.exception("health db check failed")
        return "error"


def _tok_ok(got: str, expected: str) -> bool:
    if not expected or len(got) != len(expected):
        return False
    return secrets.compare_digest(got.encode(), expected.encode())


@app.get("/health/live")
def health_live():
    """Liveness — no DB, no rate limit (safe for orchestrator probes)."""
    return JSONResponse(
        content={"ok": True, "app": settings.app_name, "version": APP_VERSION},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health/ready")
def health_ready(request: Request):
    """Readiness — requires DB. Media/limiter status reported but do not fail ready."""
    from app.services.rate_limit import client_ip, enforce_rate_limit, limiter_health
    from app.services.storage import media_backend, media_health

    enforce_rate_limit(
        f"health-ready:ip:{client_ip(request)}",
        limit=120,
        window_sec=60,
    )
    timeout = float(settings.readiness_timeout_seconds)
    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="fos-ready")
    futures = {
        "db": executor.submit(_db_ping),
        "media": executor.submit(media_health),
        "limiter": executor.submit(limiter_health),
    }
    done, pending = wait(set(futures.values()), timeout=timeout)
    statuses: dict[str, str] = {}
    for name, future in futures.items():
        if future not in done:
            statuses[name] = "timeout"
            future.cancel()
            continue
        try:
            value = future.result()
            statuses[name] = value if isinstance(value, str) else "error"
        except Exception:  # noqa: BLE001
            logger.warning("health %s check failed", name, exc_info=True)
            statuses[name] = "error"
    executor.shutdown(wait=False, cancel_futures=True)
    db_status = statuses["db"]
    media_status = statuses["media"]
    limiter_status = statuses["limiter"]
    body = {
        "ok": db_status == "ok",
        "app": settings.app_name,
        "version": APP_VERSION,
        "db": db_status,
        "media_backend": media_backend(),
        "media": media_status,
        "limiter": limiter_status,
    }
    headers = {"Cache-Control": "no-store"}
    if db_status != "ok":
        return JSONResponse(status_code=503, content=body, headers=headers)
    return JSONResponse(content=body, headers=headers)


@app.get("/health")
def health(request: Request):
    """Backward-compatible ready check (same as /health/ready)."""
    return health_ready(request)


@app.get("/metrics")
def metrics(request: Request):
    """Prometheus text metrics. Optional METRICS_TOKEN gate."""
    from fastapi import HTTPException
    from fastapi.responses import PlainTextResponse

    from app.services.metrics import render_prometheus
    from app.services.rate_limit import client_ip, enforce_rate_limit, limiter_health
    from app.services.storage import media_health

    expected = (settings.metrics_token or "").strip()
    if expected:
        got = (request.headers.get("x-metrics-token") or "").strip()
        auth = (request.headers.get("authorization") or "").strip()
        bearer = ""
        if auth.lower().startswith("bearer "):
            bearer = auth[7:].strip()
        if not (_tok_ok(got, expected) or _tok_ok(bearer, expected)):
            raise HTTPException(
                401,
                "Metrics token required",
                headers={"WWW-Authenticate": 'Bearer realm="metrics"'},
            )
    enforce_rate_limit(f"metrics:ip:{client_ip(request)}", limit=30, window_sec=60)
    if expected:
        enforce_rate_limit("metrics:token", limit=60, window_sec=60)
    limiter_status = limiter_health()
    redis_configured = bool((settings.rate_limit_redis_url or "").strip())
    body = render_prometheus(
        app=settings.app_name,
        version=APP_VERSION,
        db_ok=_db_ping() == "ok",
        media_ok=media_health() == "ok",
        limiter=limiter_status,
        limiter_redis_up=(limiter_status == "redis") if redis_configured else None,
    )
    return PlainTextResponse(
        body,
        media_type="text/plain; version=0.0.4",
        headers={"Cache-Control": "no-store"},
    )
