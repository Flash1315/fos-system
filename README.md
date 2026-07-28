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
