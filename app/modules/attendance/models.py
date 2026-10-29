from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime


class CloseReason(StrEnum):
    CHECKED_OUT = "checked_out"
    # Closed automatically because the member never checked out; check_out_at stays NULL
    # because the real departure time is unknown.
    STALE = "stale"
    # Closed because the member was deactivated while checked in.
    MEMBER_DEACTIVATED = "member_deactivated"


class AttendanceSession(Base):
    """One visit. A session is open while closed_reason IS NULL."""

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        CheckConstraint(
            "closed_reason IS NULL OR "
            "closed_reason IN ('checked_out','stale','member_deactivated')",
            name="ck_attendance_closed_reason",
        ),
        CheckConstraint("method IN ('qr','manual')", name="ck_attendance_method"),
        CheckConstraint(
            "check_out_at IS NULL OR check_out_at >= check_in_at", name="ck_attendance_order"
        ),
        # At most one open session per member, enforced by the database.
        Index(
            "uq_attendance_one_open_per_member",
            "member_id",
            unique=True,
            sqlite_where=text("closed_reason IS NULL"),
            postgresql_where=text("closed_reason IS NULL"),
        ),
        Index("ix_attendance_member_check_in", "member_id", "check_in_at"),
        Index("ix_attendance_check_in", "check_in_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"))
    check_in_at: Mapped[datetime] = mapped_column(UTCDateTime)
    check_out_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    method: Mapped[str] = mapped_column(String(10))
    checked_in_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checked_out_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
