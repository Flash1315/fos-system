from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import create_media_token, get_current_user, require_roles
from app.categories import PAYMENT_METHODS, PAYMENT_SOURCES, PURPOSES, categories_for
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User, UserRole
from app.schemas import (
    BalanceOut,
    CategoriesOut,
    CommentIn,
    DecideBatchIn,
    DecideBatchOut,
    DecideIn,
    RecordCreate,
    RecordOut,
    RecordUpdate,
)
from app.services.balances import user_balance
from app.services.org_limits import require_org_member_capacity

router = APIRouter(prefix="/records", tags=["records"])

_PHOTO_RE = re.compile(r"^/media/files/(\d+)/([0-9a-f]{32}\.(?:jpg|png|webp))$")
_SEARCH_MAX = 80
_COMMENT_MAX = 4000
_BIKE_MAX = 120
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_PURPOSE_MAX = 80


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_bike(bike: str | None) -> str:
    raw = bike or ""
    if _CTRL_RE.search(raw):
        raise HTTPException(400, "bike contains invalid characters")
    cleaned = re.sub(r"\s+", " ", raw.strip())
    if len(cleaned) > _BIKE_MAX:
        raise HTTPException(400, f"bike too long (max {_BIKE_MAX})")
    return cleaned


def _normalize_spaced(value: str | None, *, field: str, max_len: int) -> str:
    raw = value or ""
    if _CTRL_RE.search(raw):
        raise HTTPException(400, f"{field} contains invalid characters")
    cleaned = re.sub(r"\s+", " ", raw.strip())
    if len(cleaned) > max_len:
        raise HTTPException(400, f"{field} too long (max {max_len})")
    return cleaned


def _append_text(existing: str | None, addition: str, *, label: str = "Comment") -> str:
    """Append an audit line, truncating older text so lifecycle actions never block."""
    base = (existing or "").rstrip()
    add = (addition or "").strip()
    if not add:
        return base
    if len(add) > _COMMENT_MAX:
        add = add[: _COMMENT_MAX - 1] + "…"
    if not base:
        return add
    sep = "\n"
    combined = f"{base}{sep}{add}"
    if len(combined) <= _COMMENT_MAX:
        return combined
    head_budget = _COMMENT_MAX - len(sep) - len(add)
    if head_budget <= 0:
        return add
    head = base[:head_budget]
    if len(base) > head_budget and head_budget > 1:
        head = head[:-1] + "…"
    return f"{head}{sep}{add}"


def _bound_purpose(purpose: str | None) -> str | None:
    raw = purpose or ""
    if _CTRL_RE.search(raw):
        raise HTTPException(400, "purpose contains invalid characters")
    value = re.sub(r"\s+", " ", raw.strip())
    if len(value) > _PURPOSE_MAX:
        raise HTTPException(400, f"purpose too long (max {_PURPOSE_MAX})")
    return value or None


def _search_like(q: str | None) -> str | None:
    raw = q or ""
    if _CTRL_RE.search(raw):
        raise HTTPException(400, "Search query contains invalid characters")
    cleaned = re.sub(r"\s+", " ", raw.strip())
    if not cleaned:
        return None
    if len(cleaned) > _SEARCH_MAX:
        raise HTTPException(400, f"Search query too long (max {_SEARCH_MAX} characters)")
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _validate_photo_url(photo_url: str, org_id: int) -> str:
    url = (photo_url or "").strip()
    if not url:
        return ""
    m = _PHOTO_RE.match(url)
    if not m:
        raise HTTPException(
            400,
            "photo_url must be an uploaded /media/files/{org}/{uuid}.{jpg|png|webp} path",
        )
    if int(m.group(1)) != org_id:
        raise HTTPException(400, "photo_url does not belong to this organization")
    return url


def _validate_occurred_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    now = _utcnow()
    # Normalize aware → naive UTC
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value > now + timedelta(days=1):
        raise HTTPException(400, "occurred_at cannot be more than 1 day in the future")
    if value < now - timedelta(days=365 * 10):
        raise HTTPException(400, "occurred_at cannot be older than 10 years")
    return value


