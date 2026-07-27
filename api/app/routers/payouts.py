from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
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
from app.services.balances import user_balance

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
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("", response_model=PayoutOut)
def create_payout(
    body: PayoutCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    target = db.get(User, body.user_id)
    if not target or target.organization_id != manager.organization_id:
        raise HTTPException(404, "User not found")
    if not target.is_active:
        raise HTTPException(400, "User inactive")
    org = db.get(Organization, manager.organization_id)
    overpayment = float(body.overpayment or 0)
    if body.kind == PayoutKind.expense_payout and overpayment <= 0:
        # Auto: paying more than current spendings → carry overpayment into next cycle
        owed = float(user_balance(db, target).get("spendings") or 0)
        if body.amount > owed:
            overpayment = body.amount - owed
    row = Payout(
        organization_id=manager.organization_id,
        user_id=target.id,
        kind=body.kind,
        amount=body.amount,
        currency=org.currency if org else "IDR",
        payment_method=body.payment_method or "cash",
        note=body.note,
        overpayment=overpayment,
        created_by=manager.id,
        created_at=_utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    print(
        f"payout org={manager.organization_id} kind={body.kind.value} "
        f"user={target.id} amount={body.amount} overpay={overpayment}"
    )
    return PayoutOut(
        id=row.id,
        user_id=row.user_id,
        user_name=target.full_name,
        kind=row.kind,
        amount=row.amount,
        currency=row.currency,
        payment_method=row.payment_method,
        note=row.note,
        overpayment=row.overpayment,
        created_by=row.created_by,
        created_at=row.created_at,
    )


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
    return [
        PayoutOut(
            id=r.id,
            user_id=r.user_id,
            user_name=user.full_name,
            kind=r.kind,
            amount=r.amount,
            currency=r.currency,
            payment_method=r.payment_method,
            note=r.note,
            overpayment=float(r.overpayment or 0),
            created_by=r.created_by,
            created_at=r.created_at,
        )
        for r in rows
    ]


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
        out.append(
            PayoutOut(
                id=r.id,
                user_id=r.user_id,
                user_name=u.full_name if u else "",
                kind=r.kind,
                amount=r.amount,
                currency=r.currency,
                payment_method=r.payment_method,
                note=r.note,
                overpayment=float(r.overpayment or 0),
                created_by=r.created_by,
                created_at=r.created_at,
            )
        )
    return out


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

    model_config = {"from_attributes": True}


@router.post("/requests", response_model=SettlementRequestOut)
def request_settlement(
    body: SettlementRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
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
    return SettlementRequestOut(
        id=row.id,
        user_id=row.user_id,
        user_name=user.full_name,
        kind=row.kind,
        amount=row.amount,
        note=row.note,
        status=row.status,
        created_at=row.created_at,
    )


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
        out.append(
            SettlementRequestOut(
                id=r.id,
                user_id=r.user_id,
                user_name=u.full_name if u else "",
                kind=r.kind,
                amount=r.amount,
                note=r.note,
                status=r.status,
                created_at=r.created_at,
            )
        )
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
    payout = create_payout(
        PayoutCreate(
            user_id=req.user_id,
            kind=req.kind,
            amount=req.amount,
            payment_method="cash",
            note=req.note or f"From request #{req.id}",
        ),
        db=db,
        manager=manager,
    )
    req.status = SettlementRequestStatus.approved
    req.decided_at = _utcnow()
    req.decided_by = manager.id
    db.commit()
    return payout


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
    return SettlementRequestOut(
        id=req.id,
        user_id=req.user_id,
        user_name=u.full_name if u else "",
        kind=req.kind,
        amount=req.amount,
        note=req.note,
        status=req.status,
        created_at=req.created_at,
    )
