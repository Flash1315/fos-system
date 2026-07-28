"""Opening balances and non-operating corrections."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import AdjustmentTrack, BalanceAdjustment, User, UserRole
from app.routers.records import _utcnow
from app.services.balances import adjustment_void_blocked_reason, can_void_adjustment

router = APIRouter(prefix="/adjustments", tags=["adjustments"])


class AdjustmentIn(BaseModel):
    user_id: int
    track: AdjustmentTrack
    amount: float = Field(..., description="Signed: + increases track, - decreases")
    note: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime | None = None


class AdjustmentOut(BaseModel):
    id: int
    user_id: int
    user_name: str = ""
    track: AdjustmentTrack
    amount: float
    note: str
    occurred_at: datetime
    created_by: int
    created_at: datetime
    is_voided: bool = False
    can_void: bool = False
    void_blocked_reason: str | None = None

    model_config = {"from_attributes": True}


class VoidIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


def _out(row: BalanceAdjustment, user_name: str, db: Session | None = None) -> AdjustmentOut:
    return AdjustmentOut(
        id=row.id,
        user_id=row.user_id,
        user_name=user_name,
        track=row.track,
        amount=row.amount,
        note=row.note,
        occurred_at=row.occurred_at,
        created_by=row.created_by,
        created_at=row.created_at,
        is_voided=bool(row.is_voided),
        can_void=can_void_adjustment(db, row) if db is not None else False,
        void_blocked_reason=adjustment_void_blocked_reason(db, row) if db is not None else None,
    )


@router.get("", response_model=list[AdjustmentOut])
def list_adjustments(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rows = (
        db.query(BalanceAdjustment)
        .filter(BalanceAdjustment.organization_id == user.organization_id)
        .order_by(BalanceAdjustment.created_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for r in rows:
        u = db.get(User, r.user_id)
        out.append(_out(r, u.full_name if u else "", db))
    return out


@router.post("", response_model=AdjustmentOut)
def create_adjustment(
    body: AdjustmentIn,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    if abs(float(body.amount)) < 1e-9:
        raise HTTPException(400, "Amount cannot be zero")
    target = db.get(User, body.user_id)
    if not target or target.organization_id != manager.organization_id or not target.is_active:
        raise HTTPException(404, "User not found")
    row = BalanceAdjustment(
        organization_id=manager.organization_id,
        user_id=target.id,
        track=body.track,
        amount=float(body.amount),
        note=body.note.strip(),
        occurred_at=body.occurred_at or _utcnow(),
        created_by=manager.id,
        created_at=_utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row, target.full_name, db)


@router.post("/{adjustment_id}/void", response_model=AdjustmentOut)
def void_adjustment(
    adjustment_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    row = db.get(BalanceAdjustment, adjustment_id)
    if not row or row.organization_id != manager.organization_id:
        raise HTTPException(404, "Adjustment not found")
    if row.is_voided:
        raise HTTPException(400, "Already voided")
    if not can_void_adjustment(db, row):
        raise HTTPException(
            400,
            "Adjustment is locked by a later settlement. Void that payout first.",
        )
    row.is_voided = True
    row.voided_at = _utcnow()
    row.voided_by = manager.id
    row.note = (row.note + f"\n[voided] {body.note}").strip()
    db.commit()
    db.refresh(row)
    u = db.get(User, row.user_id)
    return _out(row, u.full_name if u else "", db)
