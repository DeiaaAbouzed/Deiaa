"""Bulk feeding, ZIP import, academy, drugs/doctors, users, settings and audit."""

import io
import json
import zipfile

from rushd.models import AuditLog, Doctor, Prescription
from rushd.training.export import ExportError, decrypt_stream

from .conftest import PASSWORD, prescription_image, upload


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_bulk_upload_prereads_everything(login, fake_claude):
    trainer = login("mona", role="trainer")
    files = [("files", (f"rx{i}.jpg", prescription_image(seed=100 + i), "image/jpeg")) for i in range(3)]
    files.append(("files", ("broken.jpg", b"garbage", "image/jpeg")))
    response = trainer.post("/api/batches", files=files, data={"name": "دفعة اختبار"})
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 3 and body["rejected"][0]["file"] == "broken.jpg"
    batches = trainer.get("/api/batches").json()
    assert batches[0]["counts"]["needs_review"] == 3
    assert len(fake_claude.calls) == 3


def test_pharmacist_cannot_bulk_upload(login):
    api = login("sara")
    assert api.post("/api/batches", files=[("files", ("a.jpg", prescription_image(), "image/jpeg"))]).status_code == 403


def test_zip_import_with_labels(login, ctx, fake_claude):
    trainer = login("mona", role="trainer")
    labels = "\n".join(
        json.dumps(row, ensure_ascii=False)
        for row in [
            {
                "file": "a.jpg",
                "doctor": {"name": "د. سامي فؤاد", "specialty": "أطفال"},
                "items": [{"brand": "Augmentin", "strength": "457mg/5ml", "form": "suspension", "sig_text": "5ml x2"}],
            },
            {"file": "b.jpg", "doctor": "د. سامي فؤاد", "items": [{"brand": "Antinal", "form": "suspension"}]},
        ]
    )
    archive = _zip(
        {
            "batch/a.jpg": prescription_image(seed=201),
            "batch/b.jpg": prescription_image(seed=202),
            "batch/c.jpg": prescription_image(seed=203),  # no label -> AI pre-read
            "../evil.jpg": prescription_image(seed=204),  # path tricks are flattened, never extracted
            "__MACOSX/._a.jpg": b"junk",
            "labels.jsonl": labels.encode(),
            "notes.txt": b"ignored",
        }
    )
    response = trainer.post("/api/batches/import", files={"archive": ("data.zip", archive, "application/zip")})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verified"] == 2 and body["queued"] == 2
    with ctx.sf() as db:
        doctor = db.query(Doctor).one()
        assert doctor.verified_count == 2 and doctor.specialty == "أطفال"
        verified = db.query(Prescription).filter_by(status="verified").all()
        assert len(verified) == 2 and all(rx.use_for_training for rx in verified)
    assert len(fake_claude.calls) == 2


def test_zip_import_rejects_bad_archives(login):
    trainer = login("mona", role="trainer")
    response = trainer.post("/api/batches/import", files={"archive": ("x.zip", b"not a zip", "application/zip")})
    assert response.status_code == 400


def test_academy_round_trip(login, ctx):
    trainer = login("mona", role="trainer")
    trainee = login("tamer", role="trainee")
    assert trainee.post("/api/academy/start", json={}).status_code == 404  # empty pool

    uid = upload(trainer, prescription_image(seed=301)).json()["uid"]
    detail = trainer.get(f"/api/prescriptions/{uid}").json()
    items = [
        {
            "brand": "Augmentin",
            "strength": "1g",
            "form": "tablet",
            "sig_text": "1x2",
            "times_per_day": 2,
            "ai_index": 0,
        },
        {"brand": "Panadol", "strength": "500mg", "form": "tablet", "sig_text": "1x3", "ai_index": 1},
    ]
    assert (
        trainer.post(f"/api/prescriptions/{uid}/verify", json={"items": items, "academy_approved": True}).status_code
        == 200
    )
    assert detail["status"] == "needs_review"

    start = trainee.post("/api/academy/start", json={"difficulty": "hard"})
    assert start.status_code == 200
    attempt = start.json()["attempt_id"]
    image = trainee.get(f"/api/academy/attempts/{attempt}/image")
    assert image.status_code == 200 and image.content[:2] == b"\xff\xd8"
    assert trainee.get(f"/api/prescriptions/{uid}").status_code == 403  # only through the quiz

    answers = [{"brand": "augmentin", "strength": "1 gm", "times_per_day": 2}, {"brand": "Brufen"}]
    result = trainee.post(f"/api/academy/attempts/{attempt}/submit", json={"answers": answers}).json()
    assert result["details"][0]["name_ok"] and result["details"][0]["strength_ok"] and result["details"][0]["freq_ok"]
    assert result["details"][1]["name_ok"] is False
    assert result["details"][1]["expected"]["brand"] == "Panadol"
    assert 0 < result["percent"] < 100
    assert trainee.post(f"/api/academy/attempts/{attempt}/submit", json={"answers": answers}).status_code == 409

    other = login("hoda", role="trainee")
    assert other.get(f"/api/academy/attempts/{attempt}/image").status_code == 404
    board = trainee.get("/api/academy/leaderboard").json()
    assert board[0]["me"] is True
    assert trainee.get("/api/academy/me").json()["attempts"] == 1


