"""Test fixtures. Every test gets a fresh, disposable SQLite file and synthetic users."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core import clock
from app.core.config import get_settings
from app.main import create_app
from app.models import Base
from app.modules.auth import service as auth_service
from app.modules.auth.models import Role
from app.modules.workouts.models import Exercise

PASSWORD = "correct-horse-battery"
# 10:00 in Asia/Kolkata on 2026-03-10.
NOW = datetime(2026, 3, 10, 4, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock():
    clock.freeze(NOW)
    yield
    clock.freeze(None)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("GYMTRACK_TIMEZONE", "Asia/Kolkata")
    get_settings.cache_clear()
    base = get_settings()
    yield replace(
        base,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        timezone="Asia/Kolkata",
        stale_session_hours=4,
        checkout_dedupe_seconds=120,
        login_max_attempts=5,
    )
    get_settings.cache_clear()


@pytest.fixture
def app(settings):
    application = create_app(settings)
    Base.metadata.create_all(application.state.db.engine)
    yield application
    application.state.db.engine.dispose()


@pytest.fixture
def db(app):
    with app.state.db.session_factory() as session:
        yield session


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(client, email, password=PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def users(db):
    created = {}
    for key, role in [
        ("admin", Role.ADMIN),
        ("trainer", Role.TRAINER),
        ("trainer2", Role.TRAINER),
    ]:
        created[key] = auth_service.create_user(
            db, email=f"{key}@example.test", full_name=key.title(), role=role, password=PASSWORD
        )
    db.commit()
    return created


@pytest.fixture
def admin_h(client, users):
    return login(client, "admin@example.test")


@pytest.fixture
def trainer_h(client, users):
    return login(client, "trainer@example.test")


@pytest.fixture
def trainer2_h(client, users):
    return login(client, "trainer2@example.test")


@pytest.fixture
def plan(client, admin_h):
    r = client.post(
        "/api/plans", json={"name": "Monthly", "duration_days": 30, "price_cents": 1000},
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_member(client, admin_h, name, *, email=None, password=None, trainer_id=None):
    body = {"full_name": name, "email": email, "password": password,
            "assigned_trainer_id": trainer_id}
    r = client.post("/api/members", json=body, headers=admin_h)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def alice(client, admin_h, users, plan):
    """Active member with a login, assigned to `trainer`, membership valid today."""
    m = make_member(client, admin_h, "Alice Example", email="alice@example.test",
                    password=PASSWORD, trainer_id=users["trainer"].id)
    r = client.post(f"/api/members/{m['id']}/memberships",
                    json={"plan_id": plan["id"], "start_date": "2026-03-01"}, headers=admin_h)
    assert r.status_code == 201, r.text
    return m


@pytest.fixture
def bob(client, admin_h, users, plan):
    """Active member with a login, not assigned to any trainer, membership valid today."""
    m = make_member(client, admin_h, "Bob Example", email="bob@example.test", password=PASSWORD)
    r = client.post(f"/api/members/{m['id']}/memberships",
                    json={"plan_id": plan["id"], "start_date": "2026-03-01"}, headers=admin_h)
    assert r.status_code == 201, r.text
    return m


@pytest.fixture
def alice_h(client, alice):
    return login(client, "alice@example.test")


@pytest.fixture
def bob_h(client, bob):
    return login(client, "bob@example.test")


def qr_token(client, admin_h, member_id) -> str:
    return client.get(f"/api/members/{member_id}/qr-token", headers=admin_h).json()["qr_token"]


@pytest.fixture
def exercises(db):
    items = [Exercise(name="Back Squat", category="legs"), Exercise(name="Plank", category="core")]
    db.add_all(items)
    db.commit()
    return {e.name: e.id for e in items}
