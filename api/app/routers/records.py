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
    from app.services.balances import can_void_record, void_blocked_reason

    creator = db.get(User, rec.created_by)
    decider = db.get(User, rec.decided_by) if rec.decided_by else None
    data = RecordOut.model_validate(rec)
    return data.model_copy(
        update={
            "created_by_name": creator.full_name if creator else "",
            "decided_by_name": decider.full_name if decider else "",
            "can_void": can_void_record(db, rec),
            "void_blocked_reason": void_blocked_reason(db, rec),
        }
    )


def _assert_cash_for_approve(db: Session, rec: MoneyRecord) -> None:
    """Block approving spend from cash_on_hand when available cash is insufficient."""
    if rec.kind not in (RecordKind.expense, RecordKind.fuel):
        return
    source = rec.payment_source or "cash_on_hand"
    if source != "cash_on_hand":
        return
    owner = db.get(User, rec.created_by)
    if not owner:
        return
    bal = user_balance(db, owner)
    held = float(bal.get("cash_on_hand") or 0)
    reserved = float(bal.get("reserved_cash") or 0)
    available = float(
        bal.get("available_cash") if bal.get("available_cash") is not None else max(0.0, held - reserved)
    )
    if float(rec.amount) > available + 1e-6:
        raise HTTPException(
            400,
            f"Only {available} available from cash on hand "
            f"({held} held, {reserved} reserved by pending requests). "
            f"Cannot approve {rec.amount} from cash.",
        )


def _last_fuel_odometer(
    db: Session,
    org_id: int,
    owner_id: int,
    bike: str,
    *,
    exclude_id: int | None = None,
) -> MoneyRecord | None:
    """Latest non-rejected fuel reading for bike (or owner when bike blank)."""
    eff = func.coalesce(MoneyRecord.occurred_at, MoneyRecord.created_at)
    q = db.query(MoneyRecord).filter(
        MoneyRecord.organization_id == org_id,
        MoneyRecord.kind == RecordKind.fuel,
        MoneyRecord.status != RecordStatus.rejected,
        MoneyRecord.is_voided.is_(False),
        MoneyRecord.odometer.isnot(None),
    )
    bike_key = (bike or "").strip()
    if bike_key:
        q = q.filter(MoneyRecord.bike == bike_key)
    else:
        q = q.filter(MoneyRecord.created_by == owner_id, MoneyRecord.bike == "")
    if exclude_id is not None:
        q = q.filter(MoneyRecord.id != exclude_id)
    return q.order_by(eff.desc(), MoneyRecord.id.desc()).first()


def _assert_odometer(
    db: Session,
    org_id: int,
    owner_id: int,
    bike: str,
    odometer: float | None,
    *,
    exclude_id: int | None = None,
) -> None:
    if odometer is None:
        return
    last = _last_fuel_odometer(db, org_id, owner_id, bike, exclude_id=exclude_id)
    if last is not None and float(odometer) + 1e-6 < float(last.odometer or 0):
        label = (bike or "").strip() or "this rider"
        raise HTTPException(
            400,
            f"Odometer cannot decrease for {label} (last {last.odometer}).",
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
    if body.kind == RecordKind.fuel:
        _assert_odometer(
            db,
            user.organization_id,
            owner_id,
            body.bike,
            body.odometer,
        )
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
    voided: bool | None = None,
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
    if voided is True:
        query = query.filter(MoneyRecord.is_voided.is_(True))
    elif voided is False:
        query = query.filter(MoneyRecord.is_voided.is_(False))
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
    voided: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    query = db.query(MoneyRecord).filter(MoneyRecord.organization_id == user.organization_id)
    if kind:
        query = query.filter(MoneyRecord.kind == kind)
    if status:
        query = query.filter(MoneyRecord.status == status)
    if voided is True:
        query = query.filter(MoneyRecord.is_voided.is_(True))
    elif voided is False:
        query = query.filter(MoneyRecord.is_voided.is_(False))
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
        last_expense_payout_at=bal.get("last_expense_payout_at"),
        last_income_handover_at=bal.get("last_income_handover_at"),
        reserved_spendings=float(bal.get("reserved_spendings") or 0),
        reserved_cash=float(bal.get("reserved_cash") or 0),
        available_spendings=float(bal.get("available_spendings") or 0),
        available_cash=float(bal.get("available_cash") or 0),
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


@router.get("/fuel/last-odometer")
def last_fuel_odometer(
    bike: str = "",
    user_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hint for fuel form — latest reading for bike (or rider when bike blank)."""
    owner_id = user.id
    if user_id is not None and user_id != user.id:
        if user.role not in (UserRole.owner, UserRole.manager):
            raise HTTPException(403, "Insufficient role")
        target = db.get(User, user_id)
        if not target or target.organization_id != user.organization_id:
            raise HTTPException(404, "User not found")
        owner_id = target.id
    last = _last_fuel_odometer(db, user.organization_id, owner_id, bike)
    return {
        "bike": (bike or "").strip(),
        "user_id": owner_id,
        "odometer": float(last.odometer) if last and last.odometer is not None else None,
        "record_id": last.id if last else None,
        "occurred_at": (last.occurred_at or last.created_at).isoformat()
        if last and (last.occurred_at or last.created_at)
        else None,
    }


@router.post("/decide-batch", response_model=list[RecordOut])
def decide_batch(
    body: DecideBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    """Approve/reject many pending records in one call."""
    if not body.approve and not (body.note or "").strip():
        raise HTTPException(400, "Reject requires a note")
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
    if rec.kind == RecordKind.fuel:
        next_bike = data["bike"] if "bike" in data else rec.bike
        next_odo = data["odometer"] if "odometer" in data else rec.odometer
        _assert_odometer(
            db,
            rec.organization_id,
            rec.created_by,
            next_bike or "",
            next_odo,
            exclude_id=rec.id,
        )
    for key, value in data.items():
        setattr(rec, key, value)
    # Re-normalize money fields after edit (create path already validates)
    if "payment_source" in data or "payment_method" in data:
        source, method = _normalize_payment_fields(
            rec.kind, rec.payment_source or "", rec.payment_method or ""
        )
        rec.payment_source = source
        rec.payment_method = method
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
    else:
        if not (body.note or "").strip():
            raise HTTPException(400, "Reject requires a note")
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
