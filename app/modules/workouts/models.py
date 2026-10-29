from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.core.db import Base, UTCDateTime


class WeightUnit(StrEnum):
    KG = "kg"
    LB = "lb"


LB_TO_KG = 0.45359237


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 1440)",
            name="ck_workouts_duration",
        ),
        Index("ix_workouts_member_date", "member_id", "performed_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"))
    performed_on: Mapped[date] = mapped_column(Date)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="WorkoutSet.id",
    )


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        UniqueConstraint("workout_id", "exercise_id", "set_number", name="uq_sets_number"),
        CheckConstraint("set_number >= 1", name="ck_sets_number"),
        CheckConstraint("reps IS NULL OR reps >= 0", name="ck_sets_reps"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_sets_weight"),
        CheckConstraint("weight_unit IN ('kg','lb')", name="ck_sets_unit"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="ck_sets_duration"
        ),
        Index("ix_sets_exercise", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id", ondelete="CASCADE"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    set_number: Mapped[int] = mapped_column(Integer)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_unit: Mapped[str] = mapped_column(String(2), default=WeightUnit.KG)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    workout: Mapped[WorkoutSession] = relationship(back_populates="sets")
    exercise: Mapped[Exercise] = relationship()
