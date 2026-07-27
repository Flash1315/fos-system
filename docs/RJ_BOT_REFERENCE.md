# How Fos uses the RJ Spending Bot reference

## Why this exists
Owner wants Fos agents to have **full knowledge** of the live Ride & Joy Telegram bot: flows, sheets, roles, rentals, GPS, finance rules.  
That code lives in:

```
reference/rj-spending-bot/
```

Canonical human/agent brief inside that folder: **`CONTEXT.md`**.

## Hard boundaries
| | Fos product (`api/`, `mobile/`) | RJ reference (`reference/rj-spending-bot/`) |
|---|---|---|
| Purpose | Sellable multi-tenant app | Domain/ops knowledge + migration inspiration |
| Runtime | Yes — develop & deploy | No — do not run as Fos, do not deploy from here |
| Data | SQL tenants | Google Sheets + Telegram + Calendar |
| Brand | Fos | Ride & Joy |
| Change policy | Surgical edits to ship Fos | Treat as **read-only** unless user explicitly asks to update the snapshot |

## What to learn from the bot (for Fos design)
- Expense / fuel / income categories and employee cash logic
- Approvals / manager vs instructor mental model
- Rental delivery/return checklists (future modules)
- Invoice / payout concepts (future)
- What RJ will need when it becomes a Fos tenant later

## What NOT to port blindly
- `BOT_TOKEN`, chat IDs, Sheets IDs, GPS vendor keys
- aiogram handlers as-is
- Google Sheets as primary DB
- Notification routing to Telegram groups
- Hardcoded single-company employees list → use Fos orgs/roles instead

## When implementing Fos features
1. Read `docs/PRODUCT.md` + `.cursorrules` (Fos rules win for code in `api/` / `mobile/`).
2. If domain unclear, read `reference/rj-spending-bot/CONTEXT.md` then the matching `handlers/*.py`.
3. Re-implement against Fos API/SQL multi-tenant model — do not copy Sheets calls into Fos API.

## Updating the snapshot
Only when the user asks: refresh from current `RJ-Spending-bot` into `reference/rj-spending-bot/`, still excluding secrets and runtime state.
