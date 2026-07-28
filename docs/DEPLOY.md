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
- Explicit `CORS_ORIGINS` (never `*`)
- Terminate TLS at a reverse proxy; `ENABLE_HSTS=true` only behind HTTPS
- If the proxy sets client IPs: `TRUST_X_FORWARDED_FOR=true` and `TRUSTED_PROXY_CIDRS=…`
- Keep `RATE_LIMIT_ENABLED=true` (required in production)

## 3. Media

- Persist `/app/uploads`, **or**
- `MEDIA_BACKEND=s3` with `S3_BUCKET` + paired access/secret keys

## 4. Boot / health

- Probe `GET /health/live` (liveness) and `GET /health/ready` (DB)
- Optional scrape `GET /metrics` (set `METRICS_TOKEN` in production)
- Production refuses `CORS_ORIGINS=*`; schema via Alembic only (no create_all)
- OpenAPI/docs are hidden when `ENVIRONMENT=production`
- Example compose shape: [`docker-compose.prod.example.yml`](../docker-compose.prod.example.yml)

## 5. Mobile

- Release builds need `EXPO_PUBLIC_API_URL=https://…` (see [`docs/EAS.md`](EAS.md))

## 6. Multi-worker

Default image runs one uvicorn worker. For `uvicorn --workers N`:

- Set `RATE_LIMIT_REDIS_URL`
- Size `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` so `N × (pool + overflow)` fits Postgres

## 7. Optional next

- Shared rate limits: `RATE_LIMIT_REDIS_URL` (Redis INCR fixed-window; falls back to process-local on errors)
- Hot-path DB indexes via Alembic `20260728_0002`
- Managed Redis / object storage / observability outside this repo
