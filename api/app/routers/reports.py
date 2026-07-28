from datetime import datetime, timedelta, timezone
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import (
    BalanceAdjustment,
    MoneyRecord,
    Organization,
    Payout,
    RecordKind,
    RecordStatus,
    SettlementRequest,
    User,
    UserRole,
)
from app.schemas import OrgReportOut, CategoryTotal, PurposeTotal, MyReportOut
from app.services.balances import user_balance
from app.services.org_limits import require_org_member_capacity

router = APIRouter(prefix="/reports", tags=["reports"])


def _parse_day(value: str | None, *, end: bool = False) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if len(raw) != 10:
        raise HTTPException(400, "date_from/date_to must be YYYY-MM-DD")
    try:
        day = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "date_from/date_to must be YYYY-MM-DD") from exc
    if end:
        # Exclusive upper bound: date_to=YYYY-MM-DD means < next midnight
        return day + timedelta(days=1)
    return day


def _window(
    days: int | None,
    date_from: str | None,
    date_to: str | None,
    *,
    default_days: int | None = None,
) -> tuple[datetime | None, datetime | None]:
    if date_from or date_to:
        since = _parse_day(date_from)
        until = _parse_day(date_to, end=True)
        if since and until and since >= until:
            raise HTTPException(400, "date_from must be on or before date_to")
        if since and until and (until - since).days > 3650:
            raise HTTPException(400, "date range cannot exceed 3650 days")
        return since, until
    if days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        return since, None
    if default_days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=default_days)
        return since, None
    return None, None


_CSV_CELL_MAX = 2000


def _csv_text(value) -> str:
    """Neutralize spreadsheet formula injection for free-text cells."""
    if value is None:
        return ""
    s = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(s) > _CSV_CELL_MAX:
        s = s[: _CSV_CELL_MAX - 1] + "…"
    if s and s[0] in ("=", "+", "-", "@", "\t"):
        return "'" + s
    return s


def _effective_at():
    return func.coalesce(MoneyRecord.occurred_at, MoneyRecord.created_at)


@router.get("/me", response_model=MyReportOut)
def my_report(
    days: int | None = Query(default=None, ge=1, le=3650),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"report-me:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    bal = user_balance(db, user)
    since, until = _window(days, date_from, date_to)
    eff = _effective_at()

    def sum_kind(kind: RecordKind, payment: str | None = None) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == user.organization_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.kind == kind,
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.is_voided.is_(False),
            MoneyRecord.transfer_group_id.is_(None),
        )
        if payment is not None:
            q = q.filter(MoneyRecord.payment_method == payment)
        if since is not None:
            q = q.filter(eff >= since)
        if until is not None:
            q = q.filter(eff < until)
        return float(q.scalar() or 0)

    purpose_q = db.query(
        MoneyRecord.purpose,
        func.coalesce(func.sum(MoneyRecord.amount), 0.0),
    ).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.created_by == user.id,
        MoneyRecord.status == RecordStatus.approved,
        MoneyRecord.is_voided.is_(False),
        MoneyRecord.transfer_group_id.is_(None),
        MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
    )
    if since is not None:
        purpose_q = purpose_q.filter(eff >= since)
    if until is not None:
        purpose_q = purpose_q.filter(eff < until)
    by_purpose = [
        PurposeTotal(purpose=p or "—", total=float(t)) for p, t in purpose_q.group_by(MoneyRecord.purpose).all()
    ]

    cat_q = db.query(
        MoneyRecord.kind,
        MoneyRecord.category,
        func.coalesce(func.sum(MoneyRecord.amount), 0.0),
    ).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.created_by == user.id,
        MoneyRecord.status == RecordStatus.approved,
        MoneyRecord.is_voided.is_(False),
        MoneyRecord.transfer_group_id.is_(None),
    )
    if since is not None:
        cat_q = cat_q.filter(eff >= since)
    if until is not None:
        cat_q = cat_q.filter(eff < until)
    by_category = [
        CategoryTotal(kind=k.value if hasattr(k, "value") else str(k), category=c or "—", total=float(t))
        for k, c, t in cat_q.group_by(MoneyRecord.kind, MoneyRecord.category).all()
    ]

    return MyReportOut(
        currency=currency,
        cash_on_hand=bal["cash_on_hand"],
        spendings=bal["spendings"],
        approved_expense_total=sum_kind(RecordKind.expense),
        approved_fuel_total=sum_kind(RecordKind.fuel),
        approved_income_cash=sum_kind(RecordKind.income, "cash"),
        pending_count=bal["pending_count"],
        by_purpose=by_purpose,
        by_category=by_category,
    )


