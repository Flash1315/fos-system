# Fos

**Fos** — multi-tenant field expenses for any small team.  
Mobile (Expo) + API. Built to sell; Ride & Joy can be the first customer later.

> Full product logic & rules: [`docs/PRODUCT.md`](docs/PRODUCT.md) · Agent rules: [`.cursorrules`](.cursorrules) · [`AGENTS.md`](AGENTS.md)

## Monorepo

```
fos-system/
  api/       FastAPI + SQLAlchemy (SQLite locally, Postgres ready)
  mobile/    Expo (React Native) app
  docs/      Product specification
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

### Docker (API + Postgres)

```bash
docker compose up --build
```

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
| GET | `/records/balance/me` | cash on hand |
| GET | `/reports/org` | org totals |
| POST | `/media/photo` | receipt photo (local storage) |

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
- Team invite, org reports, receipt photo (local)
- Expo app: auth, home, create, approvals, invite, team, reports, detail

## Not in v1 (later)

- Photo upload to S3/R2 (local upload works now)
- Web admin / billing
- Telegram bot bridge
- Multi-currency FX
- White-label

## License

Proprietary — Flash1315 / Fos
