#!/usr/bin/env python3
"""Live smoke against a running Fos API. Usage: smoke.py [base_url]"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SLUG = f"smokeco{int(time.time()) % 1000000}"


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(req) as res:
        raw = res.read().decode()
        return json.loads(raw) if raw else None


def main() -> None:
    health = call("GET", "/health")
    print("health:", health)

    reg = call(
        "POST",
        "/orgs/register",
        body={
            "name": "Smoke Co",
            "slug": SLUG,
            "currency": "IDR",
            "owner_email": f"owner+{SLUG}@example.com",
            "owner_name": "Owner",
            "owner_password": "secret12",
            "owner_password_confirm": "secret12",
        },
    )
    token = reg["access_token"]
    user_id = reg["user"]["id"]
    print("ok register", SLUG)

    call(
        "POST",
        "/orgs/invite",
        token,
        {
            "email": f"emp+{SLUG}@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
        },
    )

    rec = call(
        "POST",
        "/records",
        token,
        {
            "kind": "expense",
            "amount": 50000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    call("POST", f"/records/{rec['id']}/decide", token, {"approve": True})
    call(
        "POST",
        "/payouts",
        token,
        {"user_id": user_id, "kind": "expense_payout", "amount": 50000},
    )
    print("ok expense→approve→payout")

    income = call(
        "POST",
        "/records",
        token,
        {
            "kind": "income",
            "amount": 100000,
            "category": "Other",
            "payment_method": "cash",
            "purpose": "Other",
        },
    )
    call("POST", f"/records/{income['id']}/decide", token, {"approve": True})
    call(
        "POST",
        "/transfers",
        token,
        {"to_email": f"emp+{SLUG}@example.com", "amount": 25000, "comment": "smoke"},
    )

    req = urllib.request.Request(
        f"{BASE}/reports/export.csv?days=30",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as res:
        csv_len = len(res.read())
    print("ok income→transfer→csv", csv_len, "bytes")

    org = call("PATCH", "/orgs/me", token, {"name": "Smoke Co Renamed"})
    assert org["name"] == "Smoke Co Renamed"
    print("ok org rename")
    try:
        call("PATCH", "/orgs/me", token, {"currency": "USD"})
        raise SystemExit("expected currency lock after activity")
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
    print("ok currency lock")

    auto = call(
        "POST",
        "/records",
        token,
        {
            "kind": "expense",
            "amount": 1000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert auto["status"] == "approved"
    print("ok approve_now")

    adj = call(
        "POST",
        "/adjustments",
        token,
        {
            "user_id": user_id,
            "track": "spendings",
            "amount": 2500,
            "note": "smoke opening",
        },
    )
    bal = call("GET", "/records/balance/me", token)
    assert bal["spendings"] >= 2500
    call("POST", f"/adjustments/{adj['id']}/void", token, {"note": "smoke void"})
    print("ok adjustment")
    print("SMOKE_OK")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode(), file=sys.stderr)
        sys.exit(1)
