from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.categories import PAYMENT_SOURCES, PURPOSES, categories_for
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User, UserRole
from app.schemas import BalanceOut, CategoriesOut, DecideIn, RecordCreate, RecordOut

router = APIRouter(prefix="/records", tags=["records"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_out(db: Session, rec: MoneyRecord) -> RecordOut:
    creator = db.get(User, rec.created_by)
    data = RecordOut.model_validate(rec)
    return data.model_copy(update={"created_by_name": creator.full_name if creator else ""})


@router.get("/categories", response_model=CategoriesOut)
def list_categories(
    kind: RecordKind | None = None,
    user: User = Depends(get_current_user),
):
    _ = user
    return CategoriesOut(
        categories=categories_for(kind),
        purposes=PURPOSES,
        payment_sources=PAYMENT_SOURCES,
    )


@router.post("", response_model=RecordOut)
def create_record(
    body: RecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    org = db.get(Organization, user.organization_id)
    source = body.payment_source
    if body.kind in (RecordKind.expense, RecordKind.fuel) and not source:
        source = "cash_on_hand"
    rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=user.id,
        kind=body.kind,
        status=RecordStatus.pending,
        amount=body.amount,
        currency=org.currency if org else "IDR",
        category=body.category,
        purpose=body.purpose,
        place=body.place,
        bike=body.bike,
        comment=body.comment,
        photo_url=body.photo_url,
        liters=body.liters,
        odometer=body.odometer,
        client_name=body.client_name,
        payment_method=body.payment_method,
        payment_source=source,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)


@router.get("/mine", response_model=list[RecordOut])
def my_records(
    kind: RecordKind | None = None,
    status: RecordStatus | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(MoneyRecord).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.created_by == user.id,
    )
    if kind:
        q = q.filter(MoneyRecord.kind == kind)
    if status:
        q = q.filter(MoneyRecord.status == status)
    rows = q.order_by(MoneyRecord.created_at.desc()).limit(100).all()
    return [_record_out(db, r) for r in rows]


@router.get("/org", response_model=list[RecordOut])
def org_records(
    kind: RecordKind | None = None,
    status: RecordStatus | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    q = db.query(MoneyRecord).filter(MoneyRecord.organization_id == user.organization_id)
    if kind:
        q = q.filter(MoneyRecord.kind == kind)
    if status:
        q = q.filter(MoneyRecord.status == status)
    rows = q.order_by(MoneyRecord.created_at.desc()).limit(200).all()
    return [_record_out(db, r) for r in rows]


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
    return [_record_out(db, r) for r in rows]


@router.get("/balance/me", response_model=BalanceOut)
def my_balance(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """RJ-inspired dual track (per user, approved only):
    - cash_on_hand: income(cash) − expense/fuel paid from cash_on_hand (or legacy blank)
    - spendings: expense/fuel paid from my_pocket (owed to employee)
    """
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"

    def sum_income_cash() -> float:
        return float(
            db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0))
            .filter(
                MoneyRecord.organization_id == user.organization_id,
                MoneyRecord.created_by == user.id,
                MoneyRecord.kind == RecordKind.income,
                MoneyRecord.status == RecordStatus.approved,
                MoneyRecord.payment_method == "cash",
            )
            .scalar()
            or 0
        )

    def sum_out(sources: list[str]) -> float:
        return float(
            db.query(func.coalesce(func.sum(MoneyRecord.amount), 0.0))
            .filter(
                MoneyRecord.organization_id == user.organization_id,
                MoneyRecord.created_by == user.id,
                MoneyRecord.kind.in_([RecordKind.expense, RecordKind.fuel]),
                MoneyRecord.status == RecordStatus.approved,
                MoneyRecord.payment_source.in_(sources),
            )
            .scalar()
            or 0
        )

    income_cash = sum_income_cash()
    from_cash = sum_out(["cash_on_hand", ""])
    spendings = sum_out(["my_pocket"])
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
        cash_on_hand=income_cash - from_cash,
        spendings=spendings,
        currency=currency,
        pending_count=int(pending),
    )


@router.get("/{record_id}", response_model=RecordOut)
def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rec = db.get(MoneyRecord, record_id)
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    is_manager = user.role in (UserRole.owner, UserRole.manager)
    if rec.created_by != user.id and not is_manager:
        raise HTTPException(403, "Insufficient role")
    return _record_out(db, rec)


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
    rec.decided_at = _utcnow()
    rec.decided_by = user.id
    if body.note:
        rec.comment = (rec.comment + f"\n[review] {body.note}").strip()
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)
