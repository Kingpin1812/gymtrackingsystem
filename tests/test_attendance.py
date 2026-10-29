from datetime import timedelta

from app.core import clock
from tests.conftest import NOW, login, make_member, qr_token


def _in(client, h, **body):
    return client.post("/api/attendance/check-in", json=body, headers=h)


def _out(client, h, **body):
    return client.post("/api/attendance/check-out", json=body, headers=h)


def test_qr_check_in_and_out(client, admin_h, trainer_h, alice):
    token = qr_token(client, admin_h, alice["id"])
    r = _in(client, trainer_h, qr_token=token)
    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "checked_in" and body["session"]["method"] == "qr"
    assert set(body["member"]) == {"id", "full_name"}  # minimal personal data
    clock.freeze(NOW + timedelta(hours=1))
    r = _out(client, trainer_h, qr_token=token).json()
    assert r["result"] == "checked_out" and r["session"]["closed_reason"] == "checked_out"


def test_duplicate_scan_is_idempotent(client, admin_h, alice):
    first = _in(client, admin_h, member_id=alice["id"]).json()
    second = _in(client, admin_h, member_id=alice["id"]).json()
    assert second["result"] == "already_checked_in"
    assert second["session"]["id"] == first["session"]["id"]


def test_repeated_check_out_within_window(client, admin_h, alice, settings):
    _in(client, admin_h, member_id=alice["id"])
    first = _out(client, admin_h, member_id=alice["id"]).json()
    retry = _out(client, admin_h, member_id=alice["id"]).json()
    assert retry["result"] == "already_checked_out"
    assert retry["session"]["id"] == first["session"]["id"]
    clock.freeze(NOW + timedelta(seconds=settings.checkout_dedupe_seconds + 1))
    r = _out(client, admin_h, member_id=alice["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_checked_in"


def test_check_out_without_check_in(client, admin_h, alice):
    r = _out(client, admin_h, member_id=alice["id"])
    assert r.status_code == 409


def test_invalid_membership_rejected(client, admin_h, plan):
    m = make_member(client, admin_h, "No Membership")
    r = _in(client, admin_h, member_id=m["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "membership_invalid"
    # Expired yesterday (Feb 8 .. Mar 9) -> rejected today (Mar 10).
    client.post(f"/api/members/{m['id']}/memberships",
                json={"plan_id": plan["id"], "start_date": "2026-02-08"}, headers=admin_h)
    assert _in(client, admin_h, member_id=m["id"]).status_code == 409


def test_suspended_membership_rejected(client, admin_h, alice):
    ms = client.get(f"/api/members/{alice['id']}/memberships", headers=admin_h).json()[0]
    client.post(f"/api/memberships/{ms['id']}/suspend", headers=admin_h)
    assert _in(client, admin_h, member_id=alice["id"]).status_code == 409


def test_inactive_member_rejected(client, admin_h, alice):
    client.post(f"/api/members/{alice['id']}/deactivate", headers=admin_h)
    r = _in(client, admin_h, member_id=alice["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "member_inactive"


def test_rotated_qr_no_longer_works(client, admin_h, alice):
    old = qr_token(client, admin_h, alice["id"])
    client.post(f"/api/members/{alice['id']}/qr/rotate", headers=admin_h)
    r = _in(client, admin_h, qr_token=old)
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_qr"


def test_lookup_requires_exactly_one_identifier(client, admin_h, alice):
    assert _in(client, admin_h).status_code == 422
    assert _in(client, admin_h, member_id=alice["id"], qr_token="x" * 20).status_code == 422


def test_members_cannot_check_in(client, alice, alice_h):
    assert _in(client, alice_h, member_id=alice["id"]).status_code == 403
    assert client.get("/api/attendance/occupancy", headers=alice_h).status_code == 403


def test_stale_session_closed_on_next_check_in(client, admin_h, alice):
    first = _in(client, admin_h, member_id=alice["id"]).json()
    clock.freeze(NOW + timedelta(hours=5))
    r = _in(client, admin_h, member_id=alice["id"]).json()
    assert r["result"] == "checked_in"
    assert r["closed_stale_session_id"] == first["session"]["id"]
    history = client.get("/api/attendance", params={"member_id": alice["id"]},
                         headers=admin_h).json()["items"]
    stale = next(s for s in history if s["id"] == first["session"]["id"])
    assert stale["closed_reason"] == "stale" and stale["check_out_at"] is None


def test_occupancy_excludes_stale_and_closed(client, admin_h, alice, bob):
    _in(client, admin_h, member_id=alice["id"])
    clock.freeze(NOW + timedelta(hours=3))
    _in(client, admin_h, member_id=bob["id"])
    occ = client.get("/api/attendance/occupancy", headers=admin_h).json()
    assert occ["estimated_count"] == 2 and occ["is_estimate"] is True
    clock.freeze(NOW + timedelta(hours=4, minutes=1))  # alice now stale
    occ = client.get("/api/attendance/occupancy", headers=admin_h).json()
    assert occ["estimated_count"] == 1 and occ["stale_open_sessions"] == 1
    _out(client, admin_h, member_id=bob["id"])
    assert client.get("/api/attendance/occupancy",
                      headers=admin_h).json()["estimated_count"] == 0


def test_close_stale_admin_only(client, admin_h, trainer_h, alice):
    _in(client, admin_h, member_id=alice["id"])
    clock.freeze(NOW + timedelta(hours=10))
    assert client.post("/api/attendance/close-stale", headers=trainer_h).status_code == 403
    assert client.post("/api/attendance/close-stale", headers=admin_h).json() == {"closed": 1}


def test_deactivation_closes_open_session(client, admin_h, alice):
    _in(client, admin_h, member_id=alice["id"])
    client.post(f"/api/members/{alice['id']}/deactivate", headers=admin_h)
    items = client.get("/api/attendance", params={"member_id": alice["id"]},
                       headers=admin_h).json()["items"]
    assert items[0]["closed_reason"] == "member_deactivated"


def test_history_scoping(client, admin_h, alice, bob, alice_h, trainer_h):
    _in(client, admin_h, member_id=alice["id"])
    _in(client, admin_h, member_id=bob["id"])
    assert client.get("/api/attendance", headers=admin_h).json()["total"] == 2
    mine = client.get("/api/attendance/me", headers=alice_h).json()
    assert mine["total"] == 1 and mine["items"][0]["member_id"] == alice["id"]
    # Unfiltered list for a member is scoped to themselves.
    assert client.get("/api/attendance", headers=alice_h).json()["total"] == 1
    assert client.get("/api/attendance", params={"member_id": bob["id"]},
                      headers=alice_h).status_code == 404
    # Trainer sees only assigned member (alice).
    assert client.get("/api/attendance", headers=trainer_h).json()["total"] == 1


def test_history_date_filter_uses_gym_time_zone(client, alice):
    # 2026-03-10 19:00 UTC == 2026-03-11 00:30 in Asia/Kolkata.
    clock.freeze(NOW.replace(hour=19))
    admin_h = login(client, "admin@example.test")  # earlier session has expired by now
    _in(client, admin_h, member_id=alice["id"])
    on_11 = client.get("/api/attendance",
                       params={"date_from": "2026-03-11", "date_to": "2026-03-11"},
                       headers=admin_h).json()
    on_10 = client.get("/api/attendance",
                       params={"date_from": "2026-03-10", "date_to": "2026-03-10"},
                       headers=admin_h).json()
    assert on_11["total"] == 1 and on_10["total"] == 0
    bad = client.get("/api/attendance", params={"date_from": "2026-03-12",
                                                "date_to": "2026-03-11"}, headers=admin_h)
    assert bad.status_code == 422
