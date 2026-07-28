# Fos production deploy (API + Postgres)

This checklist is for a real host or managed stack. Local `docker compose up` remains **dev-only**.

## 1. Postgres

1. Provision PostgreSQL 14+ (managed preferred).
2. Create DB/user; require TLS from the API host.
3. Set:

```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/fos?sslmode=require
# or DB_SSLMODE=require when not in the URL
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_RECYCLE=1800
```

4. Production **refuses** SQLite `DATABASE_URL`.
5. On API start: Alembic `upgrade head` runs and **fails the process** if migrations error.

## 2. Secrets & HTTP

- `SECRET_KEY` ≥ 32 chars (not a known default)
- Explicit `CORS_ORIGINS` (never `*` or empty — at least one origin)
- Terminate TLS at a reverse proxy; `ENABLE_HSTS=true` only behind HTTPS
- If the proxy sets client IPs: `TRUST_X_FORWARDED_FOR=true` and `TRUSTED_PROXY_CIDRS=…`
- Keep `RATE_LIMIT_ENABLED=true` (required in production)

## 3. Media

- Persist `/app/uploads`, **or**
- `MEDIA_BACKEND=s3` with `S3_BUCKET` + paired access/secret keys

## 4. Boot / health

- Probe `GET /health/live` (liveness; use for container healthchecks) and `GET /health/ready` (DB; also reports `media` status without failing ready on media blips)
- Live/ready responses send `Cache-Control: no-store`
- Authenticated media file responses send `Cache-Control: no-store`
- Invite endpoints enforce per-org `invite-org:` rate limits
- Transfer endpoints enforce per-org `transfer-org:` rate limits
- Adjustment create/void enforce per-org `adjustment-org:` rate limits
- Payout create/batch/settle-approve enforce per-org `payout-org:` rate limits
- Record decide-batch enforces per-org `decide-batch-org:` rate limits
- Record comment/void/cancel/decide enforce per-org `comment-org:` / `void-org:` / `cancel-org:` / `decide-org:` rate limits
- Settlement requests enforce per-org `settle-request-org:` rate limits
- Team activate/role enforce per-org `team-org:` rate limits
- Media file responses send `X-Content-Type-Options: nosniff`
- CSV export responses send `Cache-Control: no-store`
- Persist `/app/uploads` or S3; content-addressed keys; cancels may remove unused receipt objects
- Idempotency rows are pruned on API startup (and on store)
- Ready reports `limiter` (`memory` / `redis` / `redis_error`) without failing on Redis blips; multi-worker should set `RATE_LIMIT_REDIS_URL`
- CSV export is rate-limited per user (10/min) and per org (20/min)
- `METRICS_TOKEN` is **required** in production; scrapers call `GET /metrics` with `Authorization: Bearer <token>`
- Production refuses `CORS_ORIGINS=*`; schema via Alembic only (no create_all)
- OpenAPI/docs are hidden when `ENVIRONMENT=production` (`/docs`, `/redoc`, `/openapi.json`)
- Example compose shape: [`docker-compose.prod.example.yml`](../docker-compose.prod.example.yml)

## 5. Mobile

- Release builds need `EXPO_PUBLIC_API_URL=https://…` (see [`docs/EAS.md`](EAS.md))

## 6. Multi-worker

Default image runs one uvicorn worker. For `uvicorn --workers N`:

- Set `RATE_LIMIT_REDIS_URL`
- Size `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` so `N × (pool + overflow)` fits Postgres

## 7. Optional next

- Managed Redis / object storage / observability outside this repo
- CSV exports neutralize formula prefixes (including fullwidth) and ship a UTF-8 BOM for Excel
- `ACCESS_TOKEN_EXPIRE_MINUTES` controls JWT lifetime; logout bumps `token_version` (revokes access + media JWTs on all devices)
