"""Per-user balance helpers — RJ get_all_balances style, multi-tenant SQL."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import MoneyRecord, Payout, PayoutKind, RecordKind, RecordStatus, User


def last_payout_at(db: Session, org_id: int, user_id: int, kind: PayoutKind):
    row = (
        db.query(Payout)
        .filter(
            Payout.organization_id == org_id,
            Payout.user_id == user_id,
            Payout.kind == kind,
        )
        .order_by(Payout.created_at.desc())
        .first()
    )
    return row.created_at if row else None


def user_balance(db: Session, user: User) -> dict:
    org_id = user.organization_id
    since_hand = last_payout_at(db, org_id, user.id, PayoutKind.income_handover)
    since_pay = last_payout_at(db, org_id, user.id, PayoutKind.expense_payout)

    def sum_income_cash() -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == org_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.kind == RecordKind.income,
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.payment_method == "cash",
        )
        if since_hand is not None:
            q = q.filter(MoneyRecord.created_at > since_hand)
        return float(q.scalar() or 0)

    def sum_out(sources: list[str], since) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == org_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.payment_source.in_(sources),
        )
        if since is not None:
            q = q.filter(MoneyRecord.created_at > since)
        return float(q.scalar() or 0)

    income_cash = sum_income_cash()
    from_cash = sum_out(["cash_on_hand", ""], since_hand)
    spendings_raw = sum_out(["my_pocket"], since_pay)
    overpay = 0.0
    if since_pay is not None:
        cut = (
            db.query(Payout)
            .filter(
                Payout.organization_id == org_id,
                Payout.user_id == user.id,
                Payout.kind == PayoutKind.expense_payout,
                Payout.created_at == since_pay,
            )
            .first()
        )
        if cut is not None:
            overpay = float(cut.overpayment or 0)
    spendings = max(0.0, spendings_raw - overpay)
    pending = (
        db.query(func.count(MoneyRecord.id))
        .filter(
            MoneyRecord.organization_id == org_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.status == RecordStatus.pending,
        )
        .scalar()
        or 0
    )
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "cash_on_hand": income_cash - from_cash,
        "spendings": spendings,
        "owed_to_employee": spendings,
        "pending_count": int(pending),
    }
