# Fos — Agent Guide

Read in this order:
1. `.cursorrules`
2. `docs/PRODUCT.md`
3. `docs/RJ_BOT_REFERENCE.md`
4. For RJ domain detail: `reference/rj-spending-bot/CONTEXT.md`

## What this repo is
Multi-tenant **field money** system: expenses, fuel, income, approvals, cash on hand.  
Stack: **FastAPI API** + **Expo mobile**. Built to sell to any small team.

## Layout
```
<<<<<<< HEAD
api/app/          FastAPI application
api/app/routers/  auth, records, team, reports, media
mobile/           Expo app (App.tsx + src/screens)
docs/PRODUCT.md   Product logic and domain rules
docker-compose.yml  API + Postgres
=======
api/                         Fos FastAPI app (ship this)
mobile/                      Fos Expo app (ship this)
docs/                        Fos product + how to use RJ reference
reference/rj-spending-bot/   Full RJ Telegram bot snapshot (read-only domain knowledge)
>>>>>>> 1ca0972d46e05bb5ab58f67fc5baf678347bf487
```

## What this repo is NOT
- Fos is not a Telegram bot and not Sheets-backed
- `reference/` is not the Fos runtime — do not deploy it
- Do not change the live `RJ-Spending-bot` repo from a Fos task unless the user explicitly says so

## How to run Fos (dev)
API: `cd api && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`  
Mobile: `cd mobile && npm install && EXPO_PUBLIC_API_URL=http://LAN_IP:8000 npx expo start`

## Change policy
Surgical edits only in `api/` / `mobile/`. Tenant isolation and approval flow are sacred unless the user changes product rules.
