"""Operational commands: init, backup/restore and master-key rotation."""

import pytest

from rushd.cli import main
from rushd.config import Settings
from rushd.context import build_context
from rushd.main import create_app
from rushd.models import Prescription, User

from .conftest import Api, FakeClaude, prescription_image, upload


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUSHD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RUSHD_SECRETS_DIR", str(tmp_path / "secrets"))
    monkeypatch.setenv("RUSHD_COOKIE_SECURE", "false")
    monkeypatch.setenv("RUSHD_WORKER_THREADS", "0")
    monkeypatch.setenv("RUSHD_REQUIRE_2FA_FOR_ADMINS", "false")
    monkeypatch.setenv("RUSHD_FRONTEND_DIR", str(tmp_path / "none"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("RUSHD_BACKUP_PASSWORD", "Backup-Pass-2026")
    return tmp_path


def _seed_data(capsys):
    main(["init"])
    out = capsys.readouterr().out
    password = out.split("(تظهر مرة واحدة فقط): ")[1].split()[0]
    app = create_app(Settings(), claude_client=FakeClaude(), start_background=False)
    api = Api(app, "admin", password=password)
    api.post("/api/auth/password", json={"current": password, "new": "Rushd!Secure-2026"})
    response = upload(api, prescription_image(seed=7))
    assert response.status_code == 202, response.text
    uid = response.json()["uid"]
    api.post(f"/api/prescriptions/{uid}/verify", json={"items": [{"brand": "Augmentin", "strength": "1g"}]})
    return uid


def _check_readable(uid):
    ctx = build_context(Settings())
    with ctx.sf() as db:
        rx = db.query(Prescription).filter_by(uid=uid).one()
        assert ctx.blobs.get(rx.image_blob, "image")[:2] == b"\xff\xd8"
        assert ctx.keyring.decrypt_json(rx.verified_result_enc, f"verified:{uid}")["items"][0]["brand"] == "Augmentin"
        assert ctx.audit.verify(db).ok
    return ctx


def test_init_is_idempotent(env, capsys):
    main(["init"])
    first = capsys.readouterr().out
    assert "admin" in first and (env / "secrets" / "master.key").exists()
    main(["init"])
    assert "يوجد مستخدمون بالفعل" in capsys.readouterr().out


def test_backup_and_restore(env, capsys, monkeypatch):
    uid = _seed_data(capsys)
    backup = env / "rushd.backup"
    main(["backup", str(backup)])
    raw = backup.read_bytes()
    assert raw.startswith(b"RUSHDX1") and b"SQLite format" not in raw
    restored = env / "restored"
    main(["restore", str(backup), str(restored)])
    monkeypatch.setenv("RUSHD_DATA_DIR", str(restored))
    _check_readable(uid)

    monkeypatch.setenv("RUSHD_BACKUP_PASSWORD", "wrong-password-x")
    with pytest.raises(SystemExit):
        main(["restore", str(backup), str(env / "restored2")])


def test_rotate_key_reencrypts_everything(env, capsys):
    uid = _seed_data(capsys)
    old_key = (env / "secrets" / "master.key").read_text()
    main(["rotate-key", "--yes"])
    assert "تم تدوير المفتاح" in capsys.readouterr().out
    assert (env / "secrets" / "master.key").read_text() != old_key
    ctx = _check_readable(uid)
    with ctx.sf() as db:
        assert db.query(User).count() == 1
    app = create_app(Settings(), claude_client=FakeClaude(), start_background=False)
    api = Api(app, "admin", password="Rushd!Secure-2026")
    assert api.get(f"/api/prescriptions/{uid}/image").status_code == 200


def test_reset_password_and_verify_audit(env, capsys):
    _seed_data(capsys)
    main(["reset-password", "admin"])
    assert "كلمة المرور المؤقتة الجديدة" in capsys.readouterr().out
    with pytest.raises(SystemExit) as code:
        main(["verify-audit"])
    assert code.value.code == 0
