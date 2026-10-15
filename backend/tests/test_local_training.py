"""The full self-training loop with a tiny model: train -> encrypt -> activate -> read offline.

Needs the optional ML stack (pip install -r requirements-train.txt); skipped otherwise.
"""

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")
pytest.importorskip("torchvision")

from rushd.main import create_app  # noqa: E402
from rushd.models import ModelVersion, Prescription, TrainingJob  # noqa: E402
from rushd.training.common import PROMPT, target_text  # noqa: E402
from rushd.training.train import Trainer  # noqa: E402

from .conftest import (  # noqa: E402
    PASSWORD,
    Api,
    FakeClaude,
    add_user,
    make_settings,
    prescription_image,
    upload,
)
from .tiny_vlm import build  # noqa: E402

ITEMS = [{"brand": "Augmentin", "strength": "1g", "form": "tablet", "sig_text": "1x2"}]


@pytest.fixture
def trained(tmp_path):
    target = target_text({"doctor": {"name": "Dr Ahmed"}, "items": ITEMS})
    base = build(tmp_path / "tiny-base", [target, PROMPT, "user assistant"])
    settings = make_settings(tmp_path, local_base_model=str(base), local_device="cpu")
    app = create_app(settings, claude_client=FakeClaude(), start_background=False)
    ctx = app.state.ctx
    add_user(ctx, "boss", role="admin")
    api = Api(app, "boss")
    for seed in range(12):
        uid = upload(api, prescription_image(seed=900 + seed)).json()["uid"]
        body = {"items": [dict(ITEMS[0], ai_index=0)], "doctor": {"name": "Dr Ahmed"}}
        assert api.post(f"/api/prescriptions/{uid}/verify", json=body).status_code == 200
    with ctx.sf() as db:
        job = TrainingJob(created_by=1, params={"epochs": 30, "learning_rate": 0.01})
        db.add(job)
        db.commit()
        job_id = job.id
    Trainer(ctx, job_id).run()
    return app, ctx, api, job_id


def test_training_produces_encrypted_model(trained):
    app, ctx, api, job_id = trained
    with ctx.sf() as db:
        job = db.get(TrainingJob, job_id)
        assert job.status == "done" and job.progress == 1.0 and job.model_version_id
        version = db.get(ModelVersion, job.model_version_id)
        assert version.train_count + version.eval_count == 12
        assert version.metrics["parse_rate"] == 1.0  # it learned to answer in JSON
        assert version.metrics["acc_drug"] == 1.0
        raw = (ctx.blobs.root / version.adapter_blob[:2] / version.adapter_blob).read_bytes()
        assert not raw.startswith(b"PK")  # the adapter is never stored in plain form
        assert b"lora" not in raw

    # Activate (needs the admin password again) and read fully offline.
    assert api.post(f"/api/training/models/{version.id}/activate", json={"password": "wrong"}).status_code == 403
    assert api.post(f"/api/training/models/{version.id}/activate", json={"password": PASSWORD}).status_code == 200
    assert ctx.local.available
    assert api.put("/api/settings", json={"changes": {"engine_mode": "local"}}).status_code == 200
    calls_before = len(ctx.claude._client.calls)
    uid = upload(api, prescription_image(seed=999)).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["status"] == "needs_review", detail["error"]
    assert detail["engine"] == "local"
    item = detail["ai_result"]["items"][0]
    assert item["brand"] == "Augmentin" and item["drug_id"]
    assert 0 < item["ai_confidence"] <= 1
    assert len(ctx.claude._client.calls) == calls_before  # nothing left the building

    overview = api.get("/api/training/overview").json()
    assert overview["engine"]["local_model"]["name"] == version.name


def test_shadow_mode_measures_local_model(trained):
    app, ctx, api, _ = trained
    with ctx.sf() as db:
        version = db.query(ModelVersion).one()
    api.post(f"/api/training/models/{version.id}/activate", json={"password": PASSWORD})
    api.put("/api/settings", json={"changes": {"engine_mode": "shadow"}})
    uid = upload(api, prescription_image(seed=998)).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["engine"] == "claude"
    body = {"items": [dict(ITEMS[0], ai_index=0)]}
    api.post(f"/api/prescriptions/{uid}/verify", json=body)
    with ctx.sf() as db:
        rx = db.query(Prescription).filter_by(uid=uid).one()
        assert rx.shadow_acc_drug == 1.0
