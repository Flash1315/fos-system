"""Per-user balance helpers — RJ get_all_balances style, multi-tenant SQL."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AdjustmentTrack,
    BalanceAdjustment,
    MoneyRecord,
    Organization,
    Payout,
    PayoutKind,
    RecordKind,
    RecordStatus,
    SettlementRequest,
    SettlementRequestStatus,
    User,
)

# Prefer occurred_at when present (late entries), else created_at
_effective_at = func.coalesce(MoneyRecord.occurred_at, MoneyRecord.created_at)
_adj_at = func.coalesce(BalanceAdjustment.occurred_at, BalanceAdjustment.created_at)
_UNSET = object()


def last_payout(db: Session, org_id: int, user_id: int, kind: PayoutKind) -> Payout | None:
    return (
        db.query(Payout)
        .filter(
            Payout.organization_id == org_id,
            Payout.user_id == user_id,
            Payout.kind == kind,
            Payout.is_voided.is_(False),
        )
        .order_by(Payout.created_at.desc(), Payout.id.desc())
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
    return record_in_closed_cycle(db, rec)


def record_settlement_cutoff_at(db: Session, rec: MoneyRecord):
    """Latest non-voided payout cutoff that would apply to this record's track."""
    kind = settlement_kind_for_record(rec)
    if kind is None:
        return None
    cut = last_payout(db, rec.organization_id, rec.created_by, kind)
    return cut.created_at if cut else None


def record_in_closed_cycle(db: Session, rec: MoneyRecord) -> bool:
    """True if the record's effective date falls at/before the track's last payout.

    Applies to pending and approved records so UI can warn before approve.
    """
    cut = record_settlement_cutoff_at(db, rec)
    if cut is None:
        return False
    eff = record_effective_at(rec)
    if eff is None:
        return False
    return eff <= cut


def void_record_balance_deltas(rec: MoneyRecord) -> tuple[float, float]:
    """Cash/spendings deltas when voiding an approved record (positive = balance up)."""
    amt = float(rec.amount or 0)
    if rec.kind == RecordKind.income and (rec.payment_method or "") == "cash":
        return (-amt, 0.0)
    if rec.kind in (RecordKind.expense, RecordKind.fuel):
        source = rec.payment_source or "cash_on_hand"
        if source == "my_pocket":
            return (0.0, -amt)
        return (amt, 0.0)
    return (0.0, 0.0)


def assert_void_records_keep_non_negative(
    db: Session, targets: list[MoneyRecord]
) -> None:
    """Reject void if any teammate's cash_on_hand or spendings would go negative."""
    from fastapi import HTTPException

    by_user: dict[int, list[MoneyRecord]] = {}
    for rec in targets:
        by_user.setdefault(rec.created_by, []).append(rec)
    for uid, rows in by_user.items():
        user = db.get(User, uid)
        if not user:
            continue
        bal = user_balance(db, user)
        cash = float(bal.get("cash_on_hand") or 0)
        spend = float(bal.get("spendings") or 0)
        d_cash = 0.0
        d_spend = 0.0
        for rec in rows:
            dc, ds = void_record_balance_deltas(rec)
            d_cash += dc
            d_spend += ds
        if cash + d_cash < -1e-6:
            raise HTTPException(
                400,
                f"Voiding would make cash_on_hand negative for {user.full_name} "
                f"(current {cash}, delta {d_cash})",
            )
        if spend + d_spend < -1e-6:
            raise HTTPException(
                400,
                f"Voiding would make spendings negative for {user.full_name} "
                f"(current {spend}, delta {d_spend})",
            )


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


def void_blocked_reason(db: Session, rec: MoneyRecord) -> str | None:
    """Human-readable why an approved record cannot be voided right now."""
    if rec.status != RecordStatus.approved or rec.is_voided:
        return None
    if can_void_record(db, rec):
        return None
    cut = record_settlement_cutoff_at(db, rec)
    stamp = cut.isoformat(timespec="seconds") if cut is not None else None
    if rec.transfer_group_id:
        base = "Locked by a settlement on a linked transfer leg. Void the latest payout first."
    else:
        base = "Locked by a settlement. Void the latest payout first."
    if stamp:
        return f"{base} Cutoff {stamp}."
    return base


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


def adjustment_void_blocked_reason(db: Session, adj: BalanceAdjustment) -> str | None:
    if adj.is_voided or can_void_adjustment(db, adj):
        return None
    return "Locked by a later settlement. Void that payout first."


def pending_reserved(
    db: Session, user_id: int, org_id: int, kind: PayoutKind, exclude_id: int | None = None
) -> float:
    """Sum of pending settlement-request amounts reserved against a track."""
    q = db.query(func.coalesce(func.sum(SettlementRequest.amount), 0.0)).filter(
        SettlementRequest.organization_id == org_id,
        SettlementRequest.user_id == user_id,
        SettlementRequest.kind == kind,
        SettlementRequest.status == SettlementRequestStatus.pending,
    )
    if exclude_id is not None:
        q = q.filter(SettlementRequest.id != exclude_id)
    return float(q.scalar() or 0)


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


