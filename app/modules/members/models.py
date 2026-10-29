from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.core.db import Base, UTCDateTime


class MemberStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MembershipStatus(StrEnum):
    """Stored states. "expired" is never stored; it is derived from end_date (see service)."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="ck_members_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Optional login account (role=member). Walk-in members may have none.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=MemberStatus.ACTIVE)
    assigned_trainer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Opaque, revocable identifier encoded in the member's QR code. Contains no personal data.
    qr_token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="member", order_by="Membership.start_date.desc()"
    )


class MembershipPlan(Base):
    __tablename__ = "membership_plans"
    __table_args__ = (
        CheckConstraint("duration_days > 0", name="ck_plans_duration"),
        CheckConstraint("price_cents >= 0", name="ck_plans_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_days: Mapped[int] = mapped_column(Integer)
    # Informational only - GymTrack does not process payments.
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_memberships_dates"),
        CheckConstraint(
            "status IN ('active','suspended','cancelled')", name="ck_memberships_status"
        ),
        Index("ix_memberships_member_dates", "member_id", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("membership_plans.id", ondelete="RESTRICT"))
    # Calendar dates in the gym's time zone, inclusive on both ends.
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=MembershipStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    member: Mapped[Member] = relationship(back_populates="memberships")
    plan: Mapped[MembershipPlan] = relationship()
