#!/usr/bin/env bash
# Smoke: register → expense → approve → report
set -euo pipefail
BASE="${FOS_API:-http://127.0.0.1:8000}"
SLUG="smoke-$(date +%s)"

echo "health: $(curl -sS "$BASE/health")"
REG=$(curl -sS -X POST "$BASE/orgs/register" -H 'Content-Type: application/json' -d "{
  \"name\": \"Smoke Co\", \"slug\": \"$SLUG\", \"currency\": \"IDR\",
  \"owner_email\": \"owner+$SLUG@example.com\", \"owner_name\": \"Owner\", \"owner_password\": \"secret12\"
}")
TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<<"$REG")
AUTH="Authorization: Bearer $TOKEN"

REC=$(curl -sS -X POST "$BASE/records" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"kind":"expense","amount":12345,"category":"supplies","comment":"smoke"}')
RID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$REC")
curl -sS -X POST "$BASE/records/$RID/decide" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"approve":true}' >/dev/null
curl -sS "$BASE/reports/org" -H "$AUTH" | python3 -m json.tool
echo "OK slug=$SLUG record=$RID"
