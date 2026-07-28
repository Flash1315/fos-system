"""Per-user balance helpers — RJ get_all_balances style, multi-tenant SQL."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AdjustmentTrack,
    BalanceAdjustment,
    MoneyRecord,
    Payout,
    PayoutKind,
    RecordKind,
    RecordStatus,
    User,
)

# Prefer occurred_at when present (late entries), else created_at
_effective_at = func.coalesce(MoneyRecord.occurred_at, MoneyRecord.created_at)
_adj_at = func.coalesce(BalanceAdjustment.occurred_at, BalanceAdjustment.created_at)


def last_payout(db: Session, org_id: int, user_id: int, kind: PayoutKind) -> Payout | None:
    return (
        db.query(Payout)
        .filter(
            Payout.organization_id == org_id,
            Payout.user_id == user_id,
            Payout.kind == kind,
            Payout.is_voided.is_(False),
        )
        .order_by(Payout.created_at.desc())
        .first()
    )


def last_payout_at(db: Session, org_id: int, user_id: int, kind: PayoutKind):
    row = last_payout(db, org_id, user_id, kind)
    return row.created_at if row else None


def record_effective_at(rec: MoneyRecord):
    return rec.occurred_at or rec.created_at


def settlement_kind_for_record(rec: MoneyRecord) -> PayoutKind | None:
    """Which payout cycle 'covers' this approved record, if any."""
    if rec.kind == RecordKind.income and (rec.payment_method or "") == "cash":
        return PayoutKind.income_handover
    if rec.kind in (RecordKind.expense, RecordKind.fuel):
        source = rec.payment_source or "cash_on_hand"
        if source == "my_pocket":
            return PayoutKind.expense_payout
        return PayoutKind.income_handover
    return None


def record_locked_by_settlement(db: Session, rec: MoneyRecord) -> bool:
    """True if a non-voided payout cutoff already includes this record."""
    if rec.status != RecordStatus.approved or rec.is_voided:
        return False
    kind = settlement_kind_for_record(rec)
    if kind is None:
        return False
    cut = last_payout(db, rec.organization_id, rec.created_by, kind)
    if cut is None:
        return False
    eff = record_effective_at(rec)
    if eff is None:
        return False
    return eff <= cut.created_at


def can_void_record(db: Session, rec: MoneyRecord) -> bool:
    if rec.status != RecordStatus.approved or rec.is_voided:
        return False
    if rec.transfer_group_id:
        siblings = (
            db.query(MoneyRecord)
            .filter(
                MoneyRecord.organization_id == rec.organization_id,
                MoneyRecord.transfer_group_id == rec.transfer_group_id,
                MoneyRecord.is_voided.is_(False),
            )
            .all()
        )
        return all(not record_locked_by_settlement(db, s) for s in siblings)
    return not record_locked_by_settlement(db, rec)


def settlement_kind_for_adjustment(track: AdjustmentTrack) -> PayoutKind:
    if track == AdjustmentTrack.spendings:
        return PayoutKind.expense_payout
    return PayoutKind.income_handover


def adjustment_locked_by_settlement(db: Session, adj: BalanceAdjustment) -> bool:
    """True if a non-voided payout cutoff already includes this adjustment."""
    if adj.is_voided:
        return False
    kind = settlement_kind_for_adjustment(adj.track)
    cut = last_payout(db, adj.organization_id, adj.user_id, kind)
    if cut is None:
        return False
    eff = adj.occurred_at or adj.created_at
    if eff is None:
        return False
    return eff <= cut.created_at


def can_void_adjustment(db: Session, adj: BalanceAdjustment) -> bool:
    if adj.is_voided:
        return False
    return not adjustment_locked_by_settlement(db, adj)


def _sum_adjustments(db: Session, org_id: int, user_id: int, track: AdjustmentTrack, since) -> float:
    q = db.query(func.coalesce(func.sum(BalanceAdjustment.amount), 0.0)).filter(
        BalanceAdjustment.organization_id == org_id,
        BalanceAdjustment.user_id == user_id,
        BalanceAdjustment.track == track,
        BalanceAdjustment.is_voided.is_(False),
    )
    if since is not None:
        q = q.filter(_adj_at > since)
    return float(q.scalar() or 0)


def user_balance(db: Session, user: User) -> dict:
    org_id = user.organization_id
    hand_cut = last_payout(db, org_id, user.id, PayoutKind.income_handover)
    pay_cut = last_payout(db, org_id, user.id, PayoutKind.expense_payout)
    since_hand = hand_cut.created_at if hand_cut else None
    since_pay = pay_cut.created_at if pay_cut else None

    def sum_income_cash() -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == org_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.kind == RecordKind.income,
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.is_voided.is_(False),
            MoneyRecord.payment_method == "cash",
        )
        if since_hand is not None:
            q = q.filter(_effective_at > since_hand)
        return float(q.scalar() or 0)

    def sum_out(sources: list[str], since) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == org_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
            MoneyRecord.status == RecordStatus.approved,
            MoneyRecord.is_voided.is_(False),
            MoneyRecord.payment_source.in_(sources),
        )
        if since is not None:
            q = q.filter(_effective_at > since)
        return float(q.scalar() or 0)

    income_cash = sum_income_cash()
    from_cash = sum_out(["cash_on_hand", ""], since_hand)
    spendings_raw = sum_out(["my_pocket"], since_pay)

    carry_cash = float(hand_cut.balance_after or 0) if hand_cut is not None else 0.0
    carry_spend = float(pay_cut.balance_after or 0) if pay_cut is not None else 0.0
    overpay = float(pay_cut.overpayment or 0) if pay_cut is not None else 0.0
    adj_cash = _sum_adjustments(db, org_id, user.id, AdjustmentTrack.cash_on_hand, since_hand)
    adj_spend = _sum_adjustments(db, org_id, user.id, AdjustmentTrack.spendings, since_pay)

    spendings = max(0.0, spendings_raw + carry_spend - overpay + adj_spend)
    cash_on_hand = income_cash - from_cash + carry_cash + adj_cash

    pending = (
        db.query(func.count(MoneyRecord.id))
        .filter(
            MoneyRecord.organization_id == org_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.status == RecordStatus.pending,
            MoneyRecord.is_voided.is_(False),
        )
        .scalar()
        or 0
    )
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "cash_on_hand": cash_on_hand,
        "spendings": spendings,
        "owed_to_employee": spendings,
        "pending_count": int(pending),
    }
