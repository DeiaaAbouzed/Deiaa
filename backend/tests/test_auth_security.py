from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient

from rushd.db import utcnow
from rushd.main import create_app
from rushd.models import User, UserSession

from .conftest import PASSWORD, Api, add_user, make_settings


def test_login_sets_hardened_cookie_and_returns_csrf(app, ctx):
    add_user(ctx, "sara")
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": "Sara", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert response.json()["csrf"]
    assert response.json()["user"]["username"] == "sara"


def test_secure_cookie_uses_host_prefix(tmp_path, fake_claude):
    app = create_app(make_settings(tmp_path, cookie_secure=True), claude_client=fake_claude, start_background=False)
    add_user(app.state.ctx, "sara")
    client = TestClient(app, base_url="https://testserver")
    response = client.post("/api/auth/login", json={"username": "sara", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-rushd_session=") and "Secure" in cookie
    assert "strict-transport-security" in response.headers


def test_wrong_password_is_generic(app, ctx):
    add_user(ctx, "sara")
    client = TestClient(app)
    bad_user = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    bad_pass = client.post("/api/auth/login", json={"username": "sara", "password": "wrong"})
    assert bad_user.status_code == bad_pass.status_code == 401
    assert bad_user.json()["detail"] == bad_pass.json()["detail"]  # no username enumeration


def test_lockout_after_repeated_failures(app, ctx):
    add_user(ctx, "sara")
    client = TestClient(app)
    for _ in range(ctx.settings.login_max_failures):
        assert client.post("/api/auth/login", json={"username": "sara", "password": "wrong"}).status_code == 401
    locked = client.post("/api/auth/login", json={"username": "sara", "password": PASSWORD})
    assert locked.status_code == 423  # even the right password is refused while locked
    with ctx.sf() as db:
        db.query(User).filter_by(username="sara").update({"locked_until": utcnow() - timedelta(seconds=1)})
        db.commit()
    assert client.post("/api/auth/login", json={"username": "sara", "password": PASSWORD}).status_code == 200


def test_ip_rate_limit(tmp_path, fake_claude):
    app = create_app(
        make_settings(tmp_path, login_ip_limit_per_15min=3), claude_client=fake_claude, start_background=False
    )
    client = TestClient(app)
    codes = [client.post("/api/auth/login", json={"username": f"u{i}", "password": "x"}).status_code for i in range(4)]
    assert codes == [401, 401, 401, 429]


def test_csrf_and_origin_checks(app, login):
    api = login("sara")
    no_header = api.client.post("/api/auth/logout")
    assert no_header.status_code == 403 and no_header.json()["code"] == "csrf"
    cross = api.client.post("/api/auth/logout", headers={"X-CSRF-Token": api.csrf, "Origin": "https://evil.example"})
    assert cross.status_code == 403
    fetch_site = api.client.post("/api/auth/logout", headers={"X-CSRF-Token": api.csrf, "Sec-Fetch-Site": "cross-site"})
    assert fetch_site.status_code == 403
    assert api.post("/api/auth/logout").status_code == 200


def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/prescriptions").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_session(login):
    api = login("sara")
    assert api.get("/api/auth/me").status_code == 200
    api.post("/api/auth/logout")
    assert api.get("/api/auth/me").status_code == 401


def test_idle_timeout(ctx, login):
    api = login("sara")
    with ctx.sf() as db:
        db.query(UserSession).update(
            {"last_seen_at": utcnow() - timedelta(minutes=ctx.settings.session_idle_minutes + 1)}
        )
        db.commit()
    assert api.get("/api/auth/me").status_code == 401


def test_must_change_password_flow(app, ctx):
    add_user(ctx, "newbie", must_change_password=True)
    api = Api(app, "newbie")
    assert api.me["flags"]["must_change_password"] is True
    blocked = api.get("/api/prescriptions")
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"
    weak = api.post("/api/auth/password", json={"current": PASSWORD, "new": "123"})
    assert weak.status_code == 400
    ok = api.post("/api/auth/password", json={"current": PASSWORD, "new": "N3w!Secure-Pass"})
    assert ok.status_code == 200
    assert api.get("/api/prescriptions").status_code == 200


def test_password_change_revokes_other_sessions(app, ctx):
    add_user(ctx, "sara")
    phone, laptop = Api(app, "sara"), Api(app, "sara")
    assert laptop.post("/api/auth/password", json={"current": PASSWORD, "new": "An0ther!Strong"}).status_code == 200
    assert phone.get("/api/auth/me").status_code == 401
    assert laptop.get("/api/auth/me").status_code == 200


def test_totp_enrolment_login_and_replay(app, ctx):
    add_user(ctx, "boss", role="admin")
    api = Api(app, "boss")
    setup = api.post("/api/auth/totp/setup", json={"password": PASSWORD})
    assert setup.status_code == 200 and setup.json()["qr"].startswith("data:image/svg+xml;base64,")
    secret = setup.json()["secret"]
    assert api.post("/api/auth/totp/enable", json={"code": "000000"}).status_code == 400
    assert api.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()}).status_code == 200

    client = TestClient(app)
    first = client.post("/api/auth/login", json={"username": "boss", "password": PASSWORD})
    assert first.status_code == 401 and first.json()["code"] == "mfa_required"
    wrong = client.post("/api/auth/login", json={"username": "boss", "password": PASSWORD, "totp": "123456"})
    assert wrong.status_code == 401
    # The code used during enrolment cannot be replayed.
    replay = client.post(
        "/api/auth/login", json={"username": "boss", "password": PASSWORD, "totp": pyotp.TOTP(secret).now()}
    )
    assert replay.status_code == 401
    with ctx.sf() as db:  # simulate the next 30-second window
        db.query(User).filter_by(username="boss").update({"totp_last_step": User.totp_last_step - 1})
        db.commit()
    good = client.post(
        "/api/auth/login", json={"username": "boss", "password": PASSWORD, "totp": pyotp.TOTP(secret).now()}
    )
    assert good.status_code == 200


def test_admins_must_enrol_2fa(tmp_path, fake_claude):
    app = create_app(
        make_settings(tmp_path, require_2fa_for_admins=True), claude_client=fake_claude, start_background=False
    )
    add_user(app.state.ctx, "boss", role="admin")
    api = Api(app, "boss")
    assert api.me["flags"]["must_setup_2fa"] is True
    response = api.get("/api/users")
    assert response.status_code == 403 and response.json()["code"] == "totp_setup_required"
    assert api.post("/api/auth/totp/disable", json={"password": PASSWORD}).status_code == 403


def test_security_headers(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "server" not in response.headers


def test_body_size_limit(tmp_path, fake_claude):
    app = create_app(make_settings(tmp_path, max_body_mb=1), claude_client=fake_claude, start_background=False)
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", content=b"x" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_roles_are_enforced(login):
    trainee = login("tamer", role="trainee")
    assert trainee.get("/api/prescriptions").status_code == 403
    assert trainee.get("/api/academy/me").status_code == 200
    pharmacist = login("sara")
    assert pharmacist.get("/api/users").status_code == 403
    assert pharmacist.get("/api/training/overview").status_code == 403
    assert pharmacist.get("/api/audit").status_code == 403


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_api_docs_hidden_in_production(client, path):
    assert client.get(path).status_code == 404
