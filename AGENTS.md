# Fos — Agent Guide

Read `.cursorrules` and `docs/PRODUCT.md` before changing code.

## What this repo is
Multi-tenant **field money** system: expenses, fuel, income, approvals, cash on hand.  
Stack: **FastAPI API** + **Expo mobile**. Built to sell to any small team.

## What this repo is NOT
- Not RJ Spending Bot
- Not Google Sheets–backed
- Not Telegram-first (bot bridge is post-v1)

## Layout
```
api/app/          FastAPI application
api/app/routers/  auth + records
mobile/           Expo app (App.tsx screens + src/api.ts)
docs/PRODUCT.md   Product logic and domain rules
```

## How to run (dev)
API: `cd api && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`  
Mobile: `cd mobile && npm install && EXPO_PUBLIC_API_URL=http://LAN_IP:8000 npx expo start`

## Change policy
Surgical edits only. Tenant isolation and approval flow are sacred unless the user explicitly changes product rules.
