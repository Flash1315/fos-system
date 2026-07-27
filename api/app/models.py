import enum
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, Enum, Text, Boolean, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    employee = "employee"


class RecordKind(str, enum.Enum):
    expense = "expense"
    fuel = "fuel"
    income = "income"


class RecordStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="IDR")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    records: Mapped[list["MoneyRecord"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_org_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.employee)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    organization: Mapped[Organization] = relationship(back_populates="users")
    records: Mapped[list["MoneyRecord"]] = relationship(
        back_populates="created_by_user",
        foreign_keys="MoneyRecord.created_by",
    )


class MoneyRecord(Base):
    """Unified expense / fuel / income row."""
    __tablename__ = "money_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[RecordKind] = mapped_column(Enum(RecordKind), nullable=False)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.pending)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="IDR")
    category: Mapped[str] = mapped_column(String(120), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    photo_url: Mapped[str] = mapped_column(String(500), default="")
    # fuel extras
    liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    odometer: Mapped[float | None] = mapped_column(Float, nullable=True)
    # income extras
    client_name: Mapped[str] = mapped_column(String(200), default="")
    payment_method: Mapped[str] = mapped_column(String(40), default="")  # cash / transfer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="records")
    created_by_user: Mapped[User] = relationship(
        back_populates="records", foreign_keys=[created_by],
    )
