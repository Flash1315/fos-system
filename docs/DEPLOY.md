# Fos production deploy (API + Postgres)

This checklist is for a real host or managed stack. Local `docker compose up` remains **dev-only**.

- Production images should install Python dependencies from `api/requirements.lock.txt` and pin base/service images by digest.

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
DB_POOL_TIMEOUT=30
DB_CONNECT_TIMEOUT=10
```

4. Production **refuses** SQLite `DATABASE_URL`.
5. On API start: Alembic `upgrade head` runs and **fails the process** if migrations error.

## 2. Secrets & HTTP

- `SECRET_KEY` ≥ 32 chars (not a known default)
- Set stable `JWT_ISSUER` and `JWT_AUDIENCE` values (both default to `fos`);
  changing either invalidates existing access and media tokens.
- Explicit `CORS_ORIGINS` (never `*` or empty — at least one origin)
- If set, `PUBLIC_APP_URL` must be HTTPS in production.
- Terminate TLS at a reverse proxy; `ENABLE_HSTS=true` only behind HTTPS
- If the proxy sets client IPs: `TRUST_X_FORWARDED_FOR=true` and `TRUSTED_PROXY_CIDRS=…`
- Keep `RATE_LIMIT_ENABLED=true` (required in production)
- Request ceilings are configurable with `JSON_BODY_LIMIT_BYTES` (default 256 KiB)
  and `UPLOAD_BODY_LIMIT_BYTES` (default 9 MiB).

## 3. Media

- Persist `/app/uploads`, **or**
- `MEDIA_BACKEND=s3` with `S3_BUCKET` + paired access/secret keys
- `S3_BUCKET` is a bare bucket name (no `/` path segments).

## 4. Boot / health

- Probe `GET /health/live` (liveness; use for container healthchecks) and `GET /health/ready` (DB; also reports `media` status without failing ready on media blips)
- `READINESS_TIMEOUT_SECONDS` (default `3`) caps readiness dependency checks.
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
- Photo upload enforces per-org `upload-org:` rate limits
- Telegram chat/test enforce per-org `telegram-org:` rate limits
- Member reset-password/token enforce per-org `reset-password-org:` / `reset-token-org:`
- Org ledger/pending lists enforce per-org `records-list-org:` rate limits
- Record create/update enforce per-org `record-write-org:` rate limits
- Org profile update enforces per-org `org-update-org:` rate limits
- Settlement cancel enforces per-org `settle-cancel-org:` rate limits
- Team balances enforce per-org `balances-read-org:` rate limits
- Org report enforces per-org `reports-read-org:` rate limits
- Org and personal payout/settlement/adjustment reads enforce per-org `finance-list-org:` rate limits
- Password changes and logout enforce per-org `password-org:` / `logout-org:` rate limits
- Accept-invite enforces `accept-invite-org:` only after the invite token resolves to an organization
- Categories, media-token, and fuel-odometer reads enforce per-org `categories-org:` / `media-token-org:` / `fuel-odo-org:` rate limits
- Billing status reads enforce per-org `billing-me-org:` rate limits
- Auth /me and org /me enforce per-org `auth-me-org:` / `org-me-org:` rate limits
- Personal balance reads enforce per-org `balance-read-org:` rate limits
- Team members/directory reads enforce per-org `members-read-org:` / `directory-read-org:` rate limits
- `/metrics` sends `Cache-Control: no-store`; CORS allows `X-Metrics-Token`
- Media file responses send `X-Content-Type-Options: nosniff`
- CSV export responses send `Cache-Control: no-store`
- Persist `/app/uploads` or S3; content-addressed keys; cancels may remove unused receipt objects
- Idempotency rows are pruned on API startup (and on store)
- Non-money invite, team, Telegram, org-update, plan, and accept-invite mutations support `Idempotency-Key`
- Ready reports `limiter` (`memory` / `redis` / `redis_error`) without failing on Redis blips; multi-worker should set `RATE_LIMIT_REDIS_URL`
- CSV export is rate-limited per user (10/min) and per org (20/min)
- `METRICS_TOKEN` is **required** in production; scrapers call `GET /metrics` with `Authorization: Bearer <token>`
- `MEDIA_TOKEN_EXPIRE_MINUTES` (default `15`) controls receipt-image token lifetime.
- `SMTP_TIMEOUT_SECONDS` (default `5`) caps optional mail delivery attempts.
- Production refuses `CORS_ORIGINS=*`; schema via Alembic only (no create_all)
- OpenAPI/docs are hidden when `ENVIRONMENT=production` (`/docs`, `/redoc`, `/openapi.json`)
- Example compose shape: [`docker-compose.prod.example.yml`](../docker-compose.prod.example.yml)

- JWT access/media tokens carry iss/aud/jti claims validated on decode

- Production requires JWT_ISSUER and JWT_AUDIENCE non-empty values

- Production Redis limiter URLs must use rediss:// TLS

- PUBLIC_APP_URL must be absolute HTTPS when set in production

- S3_BUCKET must be a bare bucket name without path separators

- Empty environment variables do not override Settings defaults

- Media token lifetime is configurable via MEDIA_TOKEN_EXPIRE_MINUTES

- JSON and upload body ceilings are configurable via settings

- SMTP timeout is configurable via SMTP_TIMEOUT_SECONDS

- Readiness dependency probes honor READINESS_TIMEOUT_SECONDS

- Corrupt password hashes authenticate as invalid credentials

- Database sessions roll back before close after handler exceptions

- Boolean JSON amounts are rejected by money parsing

- Audit detail redacts password/token/secret fields

- Sanitized receipt recompression is byte-capped

- Approve/reject-all pages pending IDs up to the batch cap

- Native CSV export shares a temporary file via expo-sharing

- CreateScreen drafts persist field state without receipt bytes

- Alembic upgrades on Postgres take a session advisory lock

- CI installs Python deps from requirements.lock.txt

- Hardening inventory script fails CI when org keys drift

- Workflow concurrency cancels superseded branch runs

- API responses send Pragma no-cache and Expires 0

- Metrics unauthorized responses include WWW-Authenticate Bearer

- Ready probes are rate-limited separately from liveness

## 5. Mobile

- Release builds need `EXPO_PUBLIC_API_URL=https://…` (see [`docs/EAS.md`](EAS.md))

## 6. Multi-worker

Default image runs one uvicorn worker. For `uvicorn --workers N`:

- Set `RATE_LIMIT_REDIS_URL`
- Production Redis URLs must use `rediss://` TLS.
- Size `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` so `N × (pool + overflow)` fits Postgres

## 7. Optional next

- Managed Redis / object storage / observability outside this repo
- CSV exports neutralize formula prefixes (including fullwidth) and ship a UTF-8 BOM for Excel
- `ACCESS_TOKEN_EXPIRE_MINUTES` controls JWT lifetime; logout bumps `token_version` (revokes access + media JWTs on all devices)