def _normalize_category_purpose(kind: RecordKind, category: str, purpose: str) -> tuple[str, str]:
    raw_cat = category or ""
    if _CTRL_RE.search(raw_cat):
        raise HTTPException(400, "category contains invalid characters")
    cat = re.sub(r"\s+", " ", raw_cat.strip())
    if not cat:
        raise HTTPException(400, "category is required")
    if len(cat) > 120:
        raise HTTPException(400, "category too long (max 120)")
    pur = (purpose or "").strip()
    if kind in (RecordKind.expense, RecordKind.fuel):
        if not pur:
            pur = "Other"
        if pur not in PURPOSES:
            raise HTTPException(400, f"purpose must be one of {PURPOSES}")
    elif kind == RecordKind.income:
        # Income may omit purpose; keep empty or validate when set
        if pur and pur not in PURPOSES:
            raise HTTPException(400, f"purpose must be one of {PURPOSES}")
    return cat, pur


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
    from app.services.balances import (
        can_void_record,
        record_in_closed_cycle,
        record_settlement_cutoff_at,
        void_blocked_reason,
    )

    creator = db.get(User, rec.created_by)
    decider = db.get(User, rec.decided_by) if rec.decided_by else None
    data = RecordOut.model_validate(rec)
    return data.model_copy(
        update={
            "created_by_name": creator.full_name if creator else "",
            "created_by_active": bool(creator.is_active) if creator else False,
            "decided_by_name": decider.full_name if decider else "",
            "can_void": can_void_record(db, rec),
            "void_blocked_reason": void_blocked_reason(db, rec),
            "is_in_closed_cycle": record_in_closed_cycle(db, rec),
            "settlement_cutoff_at": record_settlement_cutoff_at(db, rec),
        }
    )


def _assert_cash_for_approve(
    db: Session,
    rec: MoneyRecord,
    *,
    extra_spent: float = 0.0,
) -> None:
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
    available = max(0.0, available - float(extra_spent or 0))
    if float(rec.amount) > available + 1e-6:
        raise HTTPException(
            400,
            f"Only {available} available from cash on hand "
            f"({held} held, {reserved} reserved by pending requests). "
            f"Cannot approve {rec.amount} from cash.",
        )


def _is_cash_on_hand_spend(rec: MoneyRecord) -> bool:
    if rec.kind not in (RecordKind.expense, RecordKind.fuel):
        return False
    return (rec.payment_source or "cash_on_hand") == "cash_on_hand"


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
        q = q.filter(func.trim(MoneyRecord.bike) == bike_key)
    else:
        q = q.filter(
            MoneyRecord.created_by == owner_id,
            func.trim(MoneyRecord.bike) == "",
        )
    if exclude_id is not None:
        q = q.filter(MoneyRecord.id != exclude_id)
    return q.order_by(eff.desc(), MoneyRecord.id.desc()).first()


def _fuel_odometer_neighbors(
    db: Session,
    org_id: int,
    owner_id: int,
    bike: str,
    *,
    at: datetime,
    exclude_id: int | None = None,
) -> tuple[MoneyRecord | None, MoneyRecord | None]:
    """Nearest prior/next fuel readings with odometer around effective time `at`."""
    from sqlalchemy import and_, or_

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
        q = q.filter(func.trim(MoneyRecord.bike) == bike_key)
    else:
        q = q.filter(
            MoneyRecord.created_by == owner_id,
            func.trim(MoneyRecord.bike) == "",
        )
    if exclude_id is not None:
        q = q.filter(MoneyRecord.id != exclude_id)
        pred = (
            q.filter(or_(eff < at, and_(eff == at, MoneyRecord.id < exclude_id)))
            .order_by(eff.desc(), MoneyRecord.id.desc())
            .first()
        )
        succ = (
            q.filter(or_(eff > at, and_(eff == at, MoneyRecord.id > exclude_id)))
            .order_by(eff.asc(), MoneyRecord.id.asc())
            .first()
        )
    else:
        pred = q.filter(eff <= at).order_by(eff.desc(), MoneyRecord.id.desc()).first()
        succ = q.filter(eff > at).order_by(eff.asc(), MoneyRecord.id.asc()).first()
    return pred, succ


