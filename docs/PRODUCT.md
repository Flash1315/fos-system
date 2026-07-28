# Fos — Product Characteristics & Logic

## 1. Positioning

| | |
|---|---|
| **Name** | Fos |
| **Repo** | `Flash1315/fos-system` |
| **One-liner** | Field money for small teams — expenses, fuel, income, approvals, cash on hand |
| **Market** | Any small team (not RJ-only) |
| **Brand** | Independent sellable product; not Ride & Joy branded |
| **First customer (later)** | Ride & Joy can connect as a tenant via API; RJ Telegram bot stays a separate codebase |
| **License** | Proprietary — Flash1315 / Fos |

## 2. Goals (v1)

1. Multi-tenant SaaS core (organizations)
2. Roles and simple approvals
3. Record expense / fuel / income from phone
4. Show personal cash on hand
5. API-first so web, bot, or other clients can attach later

## 3. Non-goals (v1)

- Photo upload to object storage (field exists; storage later)
- Web admin / billing / subscriptions UI
- Telegram bot inside this repo
- Multi-currency FX conversion
- White-label theming
- GPS tracking, calendar, CRM, bike fleet (those stay in RJ bot if needed)
- Merging with `RJ-Spending-bot`

## 4. Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + SQLAlchemy | Fast to ship, OpenAPI docs, easy to sell as API |
| Auth | JWT (HS256) + passlib `pbkdf2_sha256` | Stateless mobile auth; avoid bcrypt 72-byte issues |
| DB local | SQLite (`fos.db`) | Zero setup |
| DB prod-ready | Postgres via `DATABASE_URL` | `.env.example` documents URL |
| Mobile | Expo + React Native (TypeScript) | One codebase → iOS/Android; store path later |
| Token storage | `expo-secure-store` | Device-secure session |

## 5. Monorepo layout

```
fos-system/
  api/
    app/
      main.py           app + CORS + /health
      config.py         settings from env
      db.py             engine + Session
      models.py         Organization, User, MoneyRecord
      schemas.py        Pydantic I/O
      auth.py           hash/JWT/deps
      routers/auth.py   register, login, invite, me
      routers/records.py create, mine, pending, decide, balance
    requirements.txt
    .env.example
  mobile/
    App.tsx             screens: auth, home, create, approve
    src/api.ts          HTTP client + types
    app.json            Expo name Fos, package app.fos.system
  docs/PRODUCT.md       this file
  .cursorrules          coding rules for agents
  AGENTS.md             short agent entrypoint
  README.md             quick start
```

## 6. Domain model

### Organization (tenant)
- `name`, unique `slug` (`^[a-z0-9-]+$`), `currency` (default `IDR`)
- All users and records belong to one org
- **Hard rule:** every business query filters by `organization_id`

### User
- Unique `(organization_id, email)`
- `role`: `owner` | `manager` | `employee`
- `hashed_password`, `is_active`
- Owner is created at `/orgs/register`

### MoneyRecord
- `kind`: `expense` | `fuel` | `income`
- `status`: `pending` | `approved` | `rejected`
- `amount` > 0, `currency` copied from org at create time
- Common: `category`, `comment`, `photo_url` (optional stub)
- Fuel extras: `liters`, `odometer`
- Income extras: `client_name`, `payment_method` (`cash` / `transfer`)
- Audit: `created_by`, `created_at`, `decided_by`, `decided_at`

## 7. Roles & permissions

| Action | employee | manager | owner |
|---|---|---|---|
| Register org (becomes owner) | — | — | yes (bootstrap) |
| Login | yes | yes | yes |
| Invite users | no | yes | yes |
| Invite another owner | no | no | yes |
| Create expense/fuel/income | yes | yes | yes |
| See own records / own balance | yes | yes | yes |
| See pending queue | no | yes | yes |
| Approve / reject | no | yes | yes |

Insufficient role → HTTP `403`.

## 8. Business flows

### 8.1 Register company
1. `POST /orgs/register` with org name, slug, currency, owner email/name/password
2. Creates `Organization` + `User(role=owner)`
3. Returns JWT + user

### 8.2 Login
1. `POST /auth/login` with `email`, `password`, `organization_slug`
2. Email alone is not enough (same email can exist in other orgs)
3. Returns JWT + user  
OAuth2 form variant: username = `email@@organization-slug` → `/auth/login-form`

### 8.3 Invite
1. Owner/manager `POST /orgs/invite`
2. Creates user in **same** org with given role + password

### 8.4 Create money record
1. Authenticated user `POST /records` (`expense` / `fuel` / `income`)
2. Starts as `pending` unless manager/owner uses `approve_now`
3. Spend defaults to `payment_source=my_pocket`; income uses `payment_method=cash|transfer`
4. Currency taken from organization (locked after first money activity)

### 8.5 Approval
1. Owner/manager `GET /records/pending`
2. `POST /records/{id}/decide` with `{ "approve": true|false, "note": "…" }`
3. Reject **requires** a non-empty note; note appended to comment
4. Approving spend from `cash_on_hand` fails if held cash is insufficient

### 8.6 Dual balance (RJ-style cutoffs)
Per user, inside their org, after last non-voided settlement:

```
spendings =
  approved expense/fuel with payment_source=my_pocket
  + carry balance_after − overpayment + spendings adjustments
  (since last expense_payout)

cash_on_hand =
  approved cash income − spend from cash_on_hand
  + carry balance_after + cash adjustments
  (since last income_handover)
```

Also returns `pending_count`, `reserved_*` / `available_*` from pending settlement requests,
and `last_expense_payout_at` / `last_income_handover_at`.

Related: `/payouts`, `/payouts/requests`, `/transfers`, `/adjustments`, `/reports/export.csv`.