def test_drug_management_and_suggest(login, ctx):
    trainer = login("mona", role="trainer")
    pharmacist = login("sara")
    found = pharmacist.get("/api/drugs/suggest", params={"q": "Augmantin"}).json()
    assert found[0]["brand"] == "Augmentin" and "1g" in found[0]["strengths"]
    arabic = pharmacist.get("/api/drugs", params={"q": "أوجمنتين"}).json()
    assert arabic["items"][0]["brand"] == "Augmentin"
    created = trainer.post("/api/drugs", json={"brand": "Ezacard", "generic": "aspirin", "drug_class": "Antiplatelet"})
    assert created.status_code == 201
    assert trainer.post("/api/drugs", json={"brand": "ezacard"}).status_code == 409
    assert pharmacist.post("/api/drugs", json={"brand": "X"}).status_code == 403
    assert pharmacist.get("/api/drugs/suggest", params={"q": "Ezacard"}).json()[0]["brand"] == "Ezacard"
    csv_text = "brand,generic,class,forms,strengths\nNewdrug,newgeneric,Statin,tablet,10mg|20mg\n"
    imported = trainer.post("/api/drugs/import", files={"file": ("d.csv", csv_text.encode(), "text/csv")})
    assert imported.json()["created"] == 1
    export = trainer.get("/api/drugs/export")
    assert "Newdrug" in export.text and export.headers["content-disposition"].startswith("attachment")


def test_doctor_merge_keeps_learning(login, ctx):
    trainer = login("mona", role="trainer")
    a = trainer.post("/api/doctors", json={"name": "د. خالد حسن", "specialty": "عظام"}).json()
    b = trainer.post("/api/doctors", json={"name": "Dr Khaled H", "phone": "0100"}).json()
    assert a["id"] != b["id"]
    merged = trainer.post(f"/api/doctors/{b['id']}/merge", json={"into_id": a["id"]})
    assert merged.status_code == 200
    with ctx.sf() as db:
        assert db.query(Doctor).count() == 1


def test_user_administration(login, app):
    from .conftest import Api

    admin = login("boss", role="admin")
    created = admin.post("/api/users", json={"username": "Nour.Ali", "full_name": "نور", "role": "pharmacist"})
    assert created.status_code == 201
    temp = created.json()["temporary_password"]
    nour = Api(app, "nour.ali", password=temp)
    assert nour.me["flags"]["must_change_password"] is True
    assert admin.post("/api/users", json={"username": "x", "role": "pharmacist"}).status_code == 400
    assert admin.post("/api/users", json={"username": "nour.ali", "role": "pharmacist"}).status_code == 409
    # Creating another admin requires re-entering the password (step-up).
    assert admin.post("/api/users", json={"username": "boss2", "role": "admin"}).status_code == 403
    assert (
        admin.post("/api/users", json={"username": "boss2", "role": "admin", "password": PASSWORD}).status_code == 201
    )
    user_id = created.json()["user"]["id"]
    assert admin.put(f"/api/users/{user_id}", json={"is_active": False}).status_code == 200
    assert nour.get("/api/auth/me").status_code == 401  # disabling revokes sessions
    me = admin.me["user"]["id"]
    assert admin.put(f"/api/users/{me}", json={"role": "pharmacist"}).status_code == 400
    branch = admin.post("/api/branches", json={"name": "فرع المهندسين"})
    assert branch.status_code == 201
    assert admin.post(f"/api/users/{user_id}/reset-password").json()["temporary_password"]


