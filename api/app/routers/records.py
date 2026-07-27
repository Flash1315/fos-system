from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User, UserRole
from app.schemas import BalanceOut, DecideIn, RecordCreate, RecordOut

router = APIRouter(prefix="/records", tags=["records"])


@router.post("", response_model=RecordOut)
def create_record(
    body: RecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    org = db.get(Organization, user.organization_id)
    rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=user.id,
        kind=body.kind,
        status=RecordStatus.pending,
        amount=body.amount,
        currency=org.currency if org else "IDR",
        category=body.category,
        comment=body.comment,
        photo_url=body.photo_url,
        liters=body.liters,
        odometer=body.odometer,
        client_name=body.client_name,
        payment_method=body.payment_method,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return RecordOut.model_validate(rec)


@router.get("/mine", response_model=list[RecordOut])
def my_records(
    kind: RecordKind | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(MoneyRecord).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.created_by == user.id,
    )
    if kind:
        q = q.filter(MoneyRecord.kind == kind)
    rows = q.order_by(MoneyRecord.created_at.desc()).limit(100).all()
    return [RecordOut.model_validate(r) for r in rows]


@router.get("/pending", response_model=list[RecordOut])
def pending_records(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rows = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.organization_id == user.organization_id,
            MoneyRecord.status == RecordStatus.pending,
        )
        .order_by(MoneyRecord.created_at.asc())
        .limit(100)
        .all()
    )
    return [RecordOut.model_validate(r) for r in rows]


@router.post("/{record_id}/decide", response_model=RecordOut)
def decide_record(
    record_id: int,
    body: DecideIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rec = db.get(MoneyRecord, record_id)
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if rec.status != RecordStatus.pending:
        raise HTTPException(400, "Already decided")
    rec.status = RecordStatus.approved if body.approve else RecordStatus.rejected
    rec.decided_at = datetime.utcnow()
    rec.decided_by = user.id
    if body.note:
        rec.comment = (rec.comment + f"\n[review] {body.note}").strip()
    db.commit()
    db.refresh(rec)
    return RecordOut.model_validate(rec)


@router.get("/balance/me", response_model=BalanceOut)
def my_balance(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Simple cash-on-hand: approved income(cash) - approved expenses - approved fuel."""
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"

    def sum_kind(kind: RecordKind, payment: str | None = None) -> float:
        q = db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0)).filter(
            MoneyRecord.organization_id == user.organization_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.kind == kind,
            MoneyRecord.status == RecordStatus.approved,
        )
        if payment is not None:
            q = q.filter(MoneyRecord.payment_method == payment)
        return float(q.scalar() or 0)

    income_cash = sum_kind(RecordKind.income, "cash")
    expenses = sum_kind(RecordKind.expense)
    fuel = sum_kind(RecordKind.fuel)
    pending = (
        db.query(func.count(MoneyRecord.id))
        .filter(
            MoneyRecord.organization_id == user.organization_id,
            MoneyRecord.created_by == user.id,
            MoneyRecord.status == RecordStatus.pending,
        )
        .scalar()
        or 0
    )
    return BalanceOut(
        cash_on_hand=income_cash - expenses - fuel,
        currency=currency,
        pending_count=int(pending),
    )
