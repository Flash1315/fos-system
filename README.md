# Fos

**Fos** — multi-tenant field expenses for any small team.  
Mobile (Expo) + API. Built to sell; Ride & Joy can be the first customer later.

> Product: [`docs/PRODUCT.md`](docs/PRODUCT.md) · Rules: [`.cursorrules`](.cursorrules) · [`AGENTS.md`](AGENTS.md)  
> RJ bot knowledge: [`docs/RJ_BOT_REFERENCE.md`](docs/RJ_BOT_REFERENCE.md) · snapshot [`reference/rj-spending-bot/`](reference/rj-spending-bot/)

## Monorepo

```
fos-system/
  api/                        FastAPI + SQLAlchemy (ship)
  mobile/                     Expo app (ship)
  docs/                       Fos + RJ reference guides
  reference/rj-spending-bot/  Full RJ bot snapshot (read-only knowledge)
```

## Quick start — API

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open docs: http://127.0.0.1:8000/docs

### Tests

```bash
cd api
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -q
# or: bash scripts/smoke.sh
```

### Docker (API + Postgres)

```bash
docker compose up --build
```

> Compose is a **local/dev** stack (weak default `SECRET_KEY`, `CORS_ORIGINS=*`, published Postgres). Do not treat it as a production deploy.

### Production checklist

- Set `ENVIRONMENT=production` and a strong `SECRET_KEY` (≥32 chars, not a known default)
- Use Postgres (`DATABASE_URL=postgresql+psycopg2://…`); keep SQLite for local/dev only
- Set explicit `CORS_ORIGINS` (never `*` in production)
- Terminate TLS at a reverse proxy; set `ENABLE_HSTS=true` only behind HTTPS
- If the proxy forwards client IPs: `TRUST_X_FORWARDED_FOR=true` **and** `TRUSTED_PROXY_CIDRS=…`
- Persist `/app/uploads` (or use `MEDIA_BACKEND=s3` with `S3_BUCKET` + paired access/secret keys)
- Keep `RATE_LIMIT_ENABLED=true` (production refuses `false`); note limits are process-local
- Probe `GET /health` for liveness; OpenAPI/docs are hidden in production
- Mobile release builds need `EXPO_PUBLIC_API_URL` as an **https** API origin
- Image runs as non-root and includes Alembic (`alembic upgrade` on startup when available)

### Main endpoints

| Method | Path | Who |
|--------|------|-----|
| POST | `/orgs/register` | create company + owner |
| POST | `/auth/login` | email + password + `organization_slug` |
| POST | `/orgs/invite` | owner/manager invite user |
| GET | `/orgs/members` | team list |
| POST | `/records` | create expense / fuel / income |
| GET | `/records/mine` | my records |
| GET | `/records/pending` | manager queue |
| POST | `/records/{id}/decide` | approve / reject |
| GET | `/records/balance/me` | cash on hand + spendings |
| GET | `/records/balance/team` | manager team balances |
| GET | `/records/fuel/last-odometer` | last fuel mileage hint |
| POST | `/payouts` | expense payout / income handover |
| POST | `/adjustments` | opening / balance corrections |
| POST | `/transfers` | colleague cash transfer |
| GET | `/reports/org` | org totals |
| GET | `/reports/export.csv` | CSV export |
| POST | `/media/photo` | receipt photo (local or S3 via authenticated API) |

## Quick start — Mobile

```bash
cd mobile
npm install
export EXPO_PUBLIC_API_URL=http://YOUR_LAN_IP:8000
npx expo start
```

## Product v1 scope

- Organizations (tenants)
- Roles: owner / manager / employee
- Expense, Fuel, Income + approvals
- Cash on hand (simple formula)
- Team invite, org reports, receipt photo (local or S3)
- Expo app: auth, home, create, approvals, invite, team, reports, detail

## Not in v1 (later)

- Web admin / billing checkout
- Telegram thin client (outbound alerts already exist)
- Multi-currency FX
- White-label

## License

Proprietary — Flash1315 / Fos
