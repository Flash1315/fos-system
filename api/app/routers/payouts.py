from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.categories import PAYMENT_METHODS
from app.db import get_db
from app.models import (
    Organization,
    Payout,
    PayoutKind,
    SettlementRequest,
    SettlementRequestStatus,
    User,
    UserRole,
)
from app.routers.records import _utcnow
from app.services.balances import last_payout, pending_reserved, user_balance

router = APIRouter(prefix="/payouts", tags=["payouts"])


class PayoutCreate(BaseModel):
    user_id: int
    kind: PayoutKind
    amount: float = Field(gt=0)
    payment_method: str = "cash"
    note: str = ""
    overpayment: float = Field(default=0, ge=0)


class PayoutOut(BaseModel):
    id: int
    user_id: int
    user_name: str = ""
    kind: PayoutKind
    amount: float
    currency: str
    payment_method: str
    note: str
    overpayment: float = 0.0
    balance_after: float = 0.0
    is_voided: bool = False
    voided_at: datetime | None = None
    void_note: str = ""
    can_void: bool = False
    void_blocked_reason: str | None = None
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class VoidIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class SettlementRequestIn(BaseModel):
    kind: PayoutKind
    amount: float = Field(gt=0)
    note: str = ""


class SettlementRequestOut(BaseModel):
    id: int
    user_id: int
    user_name: str = ""
    kind: PayoutKind
    amount: float
    note: str
    status: SettlementRequestStatus
    created_at: datetime
    settled_amount: float | None = None
    payout_id: int | None = None

    model_config = {"from_attributes": True}


def _can_void_payout(db: Session, row: Payout) -> bool:
    if row.is_voided:
        return False
    latest = last_payout(db, row.organization_id, row.user_id, row.kind)
    return latest is not None and latest.id == row.id


def _payout_void_blocked_reason(db: Session, row: Payout) -> str | None:
    if row.is_voided or _can_void_payout(db, row):
        return None
    return "Only the latest settlement of this kind can be voided."


