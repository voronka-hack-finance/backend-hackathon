from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    family_group_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    bank_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(64), nullable=False, default="card")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True, index=True)
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class AccountCategory(Base):
    __tablename__ = "account_categories"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_by_user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class CategoryLimit(Base):
    __tablename__ = "category_limits"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    category_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    owner_user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    period_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    owner_user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class UserDebt(Base):
    __tablename__ = "user_debts"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    debt_type: Mapped[str] = mapped_column(String(32), nullable=False)
    remaining_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    monthly_payment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    payment_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    overdue_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_file_id",
            "source_sheet",
            "source_row_number",
            name="uq_transactions_user_file_sheet_row",
        ),
        UniqueConstraint("user_id", "dedupe_key", name="uq_transactions_user_dedupe_key"),
    )

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    category_id: Mapped[PyUUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("account_categories.id"),
        nullable=True,
    )
    import_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    source_file_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    source_sheet: Mapped[str] = mapped_column(String(32), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    operation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    card_mask: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    operation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    operation_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    payment_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    cashback_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    category_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mcc: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bonus_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    investment_rounding_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    rounded_operation_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
