from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.categories import PAYMENT_METHODS, PAYMENT_SOURCES, PURPOSES, categories_for
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User, UserRole
from app.schemas import (
    BalanceOut,
    CategoriesOut,
    CommentIn,
    DecideBatchIn,
    DecideIn,
    RecordCreate,
    RecordOut,
    RecordUpdate,
)
from app.services.balances import user_balance

router = APIRouter(prefix="/records", tags=["records"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_payment_fields(kind: RecordKind, source: str, method: str) -> tuple[str, str]:
    source = (source or "").strip()
    method = (method or "").strip().lower()
    if kind in (RecordKind.expense, RecordKind.fuel):
        if not source:
            source = "my_pocket"
        if source not in PAYMENT_SOURCES:
            raise HTTPException(400, f"payment_source must be one of {PAYMENT_SOURCES}")
        method = ""
    elif kind == RecordKind.income:
        source = ""
        if not method:
            method = "cash"
        if method not in PAYMENT_METHODS:
            raise HTTPException(400, f"payment_method must be one of {PAYMENT_METHODS}")
    return source, method


def _record_out(db: Session, rec: MoneyRecord) -> RecordOut:
    from app.services.balances import can_void_record

    creator = db.get(User, rec.created_by)
    decider = db.get(User, rec.decided_by) if rec.decided_by else None
    data = RecordOut.model_validate(rec)
    return data.model_copy(
        update={
            "created_by_name": creator.full_name if creator else "",
            "decided_by_name": decider.full_name if decider else "",
            "can_void": can_void_record(db, rec),
        }
    )


def _assert_cash_for_approve(db: Session, rec: MoneyRecord) -> None:
    """Block approving spend from cash_on_hand when the owner lacks held cash."""
    if rec.kind not in (RecordKind.expense, RecordKind.fuel):
        return
    source = rec.payment_source or "cash_on_hand"
    if source != "cash_on_hand":
        return
    owner = db.get(User, rec.created_by)
    if not owner:
        return
    held = float(user_balance(db, owner).get("cash_on_hand") or 0)
    if float(rec.amount) > held + 1e-6:
        raise HTTPException(
            400,
            f"Insufficient cash on hand ({held}). Cannot approve {rec.amount} from cash.",
        )


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
    if body.approve_now and user.role not in (UserRole.owner, UserRole.manager):
        raise HTTPException(403, "Only managers can approve on create")
    source, method = _normalize_payment_fields(body.kind, body.payment_source, body.payment_method)
    owner_id = user.id
    body_comment = body.comment
    if body.created_for_user_id is not None:
        if user.role not in (UserRole.owner, UserRole.manager):
            raise HTTPException(403, "Only managers can create on behalf")
        target = db.get(User, body.created_for_user_id)
        if not target or target.organization_id != user.organization_id or not target.is_active:
            raise HTTPException(404, "Target user not found")
        owner_id = target.id
        stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
        note = f"[filed by {user.full_name} {stamp}]"
        body_comment = (body.comment + "\n" + note).strip() if body.comment else note
    rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=owner_id,
        kind=body.kind,
        status=RecordStatus.pending,
        amount=body.amount,
        currency=org.currency if org else "IDR",
        category=body.category,
        purpose=body.purpose,
        place=body.place,
        bike=body.bike,
        comment=body_comment,
        photo_url=body.photo_url,
        liters=body.liters,
        odometer=body.odometer,
        client_name=body.client_name,
        payment_method=method,
        payment_source=source,
        occurred_at=body.occurred_at,
    )
    db.add(rec)
    if body.approve_now:
        _assert_cash_for_approve(db, rec)
        rec.status = RecordStatus.approved
        rec.decided_by = user.id
        rec.decided_at = _utcnow()
        stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
        note = f"[auto-approved on create by {user.full_name} {stamp}]"
        rec.comment = (rec.comment + "\n" + note).strip() if rec.comment else note
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)


@router.get("/mine", response_model=list[RecordOut])
def my_records(
    kind: RecordKind | None = None,
    status: RecordStatus | None = None,
    purpose: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(MoneyRecord).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.created_by == user.id,
    )
    if kind:
        query = query.filter(MoneyRecord.kind == kind)
    if status:
        query = query.filter(MoneyRecord.status == status)
    if purpose:
        query = query.filter(MoneyRecord.purpose == purpose)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (MoneyRecord.category.ilike(like))
            | (MoneyRecord.comment.ilike(like))
            | (MoneyRecord.place.ilike(like))
            | (MoneyRecord.bike.ilike(like))
            | (MoneyRecord.client_name.ilike(like))
        )
    rows = query.order_by(MoneyRecord.created_at.desc()).limit(100).all()
    return [_record_out(db, r) for r in rows]


@router.get("/org", response_model=list[RecordOut])
def org_records(
    kind: RecordKind | None = None,
    status: RecordStatus | None = None,
    purpose: str | None = None,
    created_by: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    query = db.query(MoneyRecord).filter(MoneyRecord.organization_id == user.organization_id)
    if kind:
        query = query.filter(MoneyRecord.kind == kind)
    if status:
        query = query.filter(MoneyRecord.status == status)
    if purpose:
        query = query.filter(MoneyRecord.purpose == purpose)
    if created_by is not None:
        query = query.filter(MoneyRecord.created_by == created_by)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (MoneyRecord.category.ilike(like))
            | (MoneyRecord.comment.ilike(like))
            | (MoneyRecord.place.ilike(like))
            | (MoneyRecord.bike.ilike(like))
            | (MoneyRecord.client_name.ilike(like))
        )
    rows = query.order_by(MoneyRecord.created_at.desc()).limit(200).all()
    return [_record_out(db, r) for r in rows]