@router.get("/org", response_model=OrgReportOut)
def org_report(
    days: int | None = Query(default=None, ge=1, le=3650),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"report-org:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    oid = user.organization_id
    require_org_member_capacity(db, oid, active_only=True)
    since, until = _window(days, date_from, date_to)
    eff = _effective_at()

    def sum_approved(kind: RecordKind, payment: str | None = None) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == oid,
            MoneyRecord.kind == kind,
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.is_voided.is_(False),
            MoneyRecord.transfer_group_id.is_(None),
        )
        if payment is not None:
            q = q.filter(MoneyRecord.payment_method == payment)
        if since is not None:
            q = q.filter(eff >= since)
        if until is not None:
            q = q.filter(eff < until)
        return float(q.scalar() or 0)

    expense = sum_approved(RecordKind.expense)
    fuel = sum_approved(RecordKind.fuel)
    income_cash = sum_approved(RecordKind.income, "cash")
    income_transfer = sum_approved(RecordKind.income, "transfer")

    def sum_spend_source(sources: list[str]) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == oid,
            MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.is_voided.is_(False),
            MoneyRecord.transfer_group_id.is_(None),
            MoneyRecord.payment_source.in_(sources),
        )
        if since is not None:
            q = q.filter(eff >= since)
        if until is not None:
            q = q.filter(eff < until)
        return float(q.scalar() or 0)

    xfer_q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
        MoneyRecord.organization_id == oid,
        MoneyRecord.kind == RecordKind.expense,
        MoneyRecord.status == RecordStatus.approved,
        MoneyRecord.is_voided.is_(False),
        MoneyRecord.transfer_group_id.is_not(None),
    )
    if since is not None:
        xfer_q = xfer_q.filter(eff >= since)
    if until is not None:
        xfer_q = xfer_q.filter(eff < until)
    internal_transfer_total = float(xfer_q.scalar() or 0)

    spend_from_cash = sum_spend_source(["cash_on_hand", ""])
    spend_from_pocket = sum_spend_source(["my_pocket"])
    net_result = income_cash + income_transfer - expense - fuel
    cash_position = income_cash - spend_from_cash

    pending_q = db.query(func.count(MoneyRecord.id)).filter(
        MoneyRecord.organization_id == oid,
        MoneyRecord.status == RecordStatus.pending,
    )
    if since is not None:
        pending_q = pending_q.filter(eff >= since)
    if until is not None:
        pending_q = pending_q.filter(eff < until)
    pending = pending_q.scalar() or 0
    members = (
        db.query(User)
        .filter(User.organization_id == oid, User.is_active.is_(True))
        .all()
    )
    team_bals = [user_balance(db, m) for m in members]
    total_spendings = sum(b["spendings"] for b in team_bals)
    total_cash_held = sum(b["cash_on_hand"] for b in team_bals)

    cat_q = db.query(
        MoneyRecord.kind,
        MoneyRecord.category,
        func.coalesce(func.sum(MoneyRecord.amount), 0.0),
    ).filter(
        MoneyRecord.organization_id == oid,
        MoneyRecord.status == RecordStatus.approved,
        MoneyRecord.is_voided.is_(False),
        MoneyRecord.transfer_group_id.is_(None),
    )
    if since is not None:
        cat_q = cat_q.filter(eff >= since)
    if until is not None:
        cat_q = cat_q.filter(eff < until)
    cat_rows = cat_q.group_by(MoneyRecord.kind, MoneyRecord.category).all()
    by_category = [
        CategoryTotal(kind=k.value if hasattr(k, "value") else str(k), category=c or "—", total=float(t))
        for k, c, t in cat_rows
    ]

    purpose_q = db.query(
        MoneyRecord.purpose,
        func.coalesce(func.sum(MoneyRecord.amount), 0.0),
    ).filter(
        MoneyRecord.organization_id == oid,
        MoneyRecord.status == RecordStatus.approved,
        MoneyRecord.is_voided.is_(False),
        MoneyRecord.transfer_group_id.is_(None),
        MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
    )
    if since is not None:
        purpose_q = purpose_q.filter(eff >= since)
    if until is not None:
        purpose_q = purpose_q.filter(eff < until)
    purpose_rows = purpose_q.group_by(MoneyRecord.purpose).all()
    by_purpose = [
        PurposeTotal(purpose=p or "—", total=float(t)) for p, t in purpose_rows
    ]

    return OrgReportOut(
        currency=currency,
        approved_expense_total=expense,
        approved_fuel_total=fuel,
        approved_income_cash=income_cash,
        approved_income_transfer=income_transfer,
        pending_count=int(pending),
        team_count=len(members),
        net_result=net_result,
        cash_position=cash_position,
        spend_from_cash=spend_from_cash,
        spend_from_pocket=spend_from_pocket,
        internal_transfer_total=internal_transfer_total,
        total_spendings=total_spendings,
        total_cash_held=total_cash_held,
        by_category=by_category,
        by_purpose=by_purpose,
    )


