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

- Web admin / billing / subscriptions UI
- Full Telegram bot client inside this repo (outbound org alerts only)
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
| POST | `/media/photo` | yes | receipt image upload (local or S3 via authenticated API) |
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
- Optional `ENABLE_HSTS` behind HTTPS terminators; OpenAPI/docs hidden when `ENVIRONMENT=production`
- `billing_status` of `canceled` or `past_due` puts the organization into a read-only billing freeze; media remains available through the authenticated API (local or S3)
- Billing freeze matrix:
  - Blocked: money creates/approve/void, payouts, adjustments, transfers, invites, org edits, team mutations, Telegram changes/tests, photo upload, and plan changes
  - Allowed: login, view, cancel pending record, cancel settlement request, password change, and accept-invite
- Production refuses padded/blank `SECRET_KEY` and `TRUST_X_FORWARDED_FOR` without valid `TRUSTED_PROXY_CIDRS`
- Reactivating an inactive member uses the active-seat ceiling (does not treat existing rows as new invites)
- SMTP/Telegram outbound I/O capped (~5s); Telegram event alerts run after the response when possible
- Only the creator can DELETE-cancel a pending record; managers reject with a note
- Audit comment append truncates older text so cancel/reject/void never block on length
- Trusted XFF parses IPs, caps hops, and walks right→left past trusted proxies
- Unsettled invitees (`must_set_password`) excluded from directory, balances, and money targets
- Idempotency keys pruned after `IDEMPOTENCY_TTL_HOURS` (default 72)
- CSV / report exports default to the last 365 days when no window is given; free-text cells truncated; settlement `settled_amount` is its own column (not under `overpayment`)
- Production refuses `RATE_LIMIT_ENABLED=false`; process-local limiter hard-caps unique keys
- Settlement-request cancel idempotency replay re-checks ownership/manager role
- Mobile release builds require `EXPO_PUBLIC_API_URL` (https); upload media failures return 503
- API Docker image includes Alembic + runs as non-root; Compose is for local/dev only
- Compose Postgres binds `127.0.0.1` only; API healthcheck uses `start_period`
- EAS preview/production require https EXPO_PUBLIC_API_URL (`docs/EAS.md`)
- Optional Redis rate limiter + composite indexes for money/payout/idempotency lists
- Approving into a settled cycle requires `allow_closed_cycle`; photo uploads support Idempotency-Key
- Invite/reset issuer always receives the raw token (email is best-effort)
- Mobile soft-retries GET and Idempotency-Key requests on network/502/503/429; honors Retry-After
- Closed-cycle Approve anyway / create approve_now sends allow_closed_cycle; AppState probes /health/live and refreshes list screens
- Production requires METRICS_TOKEN for /metrics; prod compose example includes it + API healthcheck
- Photo filenames are content-addressed (sha256 prefix); cancel deletes unreferenced receipt objects; S3 skips rewrite on existing key
- SecureStore uses device-only accessibility; media JWT cached ~14m; resume refresh bus after live probe
- Billing freeze banner on write screens; JWT retained on billing 403; cancel pending still allowed
- `/health/ready` reports media + limiter probes (non-blocking); idempotency rows pruned at API startup; `fos_media_up` / `fos_limiter_redis_up`
- Account freeze UX covers settlement request/approve; Reports/MyReport resume-refresh; write screens re-check billing on resume
- Auth client validates email/currency + submit lock; invite/reset offer Share after success
- Validation errors return string `detail` + X-Request-Id; request logs use cardinality-safe paths; empty prod CORS refused
- CI version sync + `/health/ready` docker smoke (asserts container reports APP_VERSION)
- RecordDetail gates comment/void under freeze; receipt soft-fails without blocking the record
- Auth can forget remembered slug/email; shared offline copy across boot/resume/fetch
- Login/register returns `expires_in`; expired JWT → Session expired; logout revokes media JWTs
- CSV export strips NUL/fullwidth formula prefixes and adds UTF-8 BOM; Redis limiter always expires keys
- Payout history voids gated under billing freeze; Invite validates email; Balances void modal re-checks freeze
- Password change remains allowed under freeze; CSV export capped per-user and per-org
- Access JWT role claim must match DB role; `/health/live`+`/ready` send `Cache-Control: no-store`; OpenAPI hidden in prod
- Home/Approve/Team/Balances resume freeze re-check; confirm-path freeze gates; client `expires_in` → `fos_token_exp`; invite-org rate limit; media `Cache-Control: no-store`
- Production refuses SQLite `DATABASE_URL`; Alembic upgrade fails hard in production
- Postgres pool/SSL knobs: `DB_POOL_*`, `DB_SSLMODE`; see `docs/DEPLOY.md`
- Accept-invite allowed during billing freeze; money idempotency replays before writable gate
- Local media I/O errors → 503; runtime image excludes pytest (`requirements-dev.txt`)
- Rate limits use Redis when `RATE_LIMIT_REDIS_URL` is set; otherwise process-local
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
# SMTP_HOST=  SMTP_PORT=587  PUBLIC_APP_URL=https://app.example.com
# MEDIA_BACKEND=s3  S3_BUCKET=…  S3_ACCESS_KEY=…  S3_SECRET_KEY=…
# TELEGRAM_BOT_TOKEN=  BILLING_PLAN_SWITCH=false
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

- Web dashboard + billing checkout
- Telegram thin client using same API (beyond outbound alerts)
- Auto-approve policy for owners (product decision)
- Multi-currency / FX
- White-label
- Heavier analytics indexes / read replicas

## 15. Definition of done for v1 scaffold

- [x] Register org + JWT login
- [x] Invite with roles
- [x] Create expense/fuel/income as pending
- [x] Manager/owner approve/reject
- [x] Dual balance (cash on hand + spendings) + mobile home
- [x] Settlements, transfers, adjustments, settlement requests
- [x] Expo auth/home/create/approve/ledger/reports/settlements screens
- [x] Team / reports / ledger / receipt photo (local or S3 via authenticated media API)
- [x] README quick start
- [x] API pytest + CI workflow
- [ ] Production Postgres deploy (compose file ready — verify in target env)
- [ ] Store builds (EAS config stub in `mobile/eas.json`)
- Soft-fail report reloads; Create teammate/categories retry; Transfer/RecordDetail resume freeze; `transfer-org:` rate limit; CSV export `Cache-Control: no-store`
- Soft-fail load-more/Team; Invite/Account settle freeze re-check; `adjustment-org`/`payout-org`/`decide-batch-org` limits; demo login requires full env; prod `/docs` 404 CI
- Confirm-path billingMe on Team/Approve/Payout/Balances/Account; PayoutHistory soft-fail; org limits comment/void/cancel/decide/settle-request/team; soft-retry GET/Idem only; media nosniff; ready media CI
- Payout batch confirm freeze; Approve rejectAll/Balances void billingMe; Team reset freeze; upload/telegram/reset/list org limits; Auth inline form errors; Create photo quiet attach; metrics no-store + X-Metrics-Token CORS
- Soft-fail retains stale lists; pane-isolated Balances/Account; resume refresh for Payout/filters; Auth API errors inline; record-write/org-update/settle-cancel + balances/reports/finance-list org limits; early-error header parity
- v0.7.121–0.7.220 hardening: shared org budgets, non-money idempotency, security/config matrices, mobile stale-response guards, pinned/audited CI, and route inventory