def test_settings_validation(login):
    admin = login("boss", role="admin")
    settings = admin.get("/api/settings").json()
    assert settings["values"]["engine_mode"] == "cloud"
    assert settings["status"]["key_fingerprint"]
    assert admin.put("/api/settings", json={"changes": {"engine_mode": "magic"}}).status_code == 400
    assert admin.put("/api/settings", json={"changes": {"unknown": 1}}).status_code == 400
    ok = admin.put("/api/settings", json={"changes": {"ai_model": "claude-sonnet-5-5", "monthly_budget_usd": 50}})
    assert ok.status_code == 200 and ok.json()["values"]["ai_model"] == "claude-sonnet-5-5"


def test_audit_chain_detects_tampering(login, ctx):
    admin = login("boss", role="admin")
    upload(admin, prescription_image(seed=401))
    assert admin.post("/api/audit/verify").json()["ok"] is True
    log = admin.get("/api/audit").json()
    assert {"login_success", "prescription_uploaded"} <= {e["action"] for e in log["items"]}

    with ctx.sf() as db:
        entry = db.query(AuditLog).filter_by(action="prescription_uploaded").one()
        entry.username = "someone-else"  # an attacker edits the log directly in the database
        db.commit()
    result = admin.post("/api/audit/verify").json()
    assert result["ok"] is False and result["broken_at"] == entry.id


def test_audit_detects_deleted_rows(login, ctx):
    admin = login("boss", role="admin")
    upload(admin, prescription_image(seed=402))
    with ctx.sf() as db:
        newest = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        db.delete(newest)
        db.commit()
    with ctx.sf() as db:
        assert ctx.audit.verify(db).ok is False


def test_dataset_export_requires_step_up_and_is_encrypted(login, ctx):
    admin = login("boss", role="admin")
    uid = upload(admin, prescription_image(seed=501)).json()["uid"]
    admin.post(f"/api/prescriptions/{uid}/verify", json={"items": [{"brand": "Augmentin", "strength": "1g"}]})
    denied = admin.post("/api/training/export", json={"password": "wrong", "export_password": "Export-Pass-123"})
    assert denied.status_code == 403
    response = admin.post("/api/training/export", json={"password": PASSWORD, "export_password": "Export-Pass-123"})
    assert response.status_code == 200
    assert b"labels.jsonl" not in response.content  # nothing readable without the password
    plain = io.BytesIO()
    decrypt_stream(io.BytesIO(response.content), plain, "Export-Pass-123")
    with zipfile.ZipFile(plain) as zf:
        labels = zf.read("labels.jsonl").decode()
        assert "Augmentin" in labels and "محمد" not in labels  # no patient names exported
        assert any(name.startswith("images/") for name in zf.namelist())
    try:
        decrypt_stream(io.BytesIO(response.content), io.BytesIO(), "wrong-password")
        raise AssertionError("expected failure")
    except ExportError:
        pass
    try:
        decrypt_stream(io.BytesIO(response.content[:-100]), io.BytesIO(), "Export-Pass-123")
        raise AssertionError("expected failure")
    except ExportError:
        pass
    assert not list((ctx.settings.data_dir / "tmp").glob("*.rushd"))  # temp file removed


def test_training_overview(login, fake_claude):
    trainer = login("mona", role="trainer")
    uid = upload(trainer, prescription_image(seed=601)).json()["uid"]
    trainer.post(
        f"/api/prescriptions/{uid}/verify",
        json={"items": [{"brand": "Augmentin", "ai_index": 0}], "doctor": {"name": "د. منى"}},
    )
    data = trainer.get("/api/training/overview").json()
    assert data["counts"]["verified"] == 1
    assert data["accuracy"]["n_30d"] == 1
    assert len(data["curve"]) == 12 and data["curve"][-1]["count"] == 1
    assert data["doctors"][0]["name"] == "د. منى"
    assert data["cost"]["month_usd"] > 0
    assert data["engine"]["cloud_ready"] is True


def test_start_training_needs_enough_data(login):
    admin = login("boss", role="admin")
    response = admin.post("/api/training/jobs", json={"password": PASSWORD})
    assert response.status_code == 400 and "50" in response.json()["detail"]