def _payout_out(db: Session, row: Payout, user_name: str) -> PayoutOut:
    return PayoutOut(
        id=row.id,
        user_id=row.user_id,
        user_name=user_name,
        kind=row.kind,
        amount=row.amount,
        currency=row.currency,
        payment_method=row.payment_method,
        note=row.note,
        overpayment=float(row.overpayment or 0),
        balance_after=float(row.balance_after or 0),
        is_voided=bool(row.is_voided),
        voided_at=row.voided_at,
        void_note=row.void_note or "",
        can_void=_can_void_payout(db, row),
        void_blocked_reason=_payout_void_blocked_reason(db, row),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _request_out(row: SettlementRequest, user_name: str) -> SettlementRequestOut:
    return SettlementRequestOut(
        id=row.id,
        user_id=row.user_id,
        user_name=user_name,
        kind=row.kind,
        amount=row.amount,
        note=row.note,
        status=row.status,
        created_at=row.created_at,
        settled_amount=row.settled_amount,
        payout_id=row.payout_id,
    )


def _create_payout_row(
    body: PayoutCreate,
    db: Session,
    manager: User,
) -> tuple[Payout, User]:
    """Build a payout row and flush (no commit) so callers can batch atomically."""
    target = db.get(User, body.user_id)
    if not target or target.organization_id != manager.organization_id:
        raise HTTPException(404, "User not found")
    if not target.is_active:
        raise HTTPException(400, "User inactive")
    org = db.get(Organization, manager.organization_id)
    bal = user_balance(db, target)
    method = (body.payment_method or "cash").strip().lower()
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, f"payment_method must be one of {PAYMENT_METHODS}")
    overpayment = float(body.overpayment or 0)
    balance_after = 0.0
    if body.kind == PayoutKind.expense_payout:
        owed = float(bal.get("spendings") or 0)
        if body.amount > owed + 1e-6:
            if overpayment <= 0:
                overpayment = body.amount - owed
            balance_after = 0.0
        else:
            overpayment = 0.0
            balance_after = max(0.0, owed - body.amount)
    elif body.kind == PayoutKind.income_handover:
        held = float(bal.get("cash_on_hand") or 0)
        if body.amount > held + 1e-6:
            raise HTTPException(
                400,
                f"Insufficient cash on hand ({held}). Cannot take {body.amount}.",
            )
        balance_after = max(0.0, held - body.amount)
        overpayment = 0.0
    row = Payout(
        organization_id=manager.organization_id,
        user_id=target.id,
        kind=body.kind,
        amount=body.amount,
        currency=org.currency if org else "IDR",
        payment_method=method,
        note=body.note,
        overpayment=overpayment,
        balance_after=balance_after,
        created_by=manager.id,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    print(
        f"payout org={manager.organization_id} kind={body.kind.value} "
        f"user={target.id} amount={body.amount} overpay={overpayment} after={balance_after}"
    )
    return row, target


@router.post("", response_model=PayoutOut)
def create_payout(
    body: PayoutCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    row, target = _create_payout_row(body, db, manager)
    db.commit()
    db.refresh(row)
    return _payout_out(db, row, target.full_name)


@router.get("/mine", response_model=list[PayoutOut])
def my_payouts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(Payout)
        .filter(Payout.organization_id == user.organization_id, Payout.user_id == user.id)
        .order_by(Payout.created_at.desc())
        .limit(50)
        .all()
    )
    return [_payout_out(db, r, user.full_name) for r in rows]


@router.get("/org", response_model=list[PayoutOut])
def org_payouts(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rows = (
        db.query(Payout)
        .filter(Payout.organization_id == user.organization_id)
        .order_by(Payout.created_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for r in rows:
        u = db.get(User, r.user_id)
        out.append(_payout_out(db, r, u.full_name if u else ""))
    return out


@router.post("/{payout_id}/void", response_model=PayoutOut)
def void_payout(
    payout_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    row = db.get(Payout, payout_id)
    if not row or row.organization_id != manager.organization_id:
        raise HTTPException(404, "Payout not found")
    if row.is_voided:
        raise HTTPException(400, "Already voided")
    if not _can_void_payout(db, row):
        raise HTTPException(
            400,
            "Only the latest settlement of this type for the teammate can be voided",
        )
    row.is_voided = True
    row.voided_at = _utcnow()
    row.voided_by = manager.id
    row.void_note = body.note
    linked = (
        db.query(SettlementRequest)
        .filter(
            SettlementRequest.organization_id == manager.organization_id,
            SettlementRequest.payout_id == row.id,
        )
        .first()
    )
    if linked is not None:
        linked.status = SettlementRequestStatus.pending
        linked.decided_at = None
        linked.decided_by = None
        linked.settled_amount = None
        linked.payout_id = None
        linked.note = ((linked.note or "") + f"\n[reopened after payout void] {body.note}").strip()
    db.commit()
    db.refresh(row)
    target = db.get(User, row.user_id)
    return _payout_out(db, row, target.full_name if target else "")


@router.post("/batch-spendings", response_model=list[PayoutOut])
def batch_pay_all_spendings(
    payment_method: str = "cash",
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    """Create expense_payout for every teammate with spendings > 0 (one commit)."""
    members = (
        db.query(User)
        .filter(User.organization_id == manager.organization_id, User.is_active.is_(True))
        .all()
    )
    built: list[tuple[Payout, User]] = []
    for m in members:
        bal = user_balance(db, m)
        owed = float(bal.get("spendings") or 0)
        if owed <= 0:
            continue
        built.append(
            _create_payout_row(
                PayoutCreate(
                    user_id=m.id,
                    kind=PayoutKind.expense_payout,
                    amount=owed,
                    payment_method=payment_method,
                    note="batch pay all spendings",
                ),
                db=db,
                manager=manager,
            )
        )
    db.commit()
    out = []
    for row, target in built:
        db.refresh(row)
        out.append(_payout_out(db, row, target.full_name))
    return out


@router.post("/batch-cash", response_model=list[PayoutOut])
def batch_take_all_cash(
    payment_method: str = "cash",
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    """Create income_handover for every teammate with cash_on_hand > 0 (one commit)."""
    members = (
        db.query(User)
        .filter(User.organization_id == manager.organization_id, User.is_active.is_(True))
        .all()
    )
    built: list[tuple[Payout, User]] = []
    for m in members:
        bal = user_balance(db, m)
        held = float(bal.get("cash_on_hand") or 0)
        if held <= 0:
            continue
        built.append(
            _create_payout_row(
                PayoutCreate(
                    user_id=m.id,
                    kind=PayoutKind.income_handover,
                    amount=held,
                    payment_method=payment_method,
                    note="batch take all cash on hand",
                ),
                db=db,
                manager=manager,
            )
        )
    db.commit()
    out = []
    for row, target in built:
        db.refresh(row)
        out.append(_payout_out(db, row, target.full_name))
    return out


@router.get("/requests/mine", response_model=list[SettlementRequestOut])
def my_settlement_requests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(SettlementRequest)
        .filter(
            SettlementRequest.organization_id == user.organization_id,
            SettlementRequest.user_id == user.id,
        )
        .order_by(SettlementRequest.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        _request_out(r, user.full_name)
        for r in rows
    ]


@router.post("/requests", response_model=SettlementRequestOut)
def request_settlement(
    body: SettlementRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bal = user_balance(db, user)
    if body.kind == PayoutKind.expense_payout:
        available = float(bal.get("spendings") or 0)
        label = "spendings owed"
    else:
        available = float(bal.get("cash_on_hand") or 0)
        label = "cash on hand"
    reserved = pending_reserved(db, user.id, user.organization_id, body.kind)
    open_to_request = max(0.0, available - reserved)
    if body.amount > open_to_request + 1e-6:
        raise HTTPException(
            400,
            f"Request exceeds available {label} ({open_to_request}; "
            f"balance {available}, reserved by pending {reserved}).",
        )
    row = SettlementRequest(
        organization_id=user.organization_id,
        user_id=user.id,
        kind=body.kind,
        amount=body.amount,
        note=body.note,
        status=SettlementRequestStatus.pending,
        created_at=_utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _request_out(row, user.full_name)


@router.get("/requests", response_model=list[SettlementRequestOut])
def list_settlement_requests(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rows = (
        db.query(SettlementRequest)
        .filter(
            SettlementRequest.organization_id == user.organization_id,
            SettlementRequest.status == SettlementRequestStatus.pending,
        )
        .order_by(SettlementRequest.created_at.asc())
        .limit(100)
        .all()
    )
    out = []
    for r in rows:
        u = db.get(User, r.user_id)
        out.append(_request_out(r, u.full_name if u else ""))
    return out


@router.post("/requests/{request_id}/approve", response_model=PayoutOut)
def approve_settlement_request(
    request_id: int,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    req = db.get(SettlementRequest, request_id)
    if not req or req.organization_id != manager.organization_id:
        raise HTTPException(404, "Request not found")
    if req.status != SettlementRequestStatus.pending:
        raise HTTPException(400, "Request already decided")
    target = db.get(User, req.user_id)
    if not target:
        raise HTTPException(404, "User not found")
    bal = user_balance(db, target)
    available = (
        float(bal.get("spendings") or 0)
        if req.kind == PayoutKind.expense_payout
        else float(bal.get("cash_on_hand") or 0)
    )
    if float(req.amount) > available + 1e-6:
        raise HTTPException(
            400,
            f"Balance is only {available}; cancel or reduce other activity, then retry "
            f"(request is {req.amount}).",
        )
    amount = float(req.amount)
    row, target = _create_payout_row(
        PayoutCreate(
            user_id=req.user_id,
            kind=req.kind,
            amount=amount,
            payment_method="cash",
            note=req.note or f"From request #{req.id}",
        ),
        db=db,
        manager=manager,
    )
    req.status = SettlementRequestStatus.approved
    req.decided_at = _utcnow()
    req.decided_by = manager.id
    req.settled_amount = amount
    req.payout_id = row.id
    db.commit()
    db.refresh(row)
    return _payout_out(db, row, target.full_name)


@router.post("/requests/{request_id}/cancel", response_model=SettlementRequestOut)
def cancel_settlement_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    req = db.get(SettlementRequest, request_id)
    if not req or req.organization_id != user.organization_id:
        raise HTTPException(404, "Request not found")
    is_manager = user.role in (UserRole.owner, UserRole.manager)
    if req.user_id != user.id and not is_manager:
        raise HTTPException(403, "Insufficient role")
    if req.status != SettlementRequestStatus.pending:
        raise HTTPException(400, "Request already decided")
    req.status = SettlementRequestStatus.cancelled
    req.decided_at = _utcnow()
    req.decided_by = user.id
    db.commit()
    db.refresh(req)
    u = db.get(User, req.user_id)
    return _request_out(req, u.full_name if u else "")
