"""Operational commands: init, backup/restore, key rotation, and moving data/models to a GPU machine."""

import io
import json
import zipfile

import pytest

from rushd.cli import main
from rushd.config import Settings
from rushd.context import build_context
from rushd.main import create_app
from rushd.models import ModelVersion, Prescription, User
from rushd.training.transfer import TransferError, inspect_bundle

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


def test_init_can_write_first_run_credentials(env, capsys):
    note = env / "first-run.txt"
    main(["init", "--credentials-file", str(note)])
    password = capsys.readouterr().out.split("(تظهر مرة واحدة فقط): ")[1].split()[0]
    text = note.read_text(encoding="utf-8-sig")
    assert f"كلمة المرور المؤقتة: {password}" in text and "admin" in text
    assert note.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM: Notepad shows the Arabic correctly
    assert note.stat().st_mode & 0o077 == 0
    main(["init", "--credentials-file", str(env / "again.txt")])
    assert not (env / "again.txt").exists()  # only the very first run creates an admin


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


def _move_to(monkeypatch, env, name):
    """Point the CLI at another server's data (e.g. a rented GPU machine)."""
    monkeypatch.setenv("RUSHD_DATA_DIR", str(env / f"{name}-data"))
    monkeypatch.setenv("RUSHD_SECRETS_DIR", str(env / f"{name}-secrets"))
    main(["init"])


def test_dataset_moves_to_a_training_machine(env, capsys, monkeypatch):
    _seed_data(capsys)
    app = create_app(Settings(), claude_client=FakeClaude(), start_background=False)
    api = Api(app, "admin", password="Rushd!Secure-2026")
    body = {"password": "Rushd!Secure-2026", "export_password": "Export-Pass-2026"}
    response = api.post("/api/training/export", json=body)
    assert response.status_code == 200, response.text
    (env / "dataset.rushd").write_bytes(response.content)
    monkeypatch.setenv("RUSHD_EXPORT_PASSWORD", "Export-Pass-2026")
    main(["decrypt-export", str(env / "dataset.rushd"), str(env / "dataset.zip")])

    _move_to(monkeypatch, env, "gpu")
    capsys.readouterr()
    main(["import-dataset", str(env / "dataset.zip")])
    assert "أضيفت 1 روشتة" in capsys.readouterr().out
    gpu = build_context(Settings())
    with gpu.sf() as db:
        rx = db.query(Prescription).one()
        assert rx.status == "verified" and rx.use_for_training
        result = gpu.keyring.decrypt_json(rx.verified_result_enc, f"verified:{rx.uid}")
        assert result["items"][0]["brand"] == "Augmentin"
        assert gpu.audit.verify(db).ok
    main(["import-dataset", str(env / "dataset.zip")])
    assert "أضيفت 0 روشتة" in capsys.readouterr().out  # duplicates are skipped


def _bundle(base="Qwen/Qwen2-VL-2B-Instruct", peft_type="LORA", weights=None, extra=None) -> bytes:
    if weights is None:
        header = json.dumps({"lora_A": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]}}).encode()
        weights = len(header).to_bytes(8, "little") + header + bytes(8)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("meta.json", json.dumps({"format": "rushd-lora-v1", "base_model": base, "revision": None}))
        zf.writestr("adapter_config.json", json.dumps({"peft_type": peft_type, "r": 16}))
        zf.writestr("adapter.safetensors", weights)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_model_moves_between_servers(env, capsys, monkeypatch):
    _move_to(monkeypatch, env, "gpu")
    bundle = _bundle()
    gpu = build_context(Settings())
    with gpu.sf() as db:
        metrics = {"acc_drug": 0.93, "cloud_acc_drug": 0.95, "eval_count": 6, "note": "<b>x</b>"}
        blob = gpu.blobs.put(db, bundle, "model")
        db.add(
            ModelVersion(
                name="rushd-local-v1",
                base_model="Qwen/Qwen2-VL-2B-Instruct",
                adapter_blob=blob,
                metrics=metrics,
                train_count=54,
                eval_count=6,
            )
        )
        db.commit()
    monkeypatch.setenv("RUSHD_EXPORT_PASSWORD", "Model-Pass-2026")
    out = env / "model.rushd"
    main(["export-model", "rushd-local-v1", str(out)])
    raw = out.read_bytes()
    assert raw.startswith(b"RUSHDX1") and b"safetensors" not in raw and b"Qwen" not in raw
    with pytest.raises(SystemExit):
        main(["export-model", "rushd-local-v1", str(out)])  # never overwrites a file

    _move_to(monkeypatch, env, "home")
    monkeypatch.setenv("RUSHD_EXPORT_PASSWORD", "wrong-password-123")
    with pytest.raises(SystemExit):
        main(["import-model", str(out)])
    monkeypatch.setenv("RUSHD_EXPORT_PASSWORD", "Model-Pass-2026")
    capsys.readouterr()
    main(["import-model", str(out)])
    assert "rushd-local-v1-imported" in capsys.readouterr().out
    home = build_context(Settings())
    with home.sf() as db:
        model = db.query(ModelVersion).one()
        assert not model.is_active and model.train_count == 54 and model.eval_count == 6
        assert model.metrics == {
            "acc_drug": 0.93,
            "cloud_acc_drug": 0.95,
            "eval_count": 6,
            "imported_from": "rushd-local-v1",
        }
        assert home.blobs.get(model.adapter_blob, "model") == bundle  # re-encrypted under this server's key
        assert home.audit.verify(db).ok


@pytest.mark.parametrize(
    "bundle",
    [
        _bundle(extra={"payload.pkl": b"cos\nsystem\n"}),
        _bundle(base="../../etc/passwd"),
        _bundle(base="Qwen/.."),
        _bundle(base="https://evil.example/model"),
        _bundle(peft_type="PROMPT_TUNING"),
        _bundle(weights=b"\xff" * 4),
        b"not a zip file",
    ],
    ids=["extra-file", "path-traversal", "dot-repo", "url", "not-lora", "bad-weights", "not-zip"],
)
def test_unsafe_model_files_are_rejected(bundle):
    with pytest.raises(TransferError):
        inspect_bundle(bundle, set())


def test_local_base_model_path_is_allowed_only_when_configured():
    assert inspect_bundle(_bundle(base="/models/qwen2-vl"), {"/models/qwen2-vl"})["base_model"] == "/models/qwen2-vl"
    with pytest.raises(TransferError):
        inspect_bundle(_bundle(base="/models/qwen2-vl"), set())
