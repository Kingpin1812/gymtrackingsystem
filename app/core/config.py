"""Application settings, read from environment variables (and an optional .env file)."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from .env without overriding real environment variables."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int(name: str, default: int, minimum: int = 0) -> int:
    value = int(os.environ.get(name, default))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    timezone: str
    session_hours: int
    stale_session_hours: int
    checkout_dedupe_seconds: int
    login_max_attempts: int
    login_window_minutes: int
    log_level: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    default_db = (PROJECT_ROOT / "data" / "gymtrack.db").as_posix()
    settings = Settings(
        database_url=os.environ.get("GYMTRACK_DATABASE_URL", f"sqlite:///{default_db}"),
        timezone=os.environ.get("GYMTRACK_TIMEZONE", "UTC"),
        session_hours=_int("GYMTRACK_SESSION_HOURS", 12, minimum=1),
        stale_session_hours=_int("GYMTRACK_STALE_SESSION_HOURS", 4, minimum=1),
        checkout_dedupe_seconds=_int("GYMTRACK_CHECKOUT_DEDUPE_SECONDS", 120),
        login_max_attempts=_int("GYMTRACK_LOGIN_MAX_ATTEMPTS", 5, minimum=1),
        login_window_minutes=_int("GYMTRACK_LOGIN_WINDOW_MINUTES", 15, minimum=1),
        log_level=os.environ.get("GYMTRACK_LOG_LEVEL", "INFO").upper(),
    )
    ZoneInfo(settings.timezone)  # fail fast on an unknown time zone
    return settings


@lru_cache
def get_settings() -> Settings:
    return load_settings()
