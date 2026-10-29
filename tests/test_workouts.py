import pytest

from tests.conftest import make_member


def _workout(exercises, **overrides):
    body = {
        "performed_on": "2026-03-09",
        "duration_minutes": 45,
        "notes": "Felt good",
        "sets": [
            {"exercise_id": exercises["Back Squat"], "reps": 5, "weight": 100},
            {"exercise_id": exercises["Back Squat"], "reps": 5, "weight": 105},
            {"exercise_id": exercises["Plank"], "duration_seconds": 60},
        ],
    }
    body.update(overrides)
    return body


def test_member_logs_and_lists_own_workout(client, alice, alice_h, exercises):
    r = client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises),
                    headers=alice_h)
    assert r.status_code == 201, r.text
    sets = r.json()["sets"]
    assert [(s["exercise_name"], s["set_number"]) for s in sets] == [
        ("Back Squat", 1), ("Back Squat", 2), ("Plank", 1)
    ]
    listed = client.get(f"/api/members/{alice['id']}/workouts", headers=alice_h).json()
    assert listed["total"] == 1


def test_member_cannot_touch_other_members_workouts(client, alice, bob, alice_h, bob_h,
                                                     exercises):
    w = client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises),
                    headers=alice_h).json()
    assert client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises),
                       headers=bob_h).status_code == 404
    assert client.get(f"/api/members/{alice['id']}/workouts", headers=bob_h).status_code == 404
    assert client.get(f"/api/workouts/{w['id']}", headers=bob_h).status_code == 404
    assert client.put(f"/api/workouts/{w['id']}", json=_workout(exercises),
                      headers=bob_h).status_code == 404
    assert client.delete(f"/api/workouts/{w['id']}", headers=bob_h).status_code == 404
    assert client.get(f"/api/members/{alice['id']}/progress",
                      params={"exercise_id": exercises["Back Squat"]},
                      headers=bob_h).status_code == 404


def test_assigned_trainer_access_only(client, alice, bob, trainer_h, trainer2_h, exercises):
    assert client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises),
                       headers=trainer_h).status_code == 201
    assert client.post(f"/api/members/{bob['id']}/workouts", json=_workout(exercises),
                       headers=trainer_h).status_code == 404
    assert client.get(f"/api/members/{alice['id']}/workouts",
                      headers=trainer2_h).status_code == 404


@pytest.mark.parametrize(
    "override",
    [
        {"performed_on": "2026-03-11"},  # future in gym time zone
        {"performed_on": "1999-12-31"},
        {"sets": []},
        {"duration_minutes": 0},
        {"sets": [{"exercise_id": 1, "reps": -1}]},
        {"sets": [{"exercise_id": 1, "reps": 5, "weight": 5000}]},
        {"sets": [{"exercise_id": 1, "reps": 5, "weight_unit": "stone"}]},
        {"sets": [{"exercise_id": 1}]},  # no reps or duration
        {"sets": [{"exercise_id": 999, "reps": 5}]},  # unknown exercise
    ],
)
def test_invalid_workouts_rejected(client, alice, alice_h, exercises, override):
    r = client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises, **override),
                    headers=alice_h)
    assert r.status_code == 422, override


def test_replace_and_delete_workout(client, alice, alice_h, exercises):
    w = client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises),
                    headers=alice_h).json()
    new = _workout(exercises, sets=[{"exercise_id": exercises["Plank"], "duration_seconds": 90}])
    r = client.put(f"/api/workouts/{w['id']}", json=new, headers=alice_h)
    assert r.status_code == 200 and len(r.json()["sets"]) == 1
    assert client.delete(f"/api/workouts/{w['id']}", headers=alice_h).status_code == 204
    assert client.get(f"/api/workouts/{w['id']}", headers=alice_h).status_code == 404


def test_progress_converts_units_and_finds_best(client, alice, alice_h, exercises):
    sq = exercises["Back Squat"]
    client.post(f"/api/members/{alice['id']}/workouts", headers=alice_h, json=_workout(
        exercises, performed_on="2026-03-01",
        sets=[{"exercise_id": sq, "reps": 5, "weight": 100}]))
    client.post(f"/api/members/{alice['id']}/workouts", headers=alice_h, json=_workout(
        exercises, performed_on="2026-03-08",
        sets=[{"exercise_id": sq, "reps": 3, "weight": 250, "weight_unit": "lb"},
              {"exercise_id": sq, "reps": 5, "weight": 100}]))
    p = client.get(f"/api/members/{alice['id']}/progress", params={"exercise_id": sq},
                   headers=alice_h).json()
    assert [pt["performed_on"] for pt in p["points"]] == ["2026-03-01", "2026-03-08"]
    assert p["points"][0]["volume_kg"] == 500.0
    assert p["points"][1]["max_weight_kg"] == pytest.approx(113.4, abs=0.01)
    assert p["best_weight_kg"] == pytest.approx(113.4, abs=0.01)
    assert "not medical" in p["disclaimer"]


def test_inactive_member_cannot_log(client, admin_h, alice, exercises):
    client.post(f"/api/members/{alice['id']}/deactivate", headers=admin_h)
    r = client.post(f"/api/members/{alice['id']}/workouts", json=_workout(exercises),
                    headers=admin_h)
    assert r.status_code == 409


def test_exercises_listing_and_creation(client, admin_h, trainer_h, alice_h, exercises):
    assert len(client.get("/api/exercises", headers=alice_h).json()) == 2
    assert client.post("/api/exercises", json={"name": "Deadlift", "category": "back"},
                       headers=alice_h).status_code == 403
    assert client.post("/api/exercises", json={"name": "Deadlift", "category": "back"},
                       headers=trainer_h).status_code == 201
    assert client.post("/api/exercises", json={"name": "deadlift", "category": "back"},
                       headers=admin_h).status_code == 409


def test_member_without_login_workouts_by_admin(client, admin_h, exercises):
    m = make_member(client, admin_h, "No Login")
    r = client.post(f"/api/members/{m['id']}/workouts", json=_workout(exercises),
                    headers=admin_h)
    assert r.status_code == 201
