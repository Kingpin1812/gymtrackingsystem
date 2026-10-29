"""Admin command-line tasks.

  python -m app.cli create-admin --email you@example.com --name "Your Name"
  python -m app.cli seed-exercises
  python -m app.cli seed-demo        # synthetic demo data - development only
  python -m app.cli backup-db        # copy the SQLite file to data/backups/
"""

import argparse
import getpass
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.clock import gym_today, utcnow
from app.core.config import PROJECT_ROOT, get_settings
from app.core.db import Database
from app.core.errors import AppError
from app.core.security import MIN_PASSWORD_LENGTH
from app.modules.auth import service as auth_service
from app.modules.auth.models import Role, User
from app.modules.auth.schemas import clean_name, normalize_email
from app.modules.members import service as members_service
from app.modules.workouts.models import Exercise

DEFAULT_EXERCISES = [
    ("Back Squat", "legs"),
    ("Deadlift", "back"),
    ("Bench Press", "chest"),
    ("Overhead Press", "shoulders"),
    ("Barbell Row", "back"),
    ("Pull-up", "back"),
    ("Push-up", "chest"),
    ("Lunge", "legs"),
    ("Leg Press", "legs"),
    ("Bicep Curl", "arms"),
    ("Tricep Extension", "arms"),
    ("Plank", "core"),
    ("Treadmill Run", "cardio"),
    ("Rowing Machine", "cardio"),
    ("Cycling", "cardio"),
]


def _db() -> Session:
    return Database(get_settings().database_url).session_factory()


def create_admin(email: str, name: str) -> None:
    email, name = normalize_email(email), clean_name(name)
    password = getpass.getpass("Password for the new admin: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    with _db() as db:
        auth_service.create_user(
            db, email=email, full_name=name, role=Role.ADMIN, password=password
        )
        db.commit()
    print(f"Admin {email} created.")


def seed_exercises() -> int:
    with _db() as db:
        existing = {n.lower() for n in db.scalars(select(Exercise.name))}
        added = 0
        for name, category in DEFAULT_EXERCISES:
            if name.lower() not in existing:
                db.add(Exercise(name=name, category=category))
                added += 1
        db.commit()
    print(f"Added {added} exercises.")
    return added


def seed_demo() -> None:
    """Create clearly fake demo accounts. Refuses to run if any users already exist."""
    with _db() as db:
        if db.scalar(select(User.id).limit(1)):
            sys.exit("Database already has users; refusing to add demo data.")
    seed_exercises()
    demo_password = "demo-password-123"
    with _db() as db:
        auth_service.create_user(
            db, email="admin@example.com", full_name="Demo Admin", role=Role.ADMIN,
            password=demo_password,
        )
        trainer = auth_service.create_user(
            db, email="trainer@example.com", full_name="Demo Trainer", role=Role.TRAINER,
            password=demo_password,
        )
        db.commit()
        monthly = members_service.create_plan(
            db, name="Monthly", description="30 days", duration_days=30, price_cents=150000
        )
        members_service.create_plan(
            db, name="Annual", description="365 days", duration_days=365, price_cents=1500000
        )
        alex = members_service.create_member(
            db, full_name="Alex Demo", email="member@example.com", phone=None,
            assigned_trainer_id=trainer.id, password=demo_password,
        )
        members_service.add_membership(db, alex, monthly.id, gym_today() - timedelta(days=3))
        sam = members_service.create_member(
            db, full_name="Sam Sample", email=None, phone="+91 90000 00000",
            assigned_trainer_id=None, password=None,
        )
        members_service.add_membership(db, sam, monthly.id, gym_today() - timedelta(days=40))
    print("Demo data created (synthetic). Logins, all with password", repr(demo_password) + ":")
    print("  admin@example.com / trainer@example.com / member@example.com")
    print("Sam Sample has an expired membership, to demonstrate check-in rejection.")


def backup_db() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        sys.exit("backup-db only supports SQLite. Use your database's own backup tool.")
    source = Path(url.removeprefix("sqlite:///"))
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.exists():
        sys.exit(f"No database file at {source}")
    target_dir = PROJECT_ROOT / "data" / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}-{utcnow():%Y%m%dT%H%M%SZ}.db"
    # sqlite3's backup API gives a consistent copy even if the app is running.
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    print(f"Backup written to {target}")
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    sub.add_parser("seed-exercises")
    sub.add_parser("seed-demo")
    sub.add_parser("backup-db")
    args = parser.parse_args(argv)
    try:
        if args.command == "create-admin":
            create_admin(args.email, args.name)
        elif args.command == "seed-exercises":
            seed_exercises()
        elif args.command == "seed-demo":
            seed_demo()
        elif args.command == "backup-db":
            backup_db()
    except (AppError, ValueError) as exc:
        sys.exit(f"Error: {getattr(exc, 'message', exc)}")


if __name__ == "__main__":
    main()