def _assert_odometer(
    db: Session,
    org_id: int,
    owner_id: int,
    bike: str,
    odometer: float | None,
    *,
    at: datetime | None = None,
    exclude_id: int | None = None,
) -> None:
    when = at or _utcnow()
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    pred, succ = _fuel_odometer_neighbors(
        db, org_id, owner_id, bike, at=when, exclude_id=exclude_id
    )
    has_history = pred is not None or succ is not None
    if not has_history:
        # Fall back: any prior reading still forces odometer (legacy latest path).
        has_history = _last_fuel_odometer(db, org_id, owner_id, bike, exclude_id=exclude_id) is not None
    label = (bike or "").strip() or "this rider"
    if odometer is None:
        if has_history:
            last = pred or succ or _last_fuel_odometer(
                db, org_id, owner_id, bike, exclude_id=exclude_id
            )
            raise HTTPException(
                400,
                f"Odometer is required after a prior fuel reading for {label} "
                f"(last {last.odometer if last else '—'}).",
            )
        return
    value = float(odometer)
    if pred is not None and value + 1e-6 < float(pred.odometer or 0):
        raise HTTPException(
            400,
            f"Odometer cannot decrease for {label} "
            f"(previous {pred.odometer} at {(pred.occurred_at or pred.created_at)}).",
        )
    if succ is not None and value - 1e-6 > float(succ.odometer or 0):
        raise HTTPException(
            400,
            f"Odometer cannot exceed a later reading for {label} "
            f"(next {succ.odometer} at {(succ.occurred_at or succ.created_at)}).",
        )


