"""Period statistics: calendar lessons + sheet finances."""

from datetime import datetime, timedelta

from utils.calendar import get_events_for_period, parse_event, WITA
from utils.sheets import (
    get_sheet, SHEET_EXPENSES, SHEET_INCOME, SHEET_RENTALS,
    _is_sheet_data_row, _parse_amount, _parse_row_datetime, _parse_expense_datetime,
    INC_COL_CATEGORY, INC_COL_AMOUNT, INC_COL_EMPLOYEE, INC_COL_PURPOSE,
    EXP_COL_CATEGORY, EXP_COL_AMOUNT, EXP_COL_EMPLOYEE, EXP_COL_PURPOSE, EXP_COL_PAYMENT_SOURCE,
    RENT_COL_STATUS, RENT_COL_INSTRUCTOR, RENT_COL_TOTAL, RENT_COL_DELIVERY_DATE,
    RENTAL_REVENUE_STATUSES, _pad_rental_row, format_idr,
)


PERIOD_LABELS = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days", 0: "All time"}


def _period_cutoff(days: int):
    if days and days > 0:
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    return None


def _is_countable_lesson(parsed: dict) -> bool:
    summary = (parsed.get("summary") or "").lower()
    if any(k in summary for k in ("vacation", "day off", "day-off", "off day", "holiday")):
        return False
    return bool(parsed.get("instructors")) or parsed.get("duration_min", 0) > 0


def get_lesson_stats(days: int = 30) -> dict:
    events = get_events_for_period(days)
    by_instructor = {}
    by_site = {}
    total_minutes = 0
    lesson_count = 0
    for event in events:
        parsed = parse_event(event)
        if not _is_countable_lesson(parsed):
            continue
        lesson_count += 1
        total_minutes += parsed.get("duration_min") or 0
        instructors = parsed.get("instructors") or ["Unassigned"]
        for name in instructors:
            by_instructor[name] = by_instructor.get(name, 0) + 1
        site = (parsed.get("training_site") or "Unknown").strip() or "Unknown"
        by_site[site] = by_site.get(site, 0) + 1
    return {
        "lesson_count": lesson_count,
        "total_hours": round(total_minutes / 60, 1),
        "by_instructor": dict(sorted(by_instructor.items(), key=lambda x: -x[1])),
        "by_site": dict(sorted(by_site.items(), key=lambda x: -x[1])),
    }


def get_financial_stats(days: int = 30) -> dict:
    cutoff = _period_cutoff(days)
    income_total = 0
    expense_total = 0
    income_by_employee = {}
    income_by_category = {}
    income_by_purpose = {}
    expense_by_employee = {}
    expense_by_category = {}
    expense_by_purpose = {}
    expense_my_pocket = 0
    expense_cash_on_hand = 0

    try:
        inc_rows = get_sheet(SHEET_INCOME).get_all_values()[1:]
    except Exception:
        inc_rows = []
    for row in inc_rows:
        if not _is_sheet_data_row(row):
            continue
        row_dt = _parse_row_datetime(row[0], row[1] if len(row) > 1 else "")
        if cutoff and (not row_dt or row_dt < cutoff):
            continue
        amount = _parse_amount(row[INC_COL_AMOUNT] if len(row) > INC_COL_AMOUNT else "")
        if amount is None:
            continue
        income_total += amount
        emp = row[INC_COL_EMPLOYEE] if len(row) > INC_COL_EMPLOYEE else "?"
        cat = row[INC_COL_CATEGORY] if len(row) > INC_COL_CATEGORY else "?"
        purpose = row[INC_COL_PURPOSE] if len(row) > INC_COL_PURPOSE else "?"
        income_by_employee[emp] = income_by_employee.get(emp, 0) + amount
        income_by_category[cat] = income_by_category.get(cat, 0) + amount
        if purpose:
            income_by_purpose[purpose] = income_by_purpose.get(purpose, 0) + amount

    try:
        exp_rows = get_sheet(SHEET_EXPENSES).get_all_values()[1:]
    except Exception:
        exp_rows = []
    for row in exp_rows:
        if not _is_sheet_data_row(row):
            continue
        row_dt = _parse_expense_datetime(row[0], row[1] if len(row) > 1 else "")
        if cutoff and (not row_dt or row_dt < cutoff):
            continue
        amount = _parse_amount(row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else "")
        if amount is None:
            continue
        expense_total += amount
        emp = row[EXP_COL_EMPLOYEE] if len(row) > EXP_COL_EMPLOYEE else "?"
        cat = row[EXP_COL_CATEGORY] if len(row) > EXP_COL_CATEGORY else "?"
        purpose = row[EXP_COL_PURPOSE] if len(row) > EXP_COL_PURPOSE else "?"
        source = row[EXP_COL_PAYMENT_SOURCE] if len(row) > EXP_COL_PAYMENT_SOURCE else "My pocket"
        expense_by_employee[emp] = expense_by_employee.get(emp, 0) + amount
        expense_by_category[cat] = expense_by_category.get(cat, 0) + amount
        if purpose:
            expense_by_purpose[purpose] = expense_by_purpose.get(purpose, 0) + amount
        if str(source).strip() == "Cash on hand":
            expense_cash_on_hand += amount
        else:
            expense_my_pocket += amount

    rental_count = 0
    rental_revenue = 0
    rental_by_instructor = {}
    try:
        rent_rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception:
        rent_rows = []
    for row in rent_rows:
        row = _pad_rental_row(row)
        status = str(row[RENT_COL_STATUS]).strip().lower()
        if status not in RENTAL_REVENUE_STATUSES:
            continue
        delivery = row[RENT_COL_DELIVERY_DATE] if len(row) > RENT_COL_DELIVERY_DATE else ""
        from utils.sheets import parse_date
        d = parse_date(delivery)
        if cutoff and (not d or d.replace(tzinfo=None) < cutoff):
            continue
        rental_count += 1
        try:
            amount = int(str(row[RENT_COL_TOTAL] or 0).replace(",", "") or 0)
        except ValueError:
            amount = 0
        rental_revenue += amount
        instructor = str(row[RENT_COL_INSTRUCTOR] or "").strip() or "—"
        rental_by_instructor[instructor] = rental_by_instructor.get(instructor, 0) + 1

    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "net": income_total - expense_total,
        "expense_my_pocket": expense_my_pocket,
        "expense_cash_on_hand": expense_cash_on_hand,
        "income_by_employee": dict(sorted(income_by_employee.items(), key=lambda x: -x[1])),
        "income_by_category": dict(sorted(income_by_category.items(), key=lambda x: -x[1])),
        "income_by_purpose": dict(sorted(income_by_purpose.items(), key=lambda x: -x[1])),
        "expense_by_employee": dict(sorted(expense_by_employee.items(), key=lambda x: -x[1])),
        "expense_by_category": dict(sorted(expense_by_category.items(), key=lambda x: -x[1])),
        "expense_by_purpose": dict(sorted(expense_by_purpose.items(), key=lambda x: -x[1])),
        "rental_count": rental_count,
        "rental_revenue": rental_revenue,
        "rental_by_instructor": dict(sorted(rental_by_instructor.items(), key=lambda x: -x[1])),
    }


