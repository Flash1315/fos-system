"""Opening balances and non-operating corrections."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import AdjustmentTrack, BalanceAdjustment, User, UserRole
from app.routers.records import _utcnow, _validate_occurred_at
from app.services.balances import adjustment_void_blocked_reason, can_void_adjustment, user_balance

router = APIRouter(prefix="/adjustments", tags=["adjustments"])


def _require_note(value: str) -> str:
    note = (value or "").strip()
    if len(note) < 2:
        raise ValueError("Note is required (min 2 characters)")
    return note


class AdjustmentIn(BaseModel):
    user_id: int
    track: AdjustmentTrack
    amount: float = Field(..., description="Signed: + increases track, - decreases")
    note: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime | None = None

    @field_validator("note")
    @classmethod
    def note_trimmed(cls, v: str) -> str:
        return _require_note(v)


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

    @field_validator("note")
    @classmethod
    def note_trimmed(cls, v: str) -> str:
        return _require_note(v)


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
    voided: bool | None = None,
    user_id: int | None = None,
    track: AdjustmentTrack | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    q = db.query(BalanceAdjustment).filter(
        BalanceAdjustment.organization_id == user.organization_id
    )
    if voided is True:
        q = q.filter(BalanceAdjustment.is_voided.is_(True))
    elif voided is False:
        q = q.filter(BalanceAdjustment.is_voided.is_(False))
    if user_id is not None:
        q = q.filter(BalanceAdjustment.user_id == user_id)
    if track is not None:
        q = q.filter(BalanceAdjustment.track == track)
    rows = (
        q.order_by(BalanceAdjustment.created_at.desc()).offset(offset).limit(limit).all()
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import lookup_idem, normalize_idem_key, store_idem
    from app.services.money import round_money

    key = normalize_idem_key(idempotency_key)
    if key:
        hit = lookup_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="adjustments.create",
            key=key,
        )
        if hit:
            existing = db.get(BalanceAdjustment, hit.resource_id)
            if existing and existing.organization_id == manager.organization_id:
                u = db.get(User, existing.user_id)
                return _out(existing, u.full_name if u else "", db)

    amount = round_money(body.amount)
    if abs(amount) < 1e-9:
        raise HTTPException(400, "Amount cannot be zero")
    target = db.get(User, body.user_id)
    if not target or target.organization_id != manager.organization_id or not target.is_active:
        raise HTTPException(404, "User not found")
    bal = user_balance(db, target)
    current = (
        float(bal.get("cash_on_hand") or 0)
        if body.track == AdjustmentTrack.cash_on_hand
        else float(bal.get("spendings") or 0)
    )
    if current + amount < -1e-6:
        raise HTTPException(
            400,
            f"Adjustment would make {body.track.value} negative "
            f"(current {current}, delta {amount})",
        )
    occurred_at = _validate_occurred_at(body.occurred_at) or _utcnow()
    row = BalanceAdjustment(
        organization_id=manager.organization_id,
        user_id=target.id,
        track=body.track,
        amount=amount,
        note=body.note.strip(),
        occurred_at=occurred_at,
        created_by=manager.id,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    if key:
        store_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="adjustments.create",
            key=key,
            resource_id=row.id,
        )
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
        u = db.get(User, row.user_id)
        return _out(row, u.full_name if u else "", db)
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
