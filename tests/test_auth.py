from datetime import timedelta

from app.core import clock
from tests.conftest import NOW, PASSWORD, login


def test_login_and_me(client, admin_h):
    r = client.get("/api/auth/me", headers=admin_h)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin"
    assert "password_hash" not in body


def test_login_email_is_case_insensitive(client, users):
    r = client.post("/api/auth/login",
                    json={"email": "  ADMIN@Example.test ", "password": PASSWORD})
    assert r.status_code == 200


def test_wrong_password_and_unknown_email_give_same_error(client, users):
    a = client.post("/api/auth/login", json={"email": "admin@example.test", "password": "nope"})
    b = client.post("/api/auth/login", json={"email": "ghost@example.test", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "invalid_credentials"


def test_login_rate_limited_after_repeated_failures(client, users):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "admin@example.test", "password": "bad"})
    r = client.post("/api/auth/login", json={"email": "admin@example.test", "password": PASSWORD})
    assert r.status_code == 429
    # The window slides: after it passes, login works again.
    clock.freeze(NOW + timedelta(minutes=16))
    r = client.post("/api/auth/login", json={"email": "admin@example.test", "password": PASSWORD})
    assert r.status_code == 200


def test_protected_endpoints_require_auth(client):
    for path in ["/api/auth/me", "/api/members", "/api/plans", "/api/attendance/occupancy"]:
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"


def test_garbage_token_rejected(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_logout_revokes_token(client, admin_h):
    assert client.post("/api/auth/logout", headers=admin_h).status_code == 204
    assert client.get("/api/auth/me", headers=admin_h).status_code == 401


def test_session_expires(client, admin_h, settings):
    clock.freeze(NOW + timedelta(hours=settings.session_hours, seconds=1))
    assert client.get("/api/auth/me", headers=admin_h).status_code == 401


def test_admin_creates_trainer_and_rejects_duplicate_email(client, admin_h):
    body = {"email": "new@example.test", "full_name": "New Trainer", "role": "trainer",
            "password": PASSWORD}
    assert client.post("/api/users", json=body, headers=admin_h).status_code == 201
    r = client.post("/api/users", json=body, headers=admin_h)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_short_password_rejected(client, admin_h):
    body = {"email": "x@example.test", "full_name": "X", "role": "trainer", "password": "short"}
    r = client.post("/api/users", json=body, headers=admin_h)
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "password"


def test_non_admin_cannot_manage_users(client, trainer_h, alice_h):
    for h in (trainer_h, alice_h):
        assert client.get("/api/users", headers=h).status_code == 403
        body = {"email": "x@example.test", "full_name": "X", "role": "admin",
                "password": PASSWORD}
        assert client.post("/api/users", json=body, headers=h).status_code == 403


def test_deactivating_user_revokes_sessions(client, admin_h, trainer_h, users):
    r = client.patch(f"/api/users/{users['trainer'].id}", json={"is_active": False},
                     headers=admin_h)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=trainer_h).status_code == 401
    r = client.post("/api/auth/login",
                    json={"email": "trainer@example.test", "password": PASSWORD})
    assert r.status_code == 401


def test_admin_cannot_deactivate_self(client, admin_h, users):
    r = client.patch(f"/api/users/{users['admin'].id}", json={"is_active": False},
                     headers=admin_h)
    assert r.status_code == 403


def test_change_password_signs_out_other_sessions(client, users):
    first = login(client, "trainer@example.test")
    second = login(client, "trainer@example.test")
    r = client.post("/api/auth/change-password", headers=first,
                    json={"current_password": PASSWORD, "new_password": "another-good-pass"})
    assert r.status_code == 204
    assert client.get("/api/auth/me", headers=first).status_code == 200
    assert client.get("/api/auth/me", headers=second).status_code == 401
    login(client, "trainer@example.test", "another-good-pass")


def test_security_headers_and_no_stack_traces(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_unexpected_error_is_generic(app, admin_h, monkeypatch):
    from fastapi.testclient import TestClient

    from app.modules.members import service

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(service, "list_plans", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/plans", headers=admin_h)
    assert r.status_code == 500
    assert "secret" not in r.text
    assert r.json()["error"]["code"] == "internal_error"
