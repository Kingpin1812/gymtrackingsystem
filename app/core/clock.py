"""Single source of "now", so tests can control time."""

from datetime import UTC, date, datetime

from app.core.config import get_settings

_frozen: datetime | None = None


def utcnow() -> datetime:
    return _frozen if _frozen is not None else datetime.now(UTC)


def gym_today() -> date:
    """The current calendar date in the gym's configured time zone."""
    return utcnow().astimezone(get_settings().tz).date()


def freeze(at: datetime | None) -> None:
    """Testing helper: pin utcnow() to `at` (timezone-aware), or unpin with None."""
    global _frozen
    if at is not None and at.tzinfo is None:
        raise ValueError("freeze() needs a timezone-aware datetime")
    _frozen = at
