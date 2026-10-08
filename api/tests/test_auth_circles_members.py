from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.deps import LOCAL_ISSUER

from .conftest import API, login, make_circle


# ------------------------------------------------------------------ health & auth


async def test_health(client):
    r = await client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["mock_providers"] is True


async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200 and r.json()["docs"] == "/docs"


async def test_auth_config(client):
    r = await client.get(f"{API}/auth/config")
    assert r.json() == {"auth_mode": "local", "mock_providers": True, "demo_mode": True}


async def test_dev_login_creates_and_reuses_user(client):
    r1 = await client.post(f"{API}/auth/dev-login", json={"email": "A@Example.com", "full_name": "Alex"})
    r2 = await client.post(f"{API}/auth/dev-login", json={"email": "a@example.com"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["user"]["id"] == r2.json()["user"]["id"]
    assert r1.json()["user"]["email"] == "a@example.com"
    assert r1.json()["token_type"] == "bearer"


async def test_dev_login_invalid_email(client):
    r = await client.post(f"{API}/auth/dev-login", json={"email": "not-an-email"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_dev_login_disabled_in_supabase_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "supabase")
    r = await client.post(f"{API}/auth/dev-login", json={"email": "a@example.com"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "disabled"


async def test_me_requires_token(client):
    r = await client.get(f"{API}/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_me_rejects_bad_token(client):
    r = await client.get(f"{API}/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"


async def test_me_rejects_expired_token(client):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    tok = jwt.encode(
        {"sub": "u1", "email": "x@y.com", "aud": "authenticated", "iss": LOCAL_ISSUER, "exp": past},
        settings.LOCAL_JWT_SECRET, algorithm="HS256",
    )
    r = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


async def test_supabase_hs256_token_accepted(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "supabase-test-secret-which-is-long-enough")
    tok = jwt.encode(
        {"sub": "sb-user-1", "email": "sb@example.com", "aud": "authenticated",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "supabase-test-secret-which-is-long-enough", algorithm="HS256",
    )
    r = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["email"] == "sb@example.com"


async def test_me_lists_circles(client, auth):
    await make_circle(client, auth, enroll=False)
    r = await client.get(f"{API}/me", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alex@example.com"
    assert [c["role"] for c in body["circles"]] == ["owner"]


# ------------------------------------------------------------------ circles


async def test_create_circle_adds_me_as_trusted_contact(client, auth):
    r = await client.post(f"{API}/circles", json={"name": "Mum's Circle", "my_relationship": "son"}, headers=auth)
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "Mum's Circle"
    assert len(c["members"]) == 1
    assert c["members"][0]["role"] == "trusted_contact"
    assert c["members"][0]["relationship"] == "son"
    assert c["stats"]["voices_enrolled"] == 0


async def test_create_circle_validation(client, auth):
    r = await client.post(f"{API}/circles", json={"name": ""}, headers=auth)
    assert r.status_code == 422
    r = await client.post(f"{API}/circles", json={"name": "X", "my_phone_e164": "0801234"}, headers=auth)
    assert r.status_code == 422 and "E.164" in r.json()["error"]["message"]


async def test_list_and_get_circle(client, auth):
    data = await make_circle(client, auth)
    r = await client.get(f"{API}/circles", headers=auth)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.get(f"{API}/circles/{data['circle']['id']}", headers=auth)
    assert r.status_code == 200
    c = r.json()
    assert c["members"][0]["role"] == "senior"  # seniors listed first
    assert c["stats"]["voices_enrolled"] == 1


async def test_get_circle_404_and_403(client, auth, other_auth):
    r = await client.get(f"{API}/circles/nope", headers=auth)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    data = await make_circle(client, auth, enroll=False)
    r = await client.get(f"{API}/circles/{data['circle']['id']}", headers=other_auth)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


async def test_rename_circle(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.patch(f"{API}/circles/{data['circle']['id']}", json={"name": "Ada's Team"}, headers=auth)
    assert r.status_code == 200 and r.json()["name"] == "Ada's Team"


async def test_delete_circle(client, auth, other_auth):
    data = await make_circle(client, auth)
    cid = data["circle"]["id"]
    r = await client.delete(f"{API}/circles/{cid}", headers=other_auth)
    assert r.status_code == 403
    r = await client.delete(f"{API}/circles/{cid}", headers=auth)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (await client.get(f"{API}/circles/{cid}", headers=auth)).status_code == 404


# ------------------------------------------------------------------ members


async def test_add_senior_requires_phone(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/members", json={"role": "senior", "display_name": "Grandpa"}, headers=auth
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "phone_required"


async def test_add_member_validation(client, auth):
    data = await make_circle(client, auth, enroll=False)
    url = f"{API}/circles/{data['circle']['id']}/members"
    bad = [
        {"role": "boss", "display_name": "X"},
        {"role": "trusted_contact", "display_name": "X", "phone_e164": "12345"},
        {"role": "trusted_contact", "display_name": "X", "timezone": "Mars/Base"},
        {"role": "senior", "display_name": "X", "phone_e164": "+2348011111111", "companion_call_time": "25:00"},
        {"role": "trusted_contact", "display_name": ""},
    ]
    for body in bad:
        r = await client.post(url, json=body, headers=auth)
        assert r.status_code == 422, body


async def test_add_trusted_contact_and_link_to_me_conflict(client, auth):
    data = await make_circle(client, auth, enroll=False)
    url = f"{API}/circles/{data['circle']['id']}/members"
    r = await client.post(url, json={"role": "trusted_contact", "display_name": "Chioma", "relationship": "daughter"}, headers=auth)
    assert r.status_code == 201 and r.json()["user_id"] is None and r.json()["voice_status"] == "none"
    r = await client.post(url, json={"role": "trusted_contact", "display_name": "Me again", "link_to_me": True}, headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_member"


async def test_add_member_forbidden_for_non_member(client, auth, other_auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/members", json={"role": "trusted_contact", "display_name": "X"}, headers=other_auth
    )
    assert r.status_code == 403


async def test_get_and_update_member(client, auth):
    data = await make_circle(client, auth, enroll=False)
    sid = data["senior"]["id"]
    r = await client.get(f"{API}/members/{sid}", headers=auth)
    assert r.status_code == 200 and r.json()["display_name"] == "Grandma Ada"
    r = await client.patch(
        f"{API}/members/{sid}",
        json={"companion_enabled": True, "companion_call_time": "09:30", "personal_facts": ["cat Biscuit"], "relationship": "nana"},
        headers=auth,
    )
    assert r.status_code == 200
    m = r.json()
    assert m["companion_enabled"] and m["companion_call_time"] == "09:30"
    assert m["personal_facts"] == ["cat Biscuit"] and m["relationship"] == "nana"


async def test_update_member_rules(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.patch(f"{API}/members/{data['contact']['id']}", json={"companion_enabled": True}, headers=auth)
    assert r.status_code == 400
    r = await client.patch(f"{API}/members/{data['senior']['id']}", json={"phone_e164": None}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "phone_required"
    r = await client.patch(f"{API}/members/{data['senior']['id']}", json={"timezone": "Nowhere/Land"}, headers=auth)
    assert r.status_code == 422
    r = await client.patch(f"{API}/members/missing", json={"display_name": "x"}, headers=auth)
    assert r.status_code == 404


async def test_delete_member(client, auth, other_auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/members", json={"role": "trusted_contact", "display_name": "Tmp"}, headers=auth
    )
    mid = r.json()["id"]
    assert (await client.delete(f"{API}/members/{mid}", headers=other_auth)).status_code == 403
    r = await client.delete(f"{API}/members/{mid}", headers=auth)
    assert r.status_code == 200
    assert (await client.get(f"{API}/members/{mid}", headers=auth)).status_code == 404


async def test_member_access_is_scoped(client, auth):
    data = await make_circle(client, auth, enroll=False)
    other = await login(client, "x@example.com")
    r = await client.get(f"{API}/members/{data['senior']['id']}", headers=other)
    assert r.status_code == 403