@router.get("/categories", response_model=CategoriesOut)
def list_categories(
    kind: RecordKind | None = None,
    user: User = Depends(get_current_user),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"categories:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
        commit_or_replay,
    )
    from app.services.money import require_positive_money
    from app.services.org_gates import require_org_writable
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-create:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    require_org_writable(db, user.organization_id)

    key = normalize_idem_key(idempotency_key)
    fp = fingerprint(body.model_dump(mode="json")) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.create",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(MoneyRecord, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _record_out(db, existing)
    org = db.get(Organization, user.organization_id)
    if body.approve_now and user.role not in (UserRole.owner, UserRole.manager):
        raise HTTPException(403, "Only managers can approve on create")
    source, method = _normalize_payment_fields(body.kind, body.payment_source, body.payment_method)
    category, purpose = _normalize_category_purpose(body.kind, body.category, body.purpose)
    owner_id = user.id
    body_comment = body.comment
    try:
        amount = require_positive_money(body.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    photo_url = _validate_photo_url(body.photo_url, user.organization_id)
    occurred_at = _validate_occurred_at(body.occurred_at)
    bike = _normalize_bike(body.bike)
    place = _normalize_spaced(body.place, field="place", max_len=200)
    client_name = _normalize_spaced(body.client_name, field="client_name", max_len=200)
    if body.created_for_user_id is not None:
        if user.role not in (UserRole.owner, UserRole.manager):
            raise HTTPException(403, "Only managers can create on behalf")
        target = db.get(User, body.created_for_user_id)
        if not target or target.organization_id != user.organization_id:
            raise HTTPException(404, "Target user not found")
        from app.services.org_gates import require_member_ready

        require_member_ready(target, action="filing on their behalf")
        owner_id = target.id
        stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
        note = f"[filed by {user.full_name} {stamp}]"
        body_comment = _append_text(body.comment, note)
    if body.kind == RecordKind.fuel:
        _assert_odometer(
            db,
            user.organization_id,
            owner_id,
            bike,
            body.odometer,
            at=occurred_at or _utcnow(),
        )
    rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=owner_id,
        kind=body.kind,
        status=RecordStatus.pending,
        amount=amount,
        currency=org.currency if org else "IDR",
        category=category,
        purpose=purpose,
        place=place,
        bike=bike,
        comment=body_comment,
        photo_url=photo_url,
        liters=body.liters,
        odometer=body.odometer,
        client_name=client_name,
        payment_method=method,
        payment_source=source,
        occurred_at=occurred_at,
    )
    db.add(rec)
    if body.approve_now:
        from app.services.locks import lock_users

        lock_users(db, owner_id)
        if body.kind == RecordKind.fuel:
            _assert_odometer(
                db,
                user.organization_id,
                owner_id,
                bike,
                body.odometer,
                at=occurred_at or _utcnow(),
                exclude_id=None,
            )
        _assert_cash_for_approve(db, rec)
        rec.status = RecordStatus.approved
        rec.decided_by = user.id
        rec.decided_at = _utcnow()
        stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
        note = f"[auto-approved on create by {user.full_name} {stamp}]"
        rec.comment = _append_text(rec.comment, note)
    db.flush()
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.create",
            key=key,
            resource_id=rec.id,
            request_hash=fp,
        )
    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.create",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _record_out(db, existing)
            if (existing := db.get(MoneyRecord, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(rec)
    return _record_out(db, rec)


@router.get("/mine", response_model=list[RecordOut])
def my_records(
    kind: RecordKind | None = None,
    status: RecordStatus | None = None,
    purpose: str | None = None,
    q: str | None = None,
    voided: bool | None = None,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"records-mine:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    purpose = _bound_purpose(purpose)
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
    like = _search_like(q)
    if like:
        query = query.filter(
            (MoneyRecord.category.ilike(like, escape="\\"))
            | (MoneyRecord.comment.ilike(like, escape="\\"))
            | (MoneyRecord.place.ilike(like, escape="\\"))
            | (MoneyRecord.bike.ilike(like, escape="\\"))
            | (MoneyRecord.client_name.ilike(like, escape="\\"))
        )
    rows = (
        query.order_by(MoneyRecord.created_at.desc(), MoneyRecord.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_record_out(db, r) for r in rows]


@router.get("/org", response_model=list[RecordOut])
def org_records(
    kind: RecordKind | None = None,
    status: RecordStatus | None = None,
    purpose: str | None = None,
    created_by: int | None = None,
    q: str | None = None,
    voided: bool | None = None,
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"records-org:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    purpose = _bound_purpose(purpose)
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
    like = _search_like(q)
    if like:
        query = query.filter(
            (MoneyRecord.category.ilike(like, escape="\\"))
            | (MoneyRecord.comment.ilike(like, escape="\\"))
            | (MoneyRecord.place.ilike(like, escape="\\"))
            | (MoneyRecord.bike.ilike(like, escape="\\"))
            | (MoneyRecord.client_name.ilike(like, escape="\\"))
        )
    rows = (
        query.order_by(MoneyRecord.created_at.desc(), MoneyRecord.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_record_out(db, r) for r in rows]


@router.get("/pending", response_model=list[RecordOut])
def pending_records(
    purpose: str | None = None,
    kind: RecordKind | None = None,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"records-pending:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    purpose = _bound_purpose(purpose)
    q = db.query(MoneyRecord).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.status == RecordStatus.pending,
    )
    if purpose:
        q = q.filter(MoneyRecord.purpose == purpose)
    if kind:
        q = q.filter(MoneyRecord.kind == kind)
    rows = q.order_by(MoneyRecord.created_at.asc(), MoneyRecord.id.asc()).offset(offset).limit(limit).all()
    return [_record_out(db, r) for r in rows]


@router.get("/pending/count")
def pending_count(
    purpose: str | None = None,
    kind: RecordKind | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"records-pending-count:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    purpose = _bound_purpose(purpose)
    q = db.query(func.count(MoneyRecord.id)).filter(
        MoneyRecord.organization_id == user.organization_id,
        MoneyRecord.status == RecordStatus.pending,
    )
    if purpose:
        q = q.filter(MoneyRecord.purpose == purpose)
    if kind:
        q = q.filter(MoneyRecord.kind == kind)
    return {"count": int(q.scalar() or 0)}


@router.get("/media-token")
def issue_media_token(user: User = Depends(get_current_user)):
    """Short-lived token for loading receipt images without the full access JWT."""
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(f"media-token:{user.organization_id}:{user.id}", limit=60, window_sec=60)
    token = create_media_token(
        user.id, user.organization_id, user.token_version or 0, minutes=15
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": 900}


@router.get("/balance/me", response_model=BalanceOut)
def my_balance(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """RJ-inspired dual track with payout cutoffs (per user, approved only)."""
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"balance-me:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
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
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"balance-team:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    require_org_member_capacity(db, user.organization_id, active_only=True)
    from app.services.org_limits import org_member_limit

    members = (
        db.query(User)
        .filter(
            User.organization_id == user.organization_id,
            User.is_active.is_(True),
            User.must_set_password.is_(False),
        )
        .order_by(User.full_name.asc(), User.id.asc())
        .limit(org_member_limit())
        .all()
    )
    return [user_balance(db, m) for m in members]


@router.get("/fuel/last-odometer")
def last_fuel_odometer(
    bike: str = "",
    user_id: int | None = None,
    at: str | None = None,
    exclude_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hint for fuel form — latest or neighbor bounds around optional `at` (ISO date/datetime)."""
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"fuel-odo:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    if at is not None and len(at) > 40:
        raise HTTPException(400, "at is too long")
    owner_id = user.id
    if user_id is not None and user_id != user.id:
        if user.role not in (UserRole.owner, UserRole.manager):
            raise HTTPException(403, "Insufficient role")
        target = db.get(User, user_id)
        if not target or target.organization_id != user.organization_id:
            raise HTTPException(404, "User not found")
        owner_id = target.id
    bike_key = _normalize_bike(bike)
    when: datetime | None = None
    if (at or "").strip():
        raw = at.strip()
        try:
            if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
                when = datetime.fromisoformat(f"{raw}T12:00:00")
            else:
                when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if when.tzinfo is not None:
                    when = when.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError as exc:
            raise HTTPException(400, "at must be YYYY-MM-DD or ISO datetime") from exc
        when = _validate_occurred_at(when)
    last = _last_fuel_odometer(
        db, user.organization_id, owner_id, bike_key, exclude_id=exclude_id
    )
    if when is not None:
        pred, succ = _fuel_odometer_neighbors(
            db, user.organization_id, owner_id, bike_key, at=when, exclude_id=exclude_id
        )
        return {
            "bike": bike_key,
            "user_id": owner_id,
            "odometer": float(pred.odometer) if pred and pred.odometer is not None else None,
            "min_odometer": float(pred.odometer) if pred and pred.odometer is not None else None,
            "max_odometer": float(succ.odometer) if succ and succ.odometer is not None else None,
            "record_id": pred.id if pred else None,
            "occurred_at": (pred.occurred_at or pred.created_at).isoformat()
            if pred and (pred.occurred_at or pred.created_at)
            else None,
            "has_history": pred is not None or succ is not None or last is not None,
        }
    return {
        "bike": bike_key,
        "user_id": owner_id,
        "odometer": float(last.odometer) if last and last.odometer is not None else None,
        "min_odometer": float(last.odometer) if last and last.odometer is not None else None,
        "max_odometer": None,
        "record_id": last.id if last else None,
        "occurred_at": (last.occurred_at or last.created_at).isoformat()
        if last and (last.occurred_at or last.created_at)
        else None,
        "has_history": last is not None,
    }


@router.post("/decide-batch", response_model=DecideBatchOut)
def decide_batch(
    body: DecideBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Approve/reject many pending records in one call."""
    from app.services.idempotency import (
        dumps_json,
        fingerprint,
        loads_json,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-decide-batch:{user.organization_id}:{user.id}",
        limit=20,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    require_org_writable(db, user.organization_id)

    if not body.approve and len(body.note or "") < 2:
        raise HTTPException(400, "Reject requires a note (min 2 characters)")
    key = normalize_idem_key(idempotency_key)
    fp = fingerprint(body.model_dump(mode="json")) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.decide_batch",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            if hit.response_json:
                cached = loads_json(hit.response_json)
                if isinstance(cached, dict):
                    return DecideBatchOut.model_validate(cached)
    from app.services.locks import lock_users

    # Preload pending targets so we can lock creators before balance checks.
    pending_rows = []
    for rid in body.ids:
        rec = db.get(MoneyRecord, rid)
        if (
            rec
            and rec.organization_id == user.organization_id
            and rec.status == RecordStatus.pending
        ):
            pending_rows.append(rec)
    if body.approve and pending_rows:
        lock_users(db, *[r.created_by for r in pending_rows])
    out = []
    skipped = 0
    skipped_cash = 0
    skipped_inactive = 0
    # Track cash_on_hand spend approved in this batch (session autoflush is off).
    extra_cash_spent: dict[int, float] = {}
    for rid in body.ids:
        rec = (
            db.query(MoneyRecord)
            .filter(
                MoneyRecord.id == rid,
                MoneyRecord.organization_id == user.organization_id,
            )
            .with_for_update()
            .first()
        )
        if not rec or rec.organization_id != user.organization_id:
            skipped += 1
            continue
        if rec.status != RecordStatus.pending:
            skipped += 1
            continue
        if body.approve:
            creator = db.get(User, rec.created_by)
            if creator is not None and not creator.is_active:
                skipped += 1
                skipped_inactive += 1
                continue
            spent = extra_cash_spent.get(rec.created_by, 0.0)
            if rec.kind == RecordKind.fuel:
                try:
                    _assert_odometer(
                        db,
                        rec.organization_id,
                        rec.created_by,
                        rec.bike or "",
                        float(rec.odometer) if rec.odometer is not None else None,
                        at=rec.occurred_at or rec.created_at,
                        exclude_id=rec.id,
                    )
                except HTTPException:
                    skipped += 1
                    continue
            try:
                _assert_cash_for_approve(db, rec, extra_spent=spent)
            except HTTPException:
                skipped += 1
                skipped_cash += 1
                continue
            if _is_cash_on_hand_spend(rec):
                extra_cash_spent[rec.created_by] = spent + float(rec.amount)
        rec.status = RecordStatus.approved if body.approve else RecordStatus.rejected
        rec.decided_at = _utcnow()
        rec.decided_by = user.id
        if body.note:
            rec.comment = _append_text(rec.comment, f"[review] {body.note}")
        out.append(rec)
    if not out:
        if skipped_cash > 0:
            raise HTTPException(
                400,
                "No records approved — insufficient cash on hand for the selected spend",
            )
        if skipped_inactive > 0:
            raise HTTPException(
                400,
                "No records approved — selected records belong to inactive teammates",
            )
        # Soft retry: every id exists and is already at the desired decided status.
        desired = RecordStatus.approved if body.approve else RecordStatus.rejected
        already_ok = 0
        missing = 0
        conflict = False
        for rid in body.ids:
            rec = db.get(MoneyRecord, rid)
            if not rec or rec.organization_id != user.organization_id:
                missing += 1
                continue
            if rec.status == desired and not rec.is_voided:
                already_ok += 1
            else:
                conflict = True
                break
        if already_ok > 0 and missing == 0 and not conflict:
            return DecideBatchOut(
                decided=[],
                skipped=len(body.ids),
                skipped_insufficient_cash=0,
                skipped_inactive=0,
            )
        raise HTTPException(400, "No pending records matched the given ids")
    payload = DecideBatchOut(
        decided=[_record_out(db, r) for r in out],
        skipped=skipped,
        skipped_insufficient_cash=skipped_cash,
        skipped_inactive=skipped_inactive,
    )
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.decide_batch",
            key=key,
            resource_id=out[0].id,
            response_json=dumps_json(payload.model_dump(mode="json")),
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.decide_batch",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            DecideBatchOut.model_validate(cached)
            if hit.response_json
            and isinstance((cached := loads_json(hit.response_json)), dict)
            else None
        ),
    )
    if replay is not None:
        return replay
    for rec in out:
        db.refresh(rec)
    # Rebuild after refresh so timestamps/ids are current
    return DecideBatchOut(
        decided=[_record_out(db, r) for r in out],
        skipped=skipped,
        skipped_insufficient_cash=skipped_cash,
        skipped_inactive=skipped_inactive,
    )


@router.get("/{record_id}", response_model=RecordOut)
def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-get:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Creator or manager can edit fields while status is still pending."""
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
        commit_or_replay,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-update:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    require_org_writable(db, user.organization_id)

    key = normalize_idem_key(idempotency_key)
    fp = (
        fingerprint({"record_id": record_id, **body.model_dump(mode="json")})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.update",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(MoneyRecord, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _record_out(db, existing)

    rec = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    is_manager = user.role in (UserRole.owner, UserRole.manager)
    if rec.created_by != user.id and not is_manager:
        raise HTTPException(403, "Insufficient role")
    if rec.status != RecordStatus.pending:
        raise HTTPException(400, "Only pending records can be edited")
    data = body.model_dump(exclude_unset=True)
    if "amount" in data and data["amount"] is None:
        raise HTTPException(400, "amount cannot be null")
    if "amount" in data and data["amount"] is not None:
        from app.services.money import require_positive_money

        try:
            data["amount"] = require_positive_money(data["amount"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "photo_url" in data:
        data["photo_url"] = _validate_photo_url(data["photo_url"] or "", user.organization_id)
    if "occurred_at" in data:
        data["occurred_at"] = _validate_occurred_at(data["occurred_at"])
    if "bike" in data:
        data["bike"] = _normalize_bike(data["bike"])
    if "place" in data:
        data["place"] = _normalize_spaced(data["place"], field="place", max_len=200)
    if "client_name" in data:
        data["client_name"] = _normalize_spaced(
            data["client_name"], field="client_name", max_len=200
        )
    if rec.kind == RecordKind.fuel:
        from app.services.locks import lock_users

        lock_users(db, rec.created_by)
        next_bike = data["bike"] if "bike" in data else rec.bike
        next_odo = data["odometer"] if "odometer" in data else rec.odometer
        next_at = (
            data["occurred_at"]
            if "occurred_at" in data
            else (rec.occurred_at or rec.created_at)
        )
        _assert_odometer(
            db,
            rec.organization_id,
            rec.created_by,
            next_bike or "",
            next_odo,
            at=next_at,
            exclude_id=rec.id,
        )
    if "category" in data or "purpose" in data:
        next_cat = data["category"] if "category" in data else rec.category
        next_pur = data["purpose"] if "purpose" in data else rec.purpose
        cat, pur = _normalize_category_purpose(rec.kind, next_cat or "", next_pur or "")
        data["category"] = cat
        data["purpose"] = pur
    for field, value in data.items():
        setattr(rec, field, value)
    if rec.kind == RecordKind.fuel and (rec.liters is None or float(rec.liters) <= 0):
        raise HTTPException(400, "Fuel records require liters > 0")
    # Re-normalize money fields after edit (create path already validates)
    if "payment_source" in data or "payment_method" in data:
        source, method = _normalize_payment_fields(
            rec.kind, rec.payment_source or "", rec.payment_method or ""
        )
        rec.payment_source = source
        rec.payment_method = method
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.update",
            key=key,
            resource_id=rec.id,
            request_hash=fp,
        )
    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.update",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _record_out(db, existing)
            if (existing := db.get(MoneyRecord, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(rec)
    return _record_out(db, rec)


@router.post("/{record_id}/decide", response_model=RecordOut)
def decide_record(
    record_id: int,
    body: DecideIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-decide:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    require_org_writable(db, user.organization_id)

    key = normalize_idem_key(idempotency_key)
    fp = (
        fingerprint({"record_id": record_id, **body.model_dump(mode="json")})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.decide",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(MoneyRecord, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _record_out(db, existing)
    peek = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .first()
    )
    if not peek or peek.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if peek.status != RecordStatus.pending:
        desired = RecordStatus.approved if body.approve else RecordStatus.rejected
        if peek.status == desired and not peek.is_voided:
            return _record_out(db, peek)
        raise HTTPException(400, "Already decided")
    if body.approve:
        from app.services.locks import lock_users

        # Lock users before record rows — same order as transfers (avoids PG deadlocks).
        lock_users(db, peek.created_by)
    rec = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if rec.status != RecordStatus.pending:
        desired = RecordStatus.approved if body.approve else RecordStatus.rejected
        if rec.status == desired and not rec.is_voided:
            return _record_out(db, rec)
        raise HTTPException(400, "Already decided")
    if body.approve:
        creator = db.get(User, rec.created_by)
        if creator is not None and not creator.is_active:
            raise HTTPException(
                400,
                "Cannot approve — record owner is inactive. Reject instead or reactivate them.",
            )
        if rec.kind == RecordKind.fuel:
            _assert_odometer(
                db,
                rec.organization_id,
                rec.created_by,
                rec.bike or "",
                float(rec.odometer) if rec.odometer is not None else None,
                at=rec.occurred_at or rec.created_at,
                exclude_id=rec.id,
            )
        _assert_cash_for_approve(db, rec)
    else:
        if len(body.note or "") < 2:
            raise HTTPException(400, "Reject requires a note (min 2 characters)")
    rec.status = RecordStatus.approved if body.approve else RecordStatus.rejected
    rec.decided_at = _utcnow()
    rec.decided_by = user.id
    if body.note:
        rec.comment = _append_text(rec.comment, f"[review] {body.note}")
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.decide",
            key=key,
            resource_id=rec.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.decide",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _record_out(db, existing)
            if (existing := db.get(MoneyRecord, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(rec)
    return _record_out(db, rec)


@router.post("/{record_id}/comment", response_model=RecordOut)
def comment_record(
    record_id: int,
    body: CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-comment:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    require_org_writable(db, user.organization_id)

    key = normalize_idem_key(idempotency_key)
    fp = (
        fingerprint({"record_id": record_id, **body.model_dump(mode="json")})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.comment",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(MoneyRecord, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _record_out(db, existing)
    rec = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
    rec.comment = _append_text(rec.comment, f"[mgr {user.full_name} {stamp}] {body.note}")
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.comment",
            key=key,
            resource_id=rec.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.comment",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _record_out(db, existing)
            if (existing := db.get(MoneyRecord, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(rec)
    return _record_out(db, rec)


@router.post("/{record_id}/void", response_model=RecordOut)
def void_approved_record(
    record_id: int,
    body: CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Manager voids an approved record; kept for audit, excluded from balances.

    Transfer legs are voided together via transfer_group_id.
    Records already included in a settlement cutoff cannot be voided until
    that payout is voided first.
    """
    from app.services.balances import assert_void_records_keep_non_negative, can_void_record
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-void:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    require_org_writable(db, user.organization_id)

    key = normalize_idem_key(idempotency_key)
    fp = (
        fingerprint({"record_id": record_id, **body.model_dump(mode="json")})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.void",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(MoneyRecord, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _record_out(db, existing)
    peek = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .first()
    )
    if not peek or peek.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if peek.status != RecordStatus.approved:
        raise HTTPException(400, "Only approved records can be voided")
    if peek.is_voided:
        return _record_out(db, peek)
    if not can_void_record(db, peek):
        raise HTTPException(
            400,
            "Record is locked by a settlement. Void the latest payout first.",
        )
    owner_ids = {peek.created_by}
    if peek.transfer_group_id:
        owner_ids = {
            uid
            for (uid,) in db.query(MoneyRecord.created_by)
            .filter(
                MoneyRecord.organization_id == user.organization_id,
                MoneyRecord.transfer_group_id == peek.transfer_group_id,
                MoneyRecord.is_voided.is_(False),
            )
            .all()
        } or owner_ids
    from app.services.locks import lock_users

    # Users before record rows — matches create_transfer lock order.
    lock_users(db, *sorted(owner_ids))
    rec = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if rec.status != RecordStatus.approved:
        raise HTTPException(400, "Only approved records can be voided")
    if rec.is_voided:
        return _record_out(db, rec)
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
            .order_by(MoneyRecord.id.asc())
            .with_for_update()
            .all()
        )
        targets = siblings or [rec]
    for row in targets:
        if not can_void_record(db, row):
            raise HTTPException(
                400,
                "Record is locked by a settlement. Void the latest payout first.",
            )
    assert_void_records_keep_non_negative(db, targets)
    for row in targets:
        row.is_voided = True
        row.voided_at = now
        row.voided_by = user.id
        row.comment = _append_text(row.comment, note)
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.void",
            key=key,
            resource_id=rec.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.void",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _record_out(db, existing)
            if (existing := db.get(MoneyRecord, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(rec)
    return _record_out(db, rec)


@router.delete("/{record_id}", response_model=RecordOut)
def cancel_pending_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Creator can cancel a still-pending record by rejecting it.

    Managers must use decide/reject with a note instead of silent DELETE cancel.
    """
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"record-cancel:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    # Cancel is allowed during billing freeze so pending work can be released.

    key = normalize_idem_key(idempotency_key)
    fp = fingerprint({"record_id": record_id}) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.cancel",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(MoneyRecord, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _record_out(db, existing)
    rec = (
        db.query(MoneyRecord)
        .filter(
            MoneyRecord.id == record_id,
            MoneyRecord.organization_id == user.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not rec or rec.organization_id != user.organization_id:
        raise HTTPException(404, "Record not found")
    if rec.created_by != user.id:
        raise HTTPException(
            403,
            "Only the creator can cancel — managers should reject with a note",
        )
    if rec.status != RecordStatus.pending:
        if rec.status == RecordStatus.rejected and "[cancelled]" in (rec.comment or ""):
            return _record_out(db, rec)
        raise HTTPException(400, "Only pending records can be cancelled")
    rec.status = RecordStatus.rejected
    rec.decided_at = _utcnow()
    rec.decided_by = user.id
    rec.comment = _append_text(rec.comment, "[cancelled]")
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="records.cancel",
            key=key,
            resource_id=rec.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="records.cancel",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _record_out(db, existing)
            if (existing := db.get(MoneyRecord, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(rec)
    return _record_out(db, rec)
