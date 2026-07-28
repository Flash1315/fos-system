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
    purpose: Mapped[str] = mapped_column(String(80), default="")  # Rental / Lesson / Office / Other
    place: Mapped[str] = mapped_column(String(200), default="")
    bike: Mapped[str] = mapped_column(String(120), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    photo_url: Mapped[str] = mapped_column(String(500), default="")
    # fuel extras
    liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    odometer: Mapped[float | None] = mapped_column(Float, nullable=True)
    # income extras
    client_name: Mapped[str] = mapped_column(String(200), default="")
    payment_method: Mapped[str] = mapped_column(String(40), default="")  # cash / transfer
    # expense/fuel: who paid — inspired by RJ My pocket / Cash on hand
    payment_source: Mapped[str] = mapped_column(String(40), default="")  # my_pocket / cash_on_hand
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # When the money actually moved (may differ from created_at for late entries)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Manager void of an approved row (kept for audit; excluded from balances)
    is_voided: Mapped[bool] = mapped_column(Boolean, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Links paired transfer legs (sender expense + recipient income)
    transfer_group_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="records")
    created_by_user: Mapped[User] = relationship(
        back_populates="records", foreign_keys=[created_by],
    )


class PayoutKind(str, enum.Enum):
    expense_payout = "expense_payout"
    income_handover = "income_handover"


class Payout(Base):
    """Manager settlement rows — RJ Expense payout / Income handover."""
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[PayoutKind] = mapped_column(Enum(PayoutKind), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="IDR")
    payment_method: Mapped[str] = mapped_column(String(40), default="cash")  # cash / transfer
    note: Mapped[str] = mapped_column(Text, default="")
    # RJ-style: amount paid above current spendings reduces next-cycle owed
    overpayment: Mapped[float] = mapped_column(Float, default=0.0)
    # Unpaid remainder after a partial settlement (carry into next cycle)
    balance_after: Mapped[float] = mapped_column(Float, default=0.0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_voided: Mapped[bool] = mapped_column(Boolean, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    void_note: Mapped[str] = mapped_column(Text, default="")


class SettlementRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    cancelled = "cancelled"


class SettlementRequest(Base):
    """Employee asks manager to settle (expense payout or income handover)."""
    __tablename__ = "settlement_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[PayoutKind] = mapped_column(Enum(PayoutKind), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[SettlementRequestStatus] = mapped_column(
        Enum(SettlementRequestStatus), default=SettlementRequestStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
