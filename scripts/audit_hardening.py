#!/usr/bin/env python3
"""Verify that every expected organization-scoped rate-limit key is wired."""

from __future__ import annotations

import re
import sys
from pathlib import Path


EXPECTED_ORG_KEYS = {
    "directory-read-org",
    "members-read-org",
    "balance-read-org",
    "org-me-org",
    "auth-me-org",
    "accept-invite-org",
    "adjustment-org",
    "balances-read-org",
    "billing-me-org",
    "cancel-org",
    "categories-org",
    "comment-org",
    "decide-batch-org",
    "decide-org",
    "export-org",
    "finance-list-org",
    "fuel-odo-org",
    "invite-org",
    "logout-org",
    "media-token-org",
    "org-update-org",
    "password-org",
    "payout-org",
    "payouts-org",
    "record-write-org",
    "records-list-org",
    "records-org",
    "report-org",
    "reports-read-org",
    "reset-password-org",
    "reset-token-org",
    "settle-cancel-org",
    "settle-request-org",
    "team-org",
    "telegram-org",
    "transfer-org",
    "upload-org",
    "void-org",
}

KEY_PATTERN = re.compile(
    r"""enforce_rate_limit\(\s*f?["']([a-z][a-z0-9-]*-org):""",
    re.MULTILINE,
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    router_dir = root / "api" / "app" / "routers"
    found: set[str] = set()
    for router in sorted(router_dir.glob("*.py")):
        found.update(KEY_PATTERN.findall(router.read_text(encoding="utf-8")))

    missing = EXPECTED_ORG_KEYS - found
    if missing:
        print("Missing expected org rate-limit keys:", file=sys.stderr)
        for key in sorted(missing):
            print(f"  - {key}:", file=sys.stderr)
        return 1

    print(f"Hardening inventory OK: {len(EXPECTED_ORG_KEYS)} org keys present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