@router.get("/pending", response_model=list[RecordOut])
def pending_records(
    purpose: str | None = None,
    kind: RecordKind | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    q = db.query(MoneyRecord).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.status == RecordStatus.pending,
    )
    if purpose:
        q = q.filter(MoneyRecord.purpose == purpose)
    if kind:
        q = q.filter(MoneyRecord.kind == kind)
    rows = q.order_by(MoneyRecord.created_at.asc()).limit(100).all()
    return [_record_out(db, r) for r in rows]


@router.get("/balance/me", response_model=BalanceOut)
def my_balance(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """RJ-inspired dual track with payout cutoffs (per user, approved only)."""
    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    bal = user_balance(db, user)
    return BalanceOut(
        cash_on_hand=bal["cash_on_hand"],
        spendings=bal["spendings"],
        currency=currency,
        pending_count=bal["pending_count"],
    )


@router.get("/balance/team", response_model=list[dict])
def team_balances(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    """All active teammates' cash/spendings — RJ manager balances view."""
    members = (
        db.query(User)
        .filter(User.organization_id == user.organization_id, User.is_active.is_(True))
        .order_by(User.full_name.asc())
        .all()
    )
    return [user_balance(db, m) for m in members]



@router.post("/decide-batch", response_model=list[RecordOut])
def decide_batch(
    body: DecideBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    """Approve/reject many pending records in one call."""
    out = []
    for rid in body.ids:
        rec = db.get(MoneyRecord, rid)
        if not rec or rec.organization_id != user.organization_id:
            continue
        if rec.status != RecordStatus.pending:
            continue
        if body.approve:
            _assert_cash_for_approve(db, rec)
        rec.status = RecordStatus.approved if body.approve else RecordStatus.rejected
        rec.decided_at = _utcnow()
        rec.decided_by = user.id
        if body.note:
            rec.comment = (rec.comment + f"\n[review] {body.note}").strip()
        out.append(rec)
    db.commit()
    for rec in out:
        db.refresh(rec)
    return [_record_out(db, r) for r in out]


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


@router.patch("/{record_id}", response_model=RecordOut)
def update_pending_record(
    record_id: int,
    body: RecordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Creator or manager can edit fields while status is still pending."""
    rec = db.get(MoneyRecord, record_id)
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    is_manager = user.role in (UserRole.owner, UserRole.manager)
    if rec.created_by != user.id and not is_manager:
        raise HTTPException(403, "Insufficient role")
    if rec.status != RecordStatus.pending:
        raise HTTPException(400, "Only pending records can be edited")
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(rec, key, value)
    db.commit()
    db.refresh(rec)
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
    if body.approve:
        _assert_cash_for_approve(db, rec)
    rec.status = RecordStatus.approved if body.approve else RecordStatus.rejected
    rec.decided_at = _utcnow()
    rec.decided_by = user.id
    if body.note:
        rec.comment = (rec.comment + f"\n[review] {body.note}").strip()
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)


@router.post("/{record_id}/comment", response_model=RecordOut)
def comment_record(
    record_id: int,
    body: CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rec = db.get(MoneyRecord, record_id)
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
    rec.comment = (rec.comment + f"\n[mgr {user.full_name} {stamp}] {body.note}").strip()
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)


@router.post("/{record_id}/void", response_model=RecordOut)
def void_approved_record(
    record_id: int,
    body: CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    """Manager voids an approved record; kept for audit, excluded from balances.

    Transfer legs are voided together via transfer_group_id.
    Records already included in a settlement cutoff cannot be voided until
    that payout is voided first.
    """
    from app.services.balances import can_void_record

    rec = db.get(MoneyRecord, record_id)
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if rec.status != RecordStatus.approved:
        raise HTTPException(400, "Only approved records can be voided")
    if rec.is_voided:
        raise HTTPException(400, "Already voided")
    if not can_void_record(db, rec):
        raise HTTPException(
            400,
            "Record is locked by a settlement. Void the latest payout first.",
        )
    stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
    note = f"[voided by {user.full_name} {stamp}] {body.note}"
    now = _utcnow()
    targets = [rec]
    if rec.transfer_group_id:
        siblings = (
            db.query(MoneyRecord)
            .filter(
                MoneyRecord.organization_id == user.organization_id,
                MoneyRecord.transfer_group_id == rec.transfer_group_id,
                MoneyRecord.is_voided.is_(False),
            )
            .all()
        )
        targets = siblings or [rec]
    for row in targets:
        row.is_voided = True
        row.voided_at = now
        row.voided_by = user.id
        row.comment = (row.comment + "\n" + note).strip()
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)


@router.delete("/{record_id}", response_model=RecordOut)
def cancel_pending_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Creator (or manager) can cancel a still-pending record by rejecting it."""
    rec = db.get(MoneyRecord, record_id)
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    is_manager = user.role in (UserRole.owner, UserRole.manager)
    if rec.created_by != user.id and not is_manager:
        raise HTTPException(403, "Insufficient role")
    if rec.status != RecordStatus.pending:
        raise HTTPException(400, "Only pending records can be cancelled")
    rec.status = RecordStatus.rejected
    rec.decided_at = _utcnow()
    rec.decided_by = user.id
    rec.comment = (rec.comment + "\n[cancelled]").strip()
    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)
