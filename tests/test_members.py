from tests.conftest import PASSWORD, login, make_member


def test_admin_creates_and_searches_members(client, admin_h):
    make_member(client, admin_h, "  Priya   Sharma ", email="Priya@Example.test")
    make_member(client, admin_h, "Rahul Verma")
    r = client.get("/api/members", params={"q": "priya"}, headers=admin_h)
    body = r.json()
    assert r.status_code == 200 and body["total"] == 1
    assert body["items"][0]["full_name"] == "Priya Sharma"  # whitespace normalised
    assert body["items"][0]["email"] == "priya@example.test"  # lower-cased


def test_pagination(client, admin_h):
    for i in range(5):
        make_member(client, admin_h, f"Member {i}")
    r = client.get("/api/members", params={"limit": 2, "offset": 2}, headers=admin_h).json()
    assert r["total"] == 5 and len(r["items"]) == 2 and r["offset"] == 2
    assert client.get("/api/members", params={"limit": 500}, headers=admin_h).status_code == 422


def test_member_input_validation(client, admin_h):
    cases = [
        {"full_name": "   "},
        {"full_name": "X", "email": "not-an-email"},
        {"full_name": "X", "phone": "call me maybe"},
        {"full_name": "X", "password": PASSWORD},  # login without email
    ]
    for body in cases:
        r = client.post("/api/members", json=body, headers=admin_h)
        assert r.status_code == 422, body


def test_duplicate_member_email_conflicts(client, admin_h):
    make_member(client, admin_h, "A", email="dup@example.test")
    r = client.post("/api/members", json={"full_name": "B", "email": "dup@example.test"},
                    headers=admin_h)
    assert r.status_code == 409


def test_assigned_trainer_must_be_trainer(client, admin_h, users):
    r = client.post("/api/members",
                    json={"full_name": "X", "assigned_trainer_id": users["admin"].id},
                    headers=admin_h)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_trainer"


def test_member_sees_only_self(client, alice, bob, alice_h):
    assert client.get("/api/members/me", headers=alice_h).json()["id"] == alice["id"]
    assert client.get(f"/api/members/{alice['id']}", headers=alice_h).status_code == 200
    # Another member's record looks like it does not exist (no ID probing).
    assert client.get(f"/api/members/{bob['id']}", headers=alice_h).status_code == 404
    assert client.get(f"/api/members/{bob['id']}/memberships",
                      headers=alice_h).status_code == 404
    assert client.get("/api/members", headers=alice_h).status_code == 403


def test_trainer_sees_only_assigned_members(client, alice, bob, trainer_h, trainer2_h):
    listed = client.get("/api/members", headers=trainer_h).json()
    assert [m["id"] for m in listed["items"]] == [alice["id"]]
    assert client.get(f"/api/members/{bob['id']}", headers=trainer_h).status_code == 404
    assert client.get("/api/members", headers=trainer2_h).json()["total"] == 0


def test_only_admin_can_modify_members(client, alice, trainer_h, alice_h):
    for h in (trainer_h, alice_h):
        assert client.patch(f"/api/members/{alice['id']}", json={"full_name": "Hacked"},
                            headers=h).status_code == 403
        assert client.post(f"/api/members/{alice['id']}/deactivate",
                           headers=h).status_code == 403
        assert client.post("/api/members", json={"full_name": "X"}, headers=h).status_code == 403


def test_update_member_syncs_login_email(client, admin_h, alice):
    r = client.patch(f"/api/members/{alice['id']}", json={"email": "alice.new@example.test"},
                     headers=admin_h)
    assert r.status_code == 200
    login(client, "alice.new@example.test")


def test_partial_update_leaves_other_fields(client, admin_h, alice):
    r = client.patch(f"/api/members/{alice['id']}", json={"phone": "+91 98765 43210"},
                     headers=admin_h).json()
    assert r["phone"] == "+91 98765 43210" and r["email"] == "alice@example.test"


def test_deactivate_blocks_login_and_keeps_history(client, admin_h, alice, alice_h):
    r = client.post(f"/api/members/{alice['id']}/deactivate", headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    assert client.get("/api/auth/me", headers=alice_h).status_code == 401
    memberships = client.get(f"/api/members/{alice['id']}/memberships", headers=admin_h).json()
    assert len(memberships) == 1  # history preserved
    # Reactivation restores login.
    client.post(f"/api/members/{alice['id']}/reactivate", headers=admin_h)
    login(client, "alice@example.test")


def test_create_login_for_walk_in_member(client, admin_h):
    m = make_member(client, admin_h, "Walk In")
    r = client.post(f"/api/members/{m['id']}/account", json={"password": PASSWORD},
                    headers=admin_h)
    assert r.status_code == 422  # no email yet
    client.patch(f"/api/members/{m['id']}", json={"email": "walkin@example.test"},
                 headers=admin_h)
    r = client.post(f"/api/members/{m['id']}/account", json={"password": PASSWORD},
                    headers=admin_h)
    assert r.status_code == 200 and r.json()["has_login"] is True
    login(client, "walkin@example.test")


def test_qr_visible_to_self_and_admin_only(client, admin_h, alice, alice_h, trainer_h, bob_h):
    assert client.get(f"/api/members/{alice['id']}/qr.svg", headers=alice_h).status_code == 200
    assert client.get(f"/api/members/{alice['id']}/qr.svg", headers=admin_h).status_code == 200
    # Even the assigned trainer cannot fetch (and so cannot impersonate) a member's QR.
    assert client.get(f"/api/members/{alice['id']}/qr.svg", headers=trainer_h).status_code == 404
    assert client.get(f"/api/members/{alice['id']}/qr.svg", headers=bob_h).status_code == 404


def test_qr_svg_is_standalone_image(client, alice, alice_h):
    r = client.get(f"/api/members/{alice['id']}/qr.svg", headers=alice_h)
    assert r.headers["content-type"].startswith("image/svg+xml")
    # Without xmlns, browsers refuse to render the SVG as an <img>.
    assert b'xmlns="http://www.w3.org/2000/svg"' in r.content


def test_qr_rotation_changes_token(client, admin_h, alice, alice_h):
    before = client.get(f"/api/members/{alice['id']}/qr-token", headers=alice_h).json()
    assert client.post(f"/api/members/{alice['id']}/qr/rotate",
                       headers=alice_h).status_code == 204
    after = client.get(f"/api/members/{alice['id']}/qr-token", headers=alice_h).json()
    assert before["qr_token"] != after["qr_token"]
    assert "alice" not in after["qr_token"].lower()
