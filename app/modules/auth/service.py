"""Authentication and user-account business rules."""

import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Forbidden, NotFound, TooManyRequests, Unauthenticated
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from app.modules.auth.models import AuthSession, Role, User


class LoginRateLimiter:
    """In-memory sliding window of failed logins per (email, client IP).

    Suitable for a single-process deployment. A multi-process deployment would need a shared
    store; that is deliberately deferred until there is a real need.
    """

    def __init__(self, max_attempts: int, window: timedelta):
        self.max_attempts = max_attempts
        self.window = window
        self._failures: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key, now: datetime) -> deque:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def check(self, key: tuple[str, str]) -> None:
        with self._lock:
            if len(self._prune(key, utcnow())) >= self.max_attempts:
                raise TooManyRequests("Too many failed login attempts. Try again later.")

    def record_failure(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._prune(key, utcnow()).append(utcnow())

    def reset(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._failures.pop(key, None)


def login(
    db: Session, settings: Settings, limiter: LoginRateLimiter, email: str, password: str, ip: str
) -> tuple[str, AuthSession, User]:
    key = (email, ip)
    limiter.check(key)
    user = db.scalar(select(User).where(User.email == email))
    # Always run one hash verification so response time does not reveal whether the email exists.
    ok = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not ok or not user.is_active:
        limiter.record_failure(key)
        raise Unauthenticated("Invalid email or password", code="invalid_credentials")
    limiter.reset(key)
    token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    db.commit()
    return token, session, user


def resolve_token(db: Session, token: str) -> User:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise Unauthenticated("Session is invalid or has expired")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Session is invalid or has expired")
    return user


def logout(db: Session, token: str) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    """Revoke every active session of a user. Caller commits."""
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def create_user(db: Session, *, email: str, full_name: str, role: Role, password: str) -> User:
    """Add a user to the session and flush. Caller commits."""
    if db.scalar(select(func.count()).select_from(User).where(User.email == email)):
        raise Conflict("A user with this email already exists", code="email_taken")
    user = User(
        email=email, full_name=full_name, role=role.value, password_hash=hash_password(password)
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("A user with this email already exists", code="email_taken") from exc
    return user


def list_users(db: Session, role: Role | None, limit: int, offset: int) -> tuple[list[User], int]:
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role.value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(User.full_name).limit(limit).offset(offset)).all()
    return list(items), total


def update_user(
    db: Session, actor: User, user_id: int, full_name: str | None, is_active: bool | None
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    if is_active is False and user.id == actor.id:
        raise Forbidden("You cannot deactivate your own account", code="self_deactivation")
    if full_name is not None:
        user.full_name = full_name
    if is_active is not None:
        user.is_active = is_active
        if not is_active:
            revoke_all_sessions(db, user.id)
    db.commit()
    return user


def change_password(db: Session, user: User, current: str, new: str, keep_token: str) -> None:
    if not verify_password(current, user.password_hash):
        raise Forbidden("Current password is incorrect", code="invalid_credentials")
    user.password_hash = hash_password(new)
    # Sign out every other session; keep the one making this request.
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.token_hash != hash_token(keep_token),
        )
        .values(revoked_at=utcnow())
    )
    db.commit()
