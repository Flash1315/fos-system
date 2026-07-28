from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserRole

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login-form")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_access_token(user_id: int, org_id: int, role: str, token_version: int = 0) -> str:
    expire = _utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "org": org_id,
        "role": role,
        "ver": int(token_version or 0),
        "typ": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_media_token(user_id: int, org_id: int, token_version: int = 0, minutes: int = 15) -> str:
    """Short-lived token for <Image> query auth — scoped to media only."""
    expire = _utcnow() + timedelta(minutes=max(1, minutes))
    payload = {
        "sub": str(user_id),
        "org": org_id,
        "ver": int(token_version or 0),
        "typ": "media",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def user_from_token(token: str, db: Session, *, allow_media: bool = False) -> User:
    """Decode JWT and return active user; rejects revoked token_version."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = int(payload.get("sub", 0))
        token_ver = int(payload.get("ver", 0) or 0)
        typ = payload.get("typ") or "access"
    except (JWTError, ValueError, TypeError):
        raise credentials_exc
    if typ == "media" and not allow_media:
        raise credentials_exc
    if typ not in ("access", "media"):
        raise credentials_exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise credentials_exc
    if int(getattr(user, "token_version", 0) or 0) != token_ver:
        raise credentials_exc
    return user


def bump_token_version(user: User) -> int:
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    return user.token_version


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    return user_from_token(token, db, allow_media=False)


def require_roles(*roles: UserRole):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return _dep
