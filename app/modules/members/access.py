"""Who may see or act on a member's records. Shared by members, attendance and workouts.

Rule: admins see everyone; trainers see members assigned to them; members see only themselves.
A caller without access gets 404 (not 403) so record IDs cannot be probed.
"""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.auth.models import Role, User
from app.modules.members.models import Member


def can_access_member(user: User, member: Member) -> bool:
    if user.role == Role.ADMIN:
        return True
    if user.role == Role.TRAINER:
        return member.assigned_trainer_id == user.id
    return member.user_id is not None and member.user_id == user.id


def get_accessible_member(db: Session, user: User, member_id: int) -> Member:
    member = db.get(Member, member_id)
    if member is None or not can_access_member(user, member):
        raise NotFound("Member not found")
    return member


def scope_members_query(stmt: Select, user: User) -> Select:
    """Restrict a query over Member to the rows the user may see."""
    if user.role == Role.ADMIN:
        return stmt
    if user.role == Role.TRAINER:
        return stmt.where(Member.assigned_trainer_id == user.id)
    return stmt.where(Member.user_id == user.id)


def member_for_user(db: Session, user: User) -> Member:
    member = db.scalar(select(Member).where(Member.user_id == user.id))
    if member is None:
        raise NotFound("No member profile is linked to this account")
    return member