@router.get("/export.csv", response_class=PlainTextResponse)
def export_csv(
    days: int | None = Query(default=None, ge=1, le=3650),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    import csv

    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"export:{user.organization_id}:{user.id}",
        limit=10,
        window_sec=60,
    )

    oid = user.organization_id
    # Unbounded export is expensive — default to last 365 days when no window given.
    since, until = _window(days, date_from, date_to, default_days=365)
    eff = _effective_at()

    q = db.query(MoneyRecord).filter(MoneyRecord.organization_id == oid)
    if since is not None:
        q = q.filter(eff >= since)
    if until is not None:
        q = q.filter(eff < until)
    rows = q.order_by(MoneyRecord.created_at.asc(), MoneyRecord.id.asc()).limit(5001).all()
    if len(rows) > 5000:
        raise HTTPException(400, "Export too large — narrow the date range")

    name_ids = {r.created_by for r in rows}
    names: dict[int, str] = {}
    if name_ids:
        names = {
            u.id: u.full_name
            for u in db.query(User)
            .filter(User.organization_id == oid, User.id.in_(name_ids))
            .all()
        }

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "type",
            "id",
            "kind",
            "status",
            "amount",
            "currency",
            "category",
            "purpose",
            "place",
            "bike",
            "payment_source",
            "payment_method",
            "created_by",
            "created_at",
            "occurred_at",
            "overpayment",
            "balance_after",
            "is_voided",
            "comment",
            "liters",
            "odometer",
            "transfer_group_id",
            "payout_id",
        ]
    )
    for r in rows:
        name = names.get(r.created_by, "")
        kind = r.kind.value if hasattr(r.kind, "value") else str(r.kind)
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        writer.writerow(
            [
                "record",
                r.id,
                kind,
                status,
                r.amount,
                r.currency,
                _csv_text(r.category),
                _csv_text(r.purpose),
                _csv_text(r.place),
                _csv_text(r.bike),
                _csv_text(r.payment_source),
                _csv_text(r.payment_method),
                _csv_text(name),
                r.created_at.isoformat() if r.created_at else "",
                r.occurred_at.isoformat() if r.occurred_at else "",
                "",
                "",
                1 if r.is_voided else 0,
                _csv_text(r.comment or ""),
                r.liters if r.liters is not None else "",
                r.odometer if r.odometer is not None else "",
                _csv_text(r.transfer_group_id or ""),
                "",
            ]
        )

    pq = db.query(Payout).filter(Payout.organization_id == oid)
    if since is not None:
        pq = pq.filter(Payout.created_at >= since)
    if until is not None:
        pq = pq.filter(Payout.created_at < until)
    payouts = pq.order_by(Payout.created_at.asc(), Payout.id.asc()).limit(2001).all()
    if len(payouts) > 2000:
        raise HTTPException(400, "Export too large — narrow the date range")
    if len(rows) + len(payouts) > 7000:
        raise HTTPException(400, "Export too large — narrow the date range")
    payout_ids = {p.user_id for p in payouts}
    missing = payout_ids - names.keys()
    if missing:
        names.update(
            {
                u.id: u.full_name
                for u in db.query(User)
                .filter(User.organization_id == oid, User.id.in_(missing))
                .all()
            }
        )
    for p in payouts:
        name = names.get(p.user_id, "")
        pkind = p.kind.value if hasattr(p.kind, "value") else str(p.kind)
        writer.writerow(
            [
                "payout",
                p.id,
                pkind,
                "voided" if p.is_voided else "settled",
                p.amount,
                p.currency,
                "",
                "",
                "",
                "",
                "",
                _csv_text(p.payment_method),
                _csv_text(name),
                p.created_at.isoformat() if p.created_at else "",
                "",
                float(p.overpayment or 0),
                float(p.balance_after or 0),
                1 if p.is_voided else 0,
                _csv_text(p.void_note or p.note or ""),
                "",
                "",
                "",
                "",
            ]
        )

    aq = db.query(BalanceAdjustment).filter(BalanceAdjustment.organization_id == oid)
    if since is not None:
        aq = aq.filter(BalanceAdjustment.occurred_at >= since)
    if until is not None:
        aq = aq.filter(BalanceAdjustment.occurred_at < until)
    adjustments = aq.order_by(BalanceAdjustment.created_at.asc(), BalanceAdjustment.id.asc()).limit(2001).all()
    if len(adjustments) > 2000:
        raise HTTPException(400, "Export too large — narrow the date range")
    if len(rows) + len(payouts) + len(adjustments) > 8000:
        raise HTTPException(400, "Export too large — narrow the date range")
    adj_ids = {a.user_id for a in adjustments}
    missing = adj_ids - names.keys()
    if missing:
        names.update(
            {
                u.id: u.full_name
                for u in db.query(User)
                .filter(User.organization_id == oid, User.id.in_(missing))
                .all()
            }
        )
    for a in adjustments:
        name = names.get(a.user_id, "")
        track = a.track.value if hasattr(a.track, "value") else str(a.track)
        writer.writerow(
            [
                "adjustment",
                a.id,
                track,
                "voided" if a.is_voided else "posted",
                a.amount,
                "",
                "",
                "",
                "",
                "",
                track,
                "",
                _csv_text(name),
                a.created_at.isoformat() if a.created_at else "",
                a.occurred_at.isoformat() if a.occurred_at else "",
                "",
                "",
                1 if a.is_voided else 0,
                _csv_text(a.note or ""),
                "",
                "",
                "",
                "",
            ]
        )

    sq = db.query(SettlementRequest).filter(SettlementRequest.organization_id == oid)
    if since is not None:
        sq = sq.filter(SettlementRequest.created_at >= since)
    if until is not None:
        sq = sq.filter(SettlementRequest.created_at < until)
    requests = sq.order_by(SettlementRequest.created_at.asc(), SettlementRequest.id.asc()).limit(2001).all()
    if len(requests) > 2000:
        raise HTTPException(400, "Export too large — narrow the date range")
    if len(rows) + len(payouts) + len(adjustments) + len(requests) > 9000:
        raise HTTPException(400, "Export too large — narrow the date range")
    req_ids = {req.user_id for req in requests}
    missing = req_ids - names.keys()
    if missing:
        names.update(
            {
                u.id: u.full_name
                for u in db.query(User)
                .filter(User.organization_id == oid, User.id.in_(missing))
                .all()
            }
        )
    for req in requests:
        name = names.get(req.user_id, "")
        rkind = req.kind.value if hasattr(req.kind, "value") else str(req.kind)
        rstatus = req.status.value if hasattr(req.status, "value") else str(req.status)
        writer.writerow(
            [
                "settlement_request",
                req.id,
                rkind,
                rstatus,
                req.amount,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                _csv_text(name),
                req.created_at.isoformat() if req.created_at else "",
                req.decided_at.isoformat() if req.decided_at else "",
                float(req.settled_amount or 0) if req.settled_amount is not None else "",
                "",
                0,
                _csv_text(req.note or ""),
                "",
                "",
                "",
                req.payout_id or "",
            ]
        )

    stamp = (date_from or date_to or (f"{days}d" if days else "365d"))
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(stamp))[:48] or "all"
    filename = f"fos-export-{safe}.csv"
    # ASCII filename + RFC 5987 UTF-8 fallback for clients that support it
    from urllib.parse import quote

    disposition = (
        f'attachment; filename="{filename}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )
