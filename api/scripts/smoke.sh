#!/usr/bin/env bash
# Quick live smoke against a running Fos API (default http://127.0.0.1:8000).
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
SLUG="smokeco$(date +%s | tail -c 6)"

REG=$(curl -sf -X POST "$BASE/orgs/register" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Smoke Co\",\"slug\":\"$SLUG\",\"currency\":\"IDR\",\"owner_email\":\"owner+$SLUG@example.com\",\"owner_name\":\"Owner\",\"owner_password\":\"secret12\"}")
TOKEN=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['access_token'])" "$REG")
USER_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['user']['id'])" "$REG")
H="Authorization: Bearer $TOKEN"
echo "ok register $SLUG"

curl -sf -X POST "$BASE/orgs/invite" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"email\":\"emp+$SLUG@example.com\",\"full_name\":\"Emp\",\"role\":\"employee\",\"password\":\"secret12\"}" >/dev/null

REC=$(curl -sf -X POST "$BASE/records" -H "$H" -H 'Content-Type: application/json' \
  -d '{"kind":"expense","amount":50000,"category":"Taxi","purpose":"Office","payment_source":"my_pocket"}')
RID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$REC")
curl -sf -X POST "$BASE/records/$RID/decide" -H "$H" -H 'Content-Type: application/json' \
  -d '{"approve":true}' >/dev/null
curl -sf -X POST "$BASE/payouts" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"user_id\":$USER_ID,\"kind\":\"expense_payout\",\"amount\":50000}" >/dev/null
echo "ok expense→approve→payout"

INC=$(curl -sf -X POST "$BASE/records" -H "$H" -H 'Content-Type: application/json' \
  -d '{"kind":"income","amount":100000,"category":"Other","payment_method":"cash","purpose":"Other"}')
IID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$INC")
curl -sf -X POST "$BASE/records/$IID/decide" -H "$H" -H 'Content-Type: application/json' \
  -d '{"approve":true}' >/dev/null
curl -sf -X POST "$BASE/transfers" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"to_email\":\"emp+$SLUG@example.com\",\"amount\":25000,\"comment\":\"smoke\"}" >/dev/null
curl -sf "$BASE/reports/export.csv?days=30" -H "$H" >/dev/null
echo "ok income→transfer→csv"
echo SMOKE_OK
