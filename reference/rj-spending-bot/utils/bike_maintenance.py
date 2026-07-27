"""Bike service / repair history from expense comments and issue reports."""

import re
from datetime import datetime

SERVICE_CATEGORIES = ("Bike service", "Tires pressure / Wheel repair")


def parse_work_description(comment: str = "", place: str = "", category: str = "") -> str:
    """Best-effort label for what was repaired — comment first, then shop/place."""
    comment = (comment or "").strip()
    place = (place or "").strip()
    if " — " in place:
        place = place.split(" — ", 1)[-1].strip()

    match = re.match(r"^\[([^\]]+)\]\s*(.*)$", comment, re.I | re.S)
    if match:
        item = match.group(1).strip()
        rest = match.group(2).strip()
        if rest:
            return f"{item} — {rest}"
        return item
    if comment:
        return comment
    if place:
        return place
    return category or "Service"


def get_bike_service_log(bike_name: str, days: int = 365) -> dict:
    from utils.sheets import (
        get_expenses_for_bike, get_bike_issues_for_bike, _parse_expense_datetime,
        _parse_mileage_km, parse_date, _parse_amount,
    )

    records = []
    for row in get_expenses_for_bike(bike_name, SERVICE_CATEGORIES, limit=0, days=days):
        comment = row.get("comment") or ""
        place = row.get("place") or ""
        work = parse_work_description(comment, place, row.get("category", ""))
        dt = _parse_expense_datetime(row.get("date", ""), row.get("time") or "00:00")
        km = _parse_mileage_km(row.get("mileage"))
        amount = _parse_amount(row.get("amount"))
        records.append({
            "source": "expense",
            "date": row.get("date"),
            "time": row.get("time"),
            "dt": dt,
            "work": work,
            "category": row.get("category", ""),
            "employee": row.get("employee") or "—",
            "km": km,
            "amount": amount,
            "comment": comment,
            "place": place,
        })

    for issue in get_bike_issues_for_bike(bike_name, limit=0, open_only=False):
        desc = (issue.get("description") or "").strip()
        if not desc:
            continue
        d = parse_date(issue.get("date", ""))
        dt = d.replace(hour=0, minute=0, second=0, microsecond=0) if d else None
        records.append({
            "source": "issue",
            "date": issue.get("date"),
            "time": issue.get("time"),
            "dt": dt,
            "work": desc,
            "category": "Bike issue",
            "employee": issue.get("reported_by") or "—",
            "km": 0,
            "amount": None,
            "status": issue.get("status", ""),
        })

    records.sort(key=lambda r: r.get("dt") or datetime.min, reverse=True)
    for r in records:
        r.pop("dt", None)

    return {
        "records": records,
        "expense_count": sum(1 for r in records if r["source"] == "expense"),
        "issue_count": sum(1 for r in records if r["source"] == "issue"),
    }


def format_service_log_lines(records: list, max_items: int = 12) -> list[str]:
    if not records:
        return ["• No service or repair records in this period."]
    lines = []
    for rec in records[:max_items]:
        src = "🔧" if rec.get("source") == "expense" else "⚠️"
        work = rec.get("work") or "—"
        emp = rec.get("employee") or "—"
        extra = []
        if rec.get("km"):
            extra.append(f"odo {rec['km']:,} km".replace(",", "."))
        if rec.get("amount"):
            from utils.sheets import format_idr
            extra.append(format_idr(rec["amount"]))
        if rec.get("source") == "issue" and rec.get("status"):
            extra.append(str(rec["status"]))
        suffix = f" | {' | '.join(extra)}" if extra else ""
        lines.append(f"{src} {rec.get('date', '—')} — <b>{work}</b> — {emp}{suffix}")
    if len(records) > max_items:
        lines.append(f"… +{len(records) - max_items} more")
    return lines
