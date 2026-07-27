#!/usr/bin/env python3
"""One-off: move Alex same-day expenses to timestamps after today's expense payout."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.sheets import (
    fix_expense_times_after_payout,
    get_all_balances,
    format_idr,
    now_date,
)


def main():
    employee = "Alex"
    today = now_date()
    fixed = fix_expense_times_after_payout(employee, today)
    balances = get_all_balances().get(employee, {})
    spendings = balances.get("effective_spendings", 0)
    held = balances.get("held_by_employee", 0)
    print(f"Fixed {fixed} expense row(s) for {employee} on {today}")
    print(f"Balance now — Spendings: {format_idr(spendings)}, Cash on hand: {format_idr(held)}")
    print(f"Since payout: {balances.get('last_exp_payout', '—')}")
    print(f"Since handover: {balances.get('last_inc_handover', '—')}")


if __name__ == "__main__":
    main()
