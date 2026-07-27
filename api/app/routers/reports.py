from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User, UserRole
from app.schemas import OrgReportOut, CategoryTotal

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/org", response_model=OrgReportOut)
def org_report(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    oid = user.organization_id

    def sum_approved(kind: RecordKind, payment: str | None = None) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == oid,
            MoneyRecord.kind == kind,
            MoneyRecord.status == RecordStatus.approved,
        )
        if payment is not None:
            q = q.filter(MoneyRecord.payment_method == payment)
        return float(q.scalar() or 0)

    expense = sum_approved(RecordKind.expense)
    fuel = sum_approved(RecordKind.fuel)
    income_cash = sum_approved(RecordKind.income, "cash")
    income_transfer = sum_approved(RecordKind.income, "transfer")
    pending = (
        db.query(func.count(MoneyRecord.id))
        .filter(MoneyRecord.organization_id == oid, MoneyRecord.status == RecordStatus.pending)
        .scalar()
        or 0
    )
    team = (
        db.query(func.count(User.id))
        .filter(User.organization_id == oid, User.is_active.is_(True))
        .scalar()
        or 0
    )

    cat_rows = (
        db.query(
            MoneyRecord.kind,
            MoneyRecord.category,
            func.coalesce(func.sum(MoneyRecord.amount), 0.0),
        )
        .filter(
            MoneyRecord.organization_id == oid,
            MoneyRecord.status == RecordStatus.approved,
        )
        .group_by(MoneyRecord.kind, MoneyRecord.category)
        .all()
    )
    by_category = [
        CategoryTotal(kind=k.value if hasattr(k, "value") else str(k), category=c or "—", total=float(t))
        for k, c, t in cat_rows
    ]

    return OrgReportOut(
        currency=currency,
        approved_expense_total=expense,
        approved_fuel_total=fuel,
        approved_income_cash=income_cash,
        approved_income_transfer=income_transfer,
        pending_count=int(pending),
        team_count=int(team),
        cash_position=income_cash - expense - fuel,
        by_category=by_category,
    )
