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
    User,
    UserRole,
)
from app.schemas import OrgReportOut, CategoryTotal, PurposeTotal, MyReportOut
from app.services.balances import user_balance

router = APIRouter(prefix="/reports", tags=["reports"])


def _parse_day(value: str | None, *, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        day = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "date_from/date_to must be YYYY-MM-DD") from exc
    if end:
        return day.replace(hour=23, minute=59, second=59)
    return day


def _window(
    days: int | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[datetime | None, datetime | None]:
    if date_from or date_to:
        since = _parse_day(date_from)
        until = _parse_day(date_to, end=True)
        if since and until and since > until:
            raise HTTPException(400, "date_from must be on or before date_to")
        return since, until
    if days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        return since, None
    return None, None


def _effective_at():
    return func.coalesce(MoneyRecord.occurred_at, MoneyRecord.created_at)


@router.get("/me", response_model=MyReportOut)
def my_report(
    days: int | None = Query(default=None, ge=1, le=3650),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
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
            q = q.filter(eff <= until)
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
        purpose_q = purpose_q.filter(eff <= until)
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
        cat_q = cat_q.filter(eff <= until)
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
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    oid = user.organization_id
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
            q = q.filter(eff <= until)
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
            q = q.filter(eff <= until)
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
        xfer_q = xfer_q.filter(eff <= until)
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
        pending_q = pending_q.filter(eff <= until)
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
        cat_q = cat_q.filter(eff <= until)
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
        purpose_q = purpose_q.filter(eff <= until)
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
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    import csv

    oid = user.organization_id
    since, until = _window(days, date_from, date_to)
    eff = _effective_at()

    q = db.query(MoneyRecord).filter(MoneyRecord.organization_id == oid)
    if since is not None:
        q = q.filter(eff >= since)
    if until is not None:
        q = q.filter(eff <= until)
    rows = q.order_by(MoneyRecord.created_at.asc()).limit(5000).all()

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
        ]
    )
    for r in rows:
        creator = db.get(User, r.created_by)
        name = creator.full_name if creator else ""
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
                r.category,
                r.purpose,
                r.place,
                r.bike,
                r.payment_source,
                r.payment_method,
                name,
                r.created_at.isoformat() if r.created_at else "",
                r.occurred_at.isoformat() if r.occurred_at else "",
                "",
                "",
                1 if r.is_voided else 0,
                r.comment or "",
            ]
        )

    pq = db.query(Payout).filter(Payout.organization_id == oid)
    if since is not None:
        pq = pq.filter(Payout.created_at >= since)
    if until is not None:
        pq = pq.filter(Payout.created_at <= until)
    for p in pq.order_by(Payout.created_at.asc()).limit(2000).all():
        u = db.get(User, p.user_id)
        name = u.full_name if u else ""
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
                p.payment_method,
                name,
                p.created_at.isoformat() if p.created_at else "",
                "",
                float(p.overpayment or 0),
                float(p.balance_after or 0),
                1 if p.is_voided else 0,
                (p.void_note or p.note or ""),
            ]
        )

    aq = db.query(BalanceAdjustment).filter(BalanceAdjustment.organization_id == oid)
    if since is not None:
        aq = aq.filter(BalanceAdjustment.occurred_at >= since)
    if until is not None:
        aq = aq.filter(BalanceAdjustment.occurred_at <= until)
    for a in aq.order_by(BalanceAdjustment.created_at.asc()).limit(2000).all():
        u = db.get(User, a.user_id)
        name = u.full_name if u else ""
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
                name,
                a.created_at.isoformat() if a.created_at else "",
                a.occurred_at.isoformat() if a.occurred_at else "",
                "",
                "",
                1 if a.is_voided else 0,
                a.note or "",
            ]
        )

    stamp = (date_from or date_to or (f"{days}d" if days else "all"))
    filename = f"fos-export-{stamp}.csv".replace("/", "-")
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
