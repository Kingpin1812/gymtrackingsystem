"""Imports every module's models so Base.metadata is complete (used by Alembic and tests)."""

from app.core.db import Base
from app.modules.attendance.models import AttendanceSession
from app.modules.auth.models import AuthSession, User
from app.modules.members.models import Member, Membership, MembershipPlan
from app.modules.workouts.models import Exercise, WorkoutSession, WorkoutSet

__all__ = [
    "Base",
    "AttendanceSession",
    "AuthSession",
    "User",
    "Member",
    "Membership",
    "MembershipPlan",
    "Exercise",
    "WorkoutSession",
    "WorkoutSet",
]
