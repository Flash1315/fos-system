from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import Organization, Payout, PayoutKind, User, UserRole
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