## 9. API surface (v1)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | liveness |
| POST | `/orgs/register` | no | create tenant + owner |
| POST | `/auth/login` | no | JWT |
| POST | `/auth/login-form` | no | OAuth2 password form |
| GET | `/auth/me` | yes | current user |
| GET | `/orgs/me` | yes | current org |
| POST | `/orgs/invite` | owner/manager | add user |
| GET | `/orgs/members` | owner/manager | team list |
| POST | `/orgs/members/{id}/active` | owner | activate/deactivate |
| POST | `/records` | yes | create record |
| GET | `/records/categories` | yes | category presets |
| GET | `/records/mine` | yes | my records |
| GET | `/records/org` | owner/manager | org ledger |
| GET | `/records/pending` | owner/manager | approval queue |
| GET | `/records/balance/me` | yes | dual balance + reserved/available |
| GET | `/records/balance/team` | owner/manager | team balances |
| GET | `/records/{id}` | yes | record detail |
| POST | `/records/{id}/decide` | owner/manager | approve/reject |
| POST | `/records/{id}/void` | owner/manager | void approved (if unlocked) |
| POST | `/payouts` | owner/manager | expense payout / income handover |
| POST | `/payouts/requests` | yes | request settlement |
| POST | `/adjustments` | owner/manager | opening / corrections |
| POST | `/transfers` | yes | colleague cash transfer |
| GET | `/reports/org` | owner/manager | org totals |
| GET | `/reports/export.csv` | owner/manager | CSV export |
| POST | `/media/photo` | yes | receipt image upload (local) |
| GET | `/media/files/{org}/{file}` | yes | fetch uploaded image |

Interactive docs: `/docs` when API is running.

## 10. Mobile UX (v1)

Screens in `mobile/App.tsx` (+ `mobile/src/screens/`):
1. **Auth** — org slug; login or register company; email/password
2. **Home** — dual balance + reserved hints, my records (incl. voided filter), actions
3. **Create** — kind/amount/category/purpose + fuel odometer + on-behalf + optional photo
4. **Approvals** — pending list → approve/reject (reject note required) / batch
5. **Invite / Team / Account** — members, roles, settlement requests, org settings
6. **Reports / My stats / Ledger** — totals, CSV share, org search
7. **Settlements / Balances / Payout history** — pay/take, openings, voids
8. **Transfer / Record detail** — cash transfer; void/comment/edit pending

Config: `EXPO_PUBLIC_API_URL` (phone needs LAN IP, not `127.0.0.1`).  
Brand in UI: **Fos** — “Field money. Clear books.”

Local stack: `docker-compose.yml` runs API + Postgres.

## 11. Security rules

- Never store plaintext passwords
- JWT secret from env (`SECRET_KEY`); change in production
- Set `ENVIRONMENT=production` so weak/default `SECRET_KEY` fails startup (min 32 chars)
- Prefer explicit `CORS_ORIGINS` (not `*`) in production
- If `TRUST_X_FORWARDED_FOR=true`, also set `TRUSTED_PROXY_CIDRS` to your proxy ranges
- Soft org size ceiling: `MAX_ORG_MEMBERS` (default 300) for invites, team balances / directory / org report
- JWT `org` claim must match the user's organization; invite tokens stored hashed only
- Logout bumps `token_version` and revokes **all** sessions for the account
- Passwords: min 8 characters with at least one letter and one digit
- Optional `ENABLE_HSTS` behind HTTPS terminators
- CSV / report exports default to the last 365 days when no window is given; free-text cells truncated
- Rate limits are process-local (not shared across workers)
- All record mutations scoped to caller’s `organization_id`
- Do not leak other orgs’ data in list/balance endpoints
- CORS configurable via `CORS_ORIGINS`

## 12. Environment

```bash
# api/.env
APP_NAME=Fos
ENVIRONMENT=development
SECRET_KEY=change-me-in-production
DATABASE_URL=sqlite:///./fos.db
# DATABASE_URL=postgresql+psycopg2://fos:fos@localhost:5432/fos
ACCESS_TOKEN_EXPIRE_MINUTES=10080
CORS_ORIGINS=*
# TRUST_X_FORWARDED_FOR=true
# TRUSTED_PROXY_CIDRS=10.0.0.0/8
# MAX_ORG_MEMBERS=300
```

Mobile: `EXPO_PUBLIC_API_URL=http://<host>:8000`

## 13. Relationship to Ride & Joy

| | RJ Spending Bot | Fos |
|---|---|---|
| Repo | `Flash1315/RJ-Spending-bot` | `Flash1315/fos-system` |
| Interface | Telegram | Expo + API |
| Data | Google Sheets / bot state | SQL tenants |
| Brand | Ride & Joy ops | Fos (sellable) |
| Future link | May call Fos API as one tenant | Stays generic |

**Do not** copy RJ chat routing, Sheets IDs, or GPS into Fos unless a future explicit integration task says so.

## 14. Roadmap hints (not committed work)

- Photo upload (R2/S3) + attach to record
- Org-wide balance / reports for owners
- Web dashboard + billing
- Telegram thin client using same API
- Auto-approve policy for owners (product decision)
- Multi-currency / FX
- White-label

## 15. Definition of done for v1 scaffold

- [x] Register org + JWT login
- [x] Invite with roles
- [x] Create expense/fuel/income as pending
- [x] Manager/owner approve/reject
- [x] Dual balance (cash on hand + spendings) + mobile home
- [x] Settlements, transfers, adjustments, settlement requests
- [x] Expo auth/home/create/approve/ledger/reports/settlements screens
- [x] Team / reports / ledger / receipt photo (local)
- [x] README quick start
- [x] API pytest + CI workflow
- [ ] Production Postgres deploy (compose file ready — verify in target env)
- [ ] Store builds (EAS config stub in `mobile/eas.json`)
