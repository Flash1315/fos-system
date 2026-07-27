from datetime import datetime, timedelta, timezone
from io import StringIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import MoneyRecord, Organization, Payout, RecordKind, RecordStatus, User, UserRole
from app.schemas import OrgReportOut, CategoryTotal, PurposeTotal
from app.services.balances import user_balance

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/org", response_model=OrgReportOut)
def org_report(
    days: int | None = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    oid = user.organization_id
    since = None
    if days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    def sum_approved(kind: RecordKind, payment: str | None = None) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == oid,
            MoneyRecord.kind == kind,
            MoneyRecord.status == RecordStatus.approved,
        )
        if payment is not None:
            q = q.filter(MoneyRecord.payment_method == payment)
        if since is not None:
            q = q.filter(MoneyRecord.created_at >= since)
        return float(q.scalar() or 0)

    expense = sum_approved(RecordKind.expense)
    fuel = sum_approved(RecordKind.fuel)
    income_cash = sum_approved(RecordKind.income, "cash")
    income_transfer = sum_approved(RecordKind.income, "transfer")
    pending_q = db.query(func.count(MoneyRecord.id)).filter(
        MoneyRecord.organization_id == oid,
        MoneyRecord.status == RecordStatus.pending,
    )
    if since is not None:
        pending_q = pending_q.filter(MoneyRecord.created_at >= since)
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
    )
    if since is not None:
        cat_q = cat_q.filter(MoneyRecord.created_at >= since)
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
        MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
    )
    if since is not None:
        purpose_q = purpose_q.filter(MoneyRecord.created_at >= since)
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
        cash_position=income_cash - expense - fuel,
        total_spendings=total_spendings,
        total_cash_held=total_cash_held,
        by_category=by_category,
        by_purpose=by_purpose,
    )


@router.get("/export.csv", response_class=PlainTextResponse)
def export_csv(
    days: int | None = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    oid = user.organization_id
    since = None
    if days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    q = db.query(MoneyRecord).filter(MoneyRecord.organization_id == oid)
    if since is not None:
        q = q.filter(MoneyRecord.created_at >= since)
    rows = q.order_by(MoneyRecord.created_at.asc()).limit(5000).all()

    buf = StringIO()
    buf.write(
        "type,id,kind,status,amount,currency,category,purpose,place,bike,"
        "payment_source,payment_method,created_by,created_at,comment\n"
    )
    for r in rows:
        creator = db.get(User, r.created_by)
        name = (creator.full_name if creator else "").replace(",", " ")
        comment = (r.comment or "").replace("\n", " ").replace(",", ";")
        kind = r.kind.value if hasattr(r.kind, "value") else str(r.kind)
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        buf.write(
            f"record,{r.id},{kind},{status},{r.amount},{r.currency},"
            f"{r.category},{r.purpose},{r.place},{r.bike},"
            f"{r.payment_source},{r.payment_method},{name},{r.created_at.isoformat()},{comment}\n"
        )

    pq = db.query(Payout).filter(Payout.organization_id == oid)
    if since is not None:
        pq = pq.filter(Payout.created_at >= since)
    for p in pq.order_by(Payout.created_at.asc()).limit(2000).all():
        u = db.get(User, p.user_id)
        name = (u.full_name if u else "").replace(",", " ")
        pkind = p.kind.value if hasattr(p.kind, "value") else str(p.kind)
        note = (p.note or "").replace("\n", " ").replace(",", ";")
        buf.write(
            f"payout,{p.id},{pkind},settled,{p.amount},{p.currency},"
            f",,,,{p.payment_method},{name},{p.created_at.isoformat()},{note}\n"
        )

    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fos-export.csv"'},
    )