def _user_balance(
    db: Session,
    user: User,
    *,
    hand_cut=_UNSET,
    pay_cut=_UNSET,
    reserved_values: tuple[float, float] | None = None,
    currency: str | None = None,
) -> dict:
    org_id = user.organization_id
    if hand_cut is _UNSET:
        hand_cut = last_payout(db, org_id, user.id, PayoutKind.income_handover)
    if pay_cut is _UNSET:
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

    spendings_net = spendings_raw + carry_spend - overpay + adj_spend
    spendings = max(0.0, spendings_net)
    remaining_overpayment_credit = max(0.0, -spendings_net)
    cash_on_hand = income_cash - from_cash + carry_cash + adj_cash

    if reserved_values is None:
        reserved_spendings = pending_reserved(
            db, user.id, org_id, PayoutKind.expense_payout
        )
        reserved_cash = pending_reserved(
            db, user.id, org_id, PayoutKind.income_handover
        )
    else:
        reserved_spendings, reserved_cash = reserved_values
    available_spendings = max(0.0, spendings - reserved_spendings)
    available_cash = max(0.0, cash_on_hand - reserved_cash)

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
    if currency is None:
        org = db.get(Organization, org_id)
        currency = org.currency if org else "IDR"
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "cash_on_hand": cash_on_hand,
        "spendings": spendings,
        "owed_to_employee": spendings,
        "currency": currency,
        "pending_count": int(pending),
        "last_expense_payout_at": since_pay.isoformat() if since_pay else None,
        "last_income_handover_at": since_hand.isoformat() if since_hand else None,
        "reserved_spendings": reserved_spendings,
        "reserved_cash": reserved_cash,
        "available_spendings": available_spendings,
        "available_cash": available_cash,
        "remaining_overpayment_credit": remaining_overpayment_credit,
    }


def user_balance(db: Session, user: User) -> dict:
    """Calculate one user's balance with the single-user query path."""
    return _user_balance(db, user)


def _latest_payouts_for_kind(
    db: Session,
    *,
    org_id: int,
    user_ids: list[int],
    kind: PayoutKind,
) -> dict[int, object]:
    """Fetch one latest non-voided payout per user in one query."""
    rank = func.row_number().over(
        partition_by=Payout.user_id,
        order_by=(Payout.created_at.desc(), Payout.id.desc()),
    )
    ranked = (
        db.query(
            Payout.user_id.label("user_id"),
            Payout.created_at.label("created_at"),
            Payout.balance_after.label("balance_after"),
            Payout.overpayment.label("overpayment"),
            rank.label("row_number"),
        )
        .filter(
            Payout.organization_id == org_id,
            Payout.user_id.in_(user_ids),
            Payout.kind == kind,
            Payout.is_voided.is_(False),
        )
        .subquery()
    )
    rows = (
        db.query(
            ranked.c.user_id,
            ranked.c.created_at,
            ranked.c.balance_after,
            ranked.c.overpayment,
        )
        .filter(ranked.c.row_number == 1)
        .all()
    )
    return {int(row.user_id): row for row in rows}


def team_balances(db: Session, members: list[User]) -> list[dict]:
    """Calculate team balances with payout cutoffs and reservations batched."""
    if not members:
        return []
    org_id = members[0].organization_id
    if any(member.organization_id != org_id for member in members):
        raise ValueError("team_balances members must belong to one organization")
    user_ids = [member.id for member in members]

    # Deliberately one query per payout kind, regardless of team size.
    hand_cuts = _latest_payouts_for_kind(
        db,
        org_id=org_id,
        user_ids=user_ids,
        kind=PayoutKind.income_handover,
    )
    pay_cuts = _latest_payouts_for_kind(
        db,
        org_id=org_id,
        user_ids=user_ids,
        kind=PayoutKind.expense_payout,
    )
    reserved_rows = (
        db.query(
            SettlementRequest.user_id,
            SettlementRequest.kind,
            func.coalesce(func.sum(SettlementRequest.amount), 0.0),
        )
        .filter(
            SettlementRequest.organization_id == org_id,
            SettlementRequest.user_id.in_(user_ids),
            SettlementRequest.status == SettlementRequestStatus.pending,
        )
        .group_by(SettlementRequest.user_id, SettlementRequest.kind)
        .all()
    )
    reserved = {
        (
            int(user_id),
            kind if isinstance(kind, PayoutKind) else PayoutKind(kind),
        ): float(amount or 0)
        for user_id, kind, amount in reserved_rows
    }
    org = db.get(Organization, org_id)
    currency = org.currency if org else "IDR"
    return [
        _user_balance(
            db,
            member,
            hand_cut=hand_cuts.get(member.id),
            pay_cut=pay_cuts.get(member.id),
            reserved_values=(
                reserved.get((member.id, PayoutKind.expense_payout), 0.0),
                reserved.get((member.id, PayoutKind.income_handover), 0.0),
            ),
            currency=currency,
        )
        for member in members
    ]