def get_full_period_stats(days: int = 30) -> dict:
    return {
        "days": days,
        "period_label": PERIOD_LABELS.get(days, f"Last {days} days"),
        "lessons": get_lesson_stats(days),
        "finance": get_financial_stats(days),
    }


def format_top_amounts(items: dict, limit: int = 6) -> list[str]:
    lines = []
    for key, amount in list(items.items())[:limit]:
        if amount:
            lines.append(f"• {key}: {format_idr(amount)}")
    return lines


def format_full_period_report(stats: dict) -> str:
    period = stats["period_label"]
    lessons = stats["lessons"]
    fin = stats["finance"]
    lines = [
        f"📈 <b>Full statistics</b>",
        f"📅 Period: <b>{period}</b>",
        "",
        "📚 <b>Lessons (Calendar)</b>",
        f"• Total lessons: <b>{lessons['lesson_count']}</b>",
        f"• Total hours: <b>{lessons['total_hours']}</b>",
    ]
    if lessons["by_instructor"]:
        lines.append("• By instructor:")
        for name, count in lessons["by_instructor"].items():
            lines.append(f"  — {name}: <b>{count}</b>")
    if lessons["by_site"]:
        lines.append("• By site:")
        for site, count in list(lessons["by_site"].items())[:8]:
            lines.append(f"  — {site}: {count}")

    lines.extend([
        "",
        "💰 <b>Income</b>",
        f"• Total: <b>{format_idr(fin['income_total'])}</b>",
    ])
    if fin["income_by_employee"]:
        lines.append("• By employee:")
        lines.extend(format_top_amounts(fin["income_by_employee"], 8))
    if fin["income_by_category"]:
        lines.append("• By category:")
        for cat, amt in list(fin["income_by_category"].items())[:6]:
            lines.append(f"  — {cat}: {format_idr(amt)}")

    lines.extend([
        "",
        "💸 <b>Expenses</b>",
        f"• Total: <b>{format_idr(fin['expense_total'])}</b>",
        f"• My pocket: {format_idr(fin['expense_my_pocket'])}",
        f"• Cash on hand: {format_idr(fin['expense_cash_on_hand'])}",
    ])
    if fin["expense_by_employee"]:
        lines.append("• By employee:")
        lines.extend(format_top_amounts(fin["expense_by_employee"], 8))

    lines.extend([
        "",
        "🏍 <b>Rentals (completed)</b>",
        f"• Count: <b>{fin['rental_count']}</b>",
        f"• Revenue (Rentals sheet): <b>{format_idr(fin['rental_revenue'])}</b>",
    ])
    if fin["rental_by_instructor"]:
        lines.append("• By instructor:")
        for name, count in fin["rental_by_instructor"].items():
            lines.append(f"  — {name}: {count}")

    lines.extend([
        "",
        f"📊 <b>Net (Income − Expenses):</b> {format_idr(fin['net'])}",
    ])
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text
