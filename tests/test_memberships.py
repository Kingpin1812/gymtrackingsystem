from datetime import UTC, date, datetime

from app.core import clock
from app.modules.members.models import Membership
from app.modules.members.service import effective_status
from tests.conftest import make_member


def _add(client, admin_h, member_id, plan_id, start):
    return client.post(f"/api/members/{member_id}/memberships",
                       json={"plan_id": plan_id, "start_date": start}, headers=admin_h)


def test_end_date_is_inclusive(client, admin_h, plan):
    m = make_member(client, admin_h, "Dates")
    r = _add(client, admin_h, m["id"], plan["id"], "2026-03-01")
    assert r.status_code == 201
    # 30-day plan starting Mar 1 covers Mar 1..Mar 30 inclusive.
    assert r.json()["end_date"] == "2026-03-30"
    assert r.json()["status"] == "active"


def test_default_start_is_gym_today(client, admin_h, plan):
    # 2026-03-09 20:00 UTC is already 2026-03-10 01:30 in Asia/Kolkata.
    clock.freeze(datetime(2026, 3, 9, 20, 0, tzinfo=UTC))
    m = make_member(client, admin_h, "Late Night")
    r = client.post(f"/api/members/{m['id']}/memberships", json={"plan_id": plan["id"]},
                    headers=admin_h)
    assert r.json()["start_date"] == "2026-03-10"


def test_effective_status_rules():
    m = Membership(start_date=date(2026, 3, 1), end_date=date(2026, 3, 30), status="active")
    assert effective_status(m, date(2026, 2, 28)) == "scheduled"
    assert effective_status(m, date(2026, 3, 1)) == "active"
    assert effective_status(m, date(2026, 3, 30)) == "active"
    assert effective_status(m, date(2026, 3, 31)) == "expired"
    m.status = "suspended"
    assert effective_status(m, date(2026, 3, 10)) == "suspended"


def test_overlapping_memberships_rejected(client, admin_h, plan):
    m = make_member(client, admin_h, "Overlap")
    assert _add(client, admin_h, m["id"], plan["id"], "2026-03-01").status_code == 201
    r = _add(client, admin_h, m["id"], plan["id"], "2026-03-30")  # touches last day
    assert r.status_code == 409 and r.json()["error"]["code"] == "membership_overlap"
    # Back-to-back renewal is fine.
    assert _add(client, admin_h, m["id"], plan["id"], "2026-03-31").status_code == 201


def test_cancelled_membership_frees_dates(client, admin_h, plan):
    m = make_member(client, admin_h, "Cancel")
    ms = _add(client, admin_h, m["id"], plan["id"], "2026-03-01").json()
    client.post(f"/api/memberships/{ms['id']}/cancel", headers=admin_h)
    assert _add(client, admin_h, m["id"], plan["id"], "2026-03-05").status_code == 201


def test_state_transitions(client, admin_h, plan):
    m = make_member(client, admin_h, "States")
    ms = _add(client, admin_h, m["id"], plan["id"], "2026-03-01").json()
    base = f"/api/memberships/{ms['id']}"
    assert client.post(f"{base}/suspend", headers=admin_h).json()["status"] == "suspended"
    assert client.post(f"{base}/suspend", headers=admin_h).status_code == 409
    assert client.post(f"{base}/resume", headers=admin_h).json()["status"] == "active"
    assert client.post(f"{base}/cancel", headers=admin_h).json()["status"] == "cancelled"
    r = client.post(f"{base}/resume", headers=admin_h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


def test_inactive_plan_cannot_be_sold(client, admin_h, plan):
    client.patch(f"/api/plans/{plan['id']}", json={"is_active": False}, headers=admin_h)
    m = make_member(client, admin_h, "No Plan")
    r = _add(client, admin_h, m["id"], plan["id"], "2026-03-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_plan"


def test_plans_admin_only_and_validated(client, admin_h, trainer_h):
    assert client.post("/api/plans", json={"name": "X", "duration_days": 1},
                       headers=trainer_h).status_code == 403
    assert client.post("/api/plans", json={"name": "Zero", "duration_days": 0},
                       headers=admin_h).status_code == 422
    assert client.post("/api/plans", json={"name": "Neg", "duration_days": 5, "price_cents": -1},
                       headers=admin_h).status_code == 422


def test_member_profile_shows_current_membership(client, alice, alice_h):
    cm = client.get("/api/members/me", headers=alice_h).json()["current_membership"]
    assert cm["status"] == "active" and cm["plan_name"] == "Monthly"
