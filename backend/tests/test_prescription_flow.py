"""End to end: upload -> AI reading -> review -> verification -> learning."""

import anthropic
import pytest

from rushd.ai.engines import ClaudeEngine, EngineError, ReadContext
from rushd.models import Correction, Doctor, DoctorDrugStat, Drug, Prescription

from .conftest import default_reading, prescription_image, upload


def _verify_body(detail, **overrides):
    items = []
    for i, item in enumerate(detail["ai_result"]["items"]):
        items.append(
            {
                "brand": item["brand"],
                "drug_id": item["drug_id"],
                "strength": item["strength"],
                "form": item["form"],
                "sig_text": item["sig_text"],
                "line_text": item["line_text"],
                "ai_index": i,
                **item["sig"],
            }
        )
    body = {"items": items, "doctor": {"name": "د. أحمد علي", "specialty": "باطنة"}}
    body.update(overrides)
    return body


def test_read_returns_enriched_result(login, fake_claude):
    api = login("sara")
    response = upload(api)
    assert response.status_code == 202
    uid = response.json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["status"] == "needs_review"
    result = detail["ai_result"]
    first = result["items"][0]
    assert first["read_name"] == "Augmantin"
    assert first["brand"] == "Augmentin"  # misreading snapped onto the drug database
    assert first["generic"] == "amoxicillin + clavulanic acid"
    assert first["instructions_ar"] == "قرص واحد مرتين يومياً (كل ١٢ ساعة) بعد الأكل لمدة أسبوع"
    assert first["level"] in ("medium", "high")
    assert any(w["type"] == "duplicate_ingredient" for w in result["warnings"])  # Panadol + Congestal
    assert result["engine"] == "claude"

    request = fake_claude.calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["effort"] == "medium"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["fallbacks"] == "default" and request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert fake_claude.images_in(0) == 1


def test_image_is_encrypted_at_rest_and_served_to_owner_only(login, ctx):
    owner, other = login("sara"), login("omar")
    uid = upload(owner).json()["uid"]
    image = owner.get(f"/api/prescriptions/{uid}/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert image.content[:3] == b"\xff\xd8\xff"
    assert other.get(f"/api/prescriptions/{uid}").status_code == 404
    assert other.get(f"/api/prescriptions/{uid}/image").status_code == 404
    with ctx.sf() as db:
        rx = db.query(Prescription).filter_by(uid=uid).one()
        raw = (ctx.blobs.root / rx.image_blob[:2] / rx.image_blob).read_bytes()
        assert b"JFIF" not in raw and raw[:3] != b"\xff\xd8\xff"  # ciphertext on disk
        assert b"Augmantin" not in rx.ai_result_enc


def test_verify_teaches_the_system(login, ctx, fake_claude):
    api = login("sara")
    uid = upload(api).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    body = _verify_body(detail)
    body["items"][0]["brand"] = "Augmentin"  # pharmacist confirms
    body["items"][2] = {"brand": "Comtrex Max", "form": "tablet", "sig_text": "1x3", "ai_index": 2}  # new drug
    response = api.post(f"/api/prescriptions/{uid}/verify", json=body)
    assert response.status_code == 200, response.text
    with ctx.sf() as db:
        rx = db.query(Prescription).filter_by(uid=uid).one()
        assert rx.status == "verified" and rx.doctor_id is not None
        assert rx.acc_drug == pytest.approx(2 / 3, abs=1e-3)
        doctor = db.get(Doctor, rx.doctor_id)
        assert doctor.verified_count == 1 and doctor.name == "د. أحمد علي"
        learned = db.query(Drug).filter_by(brand="Comtrex Max").one()
        assert learned.source == "learned"
        corrections = {(c.scope, c.wrong_norm, c.right_text) for c in db.query(Correction)}
        assert ("g", "congestal", "Comtrex Max") in corrections
        assert (f"d{doctor.id}", "augmantin", "Augmentin") in corrections
        assert db.query(DoctorDrugStat).filter_by(doctor_id=doctor.id).count() == 3

    # A pharmacist cannot silently rewrite a verified prescription.
    assert api.post(f"/api/prescriptions/{uid}/verify", json=body).status_code == 403

    # The drug learned in that (just committed) transaction is used on the very next reading.
    uid2 = upload(api, prescription_image(seed=77)).json()["uid"]
    third = api.get(f"/api/prescriptions/{uid2}").json()["ai_result"]["items"][2]
    assert third["brand"] == "Comtrex Max" and third["drug_id"] == learned.id
    assert "learned_correction" in third["flags"] and "not_in_database" not in third["flags"]


def test_second_prescription_from_known_doctor_uses_examples(login, ctx, fake_claude):
    api = login("sara")
    uid = upload(api, prescription_image(seed=1)).json()["uid"]
    body = _verify_body(api.get(f"/api/prescriptions/{uid}").json())
    body["items"][0]["brand"] = "Augmentin"
    assert api.post(f"/api/prescriptions/{uid}/verify", json=body).status_code == 200

    calls_before = len(fake_claude.calls)
    uid2 = upload(api, prescription_image(seed=2)).json()["uid"]
    calls = fake_claude.calls[calls_before:]
    assert len(calls) == 2  # unsure first pass + second look with this doctor's verified handwriting
    content = calls[1]["messages"][0]["content"]
    texts = " ".join(block.get("text", "") for block in content if block["type"] == "text")
    assert fake_claude.images_in(-1) == 2
    assert "Learning from this doctor's handwriting" in texts
    assert "Augmentin (1)" in texts  # the doctor's habits are shared too
    assert "first read as Augmantin" in texts
    assert any(block.get("cache_control") for block in content)

    detail = api.get(f"/api/prescriptions/{uid2}").json()
    first = detail["ai_result"]["items"][0]
    assert "learned_correction" in first["flags"]  # memory of the earlier correction
    assert first["confidence"] >= 0.85
    assert detail["passes"] == 2
    assert detail["doctor"]["name"] == "د. أحمد علي"


def test_preselected_doctor_gets_single_pass_with_examples(login, ctx, fake_claude):
    api = login("sara")
    uid = upload(api, prescription_image(seed=3)).json()["uid"]
    assert (
        api.post(
            f"/api/prescriptions/{uid}/verify", json=_verify_body(api.get(f"/api/prescriptions/{uid}").json())
        ).status_code
        == 200
    )
    with ctx.sf() as db:
        doctor_id = db.query(Doctor).one().id
    before = len(fake_claude.calls)
    upload(api, prescription_image(seed=4), doctor_id=doctor_id)
    assert len(fake_claude.calls) == before + 1
    assert fake_claude.images_in(-1) == 2


def test_duplicate_upload_detected(login):
    api = login("sara")
    image = prescription_image(seed=9)
    first = upload(api, image).json()
    second = upload(api, image).json()
    assert second["duplicate"] is True and second["uid"] == first["uid"]


def test_bad_image_rejected(login):
    api = login("sara")
    response = api.post("/api/prescriptions", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 400 and response.json()["code"] == "bad_image"


def test_engine_failure_marks_failed_and_retry_works(login, fake_claude):
    api = login("sara")
    fake_claude.stop_reason = "refusal"
    uid = upload(api).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["status"] == "failed" and detail["error"]
    fake_claude.stop_reason = "end_turn"
    assert api.post(f"/api/prescriptions/{uid}/retry").status_code == 200
    assert api.get(f"/api/prescriptions/{uid}").json()["status"] == "needs_review"


def test_not_configured_cloud_fails_cleanly(tmp_path):
    from fastapi.testclient import TestClient

    from rushd.main import create_app

    from .conftest import Api, add_user, make_settings

    app = create_app(make_settings(tmp_path), start_background=False)  # no API key, no fake client
    add_user(app.state.ctx, "sara")
    api = Api(app, "sara")
    uid = upload(api).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["status"] == "failed" and "مفتاح" in detail["error"]
    assert TestClient(app).get("/api/health").status_code == 200


def test_reject_and_daily_quota(login, ctx):
    api = login("sara")
    uid = upload(api, prescription_image(seed=11)).json()["uid"]
    assert api.post(f"/api/prescriptions/{uid}/reject", json={"reason": "ليست روشتة"}).status_code == 200
    assert api.get(f"/api/prescriptions/{uid}").json()["status"] == "rejected"
    with ctx.sf() as db:
        ctx.store.update(db, {"reads_per_user_per_day": 2}, None)
        db.commit()
    upload(api, prescription_image(seed=12))
    assert upload(api, prescription_image(seed=13)).status_code == 429


def test_monthly_budget_blocks_cloud(login, ctx):
    api = login("sara")
    with ctx.sf() as db:
        ctx.store.update(db, {"monthly_budget_usd": 0.01}, None)
        db.commit()
    upload(api, prescription_image(seed=21))  # costs more than the budget
    uid = upload(api, prescription_image(seed=22)).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["status"] == "failed" and "الميزانية" in detail["error"]


def test_listing_and_review_queue(login, ctx):
    pharmacist, trainer = login("sara"), login("mona", role="trainer")
    for seed in (31, 32):
        upload(pharmacist, prescription_image(seed=seed))
    upload(trainer, prescription_image(seed=33))
    assert pharmacist.get("/api/prescriptions").json()["total"] == 2  # own uploads only
    assert trainer.get("/api/prescriptions").json()["total"] == 3
    first = trainer.get("/api/review/next").json()
    assert first["uid"] and first["remaining"] == 3
    second = trainer.get(f"/api/review/next?after={first['uid']}").json()
    assert second["uid"] != first["uid"]


def test_claude_engine_error_mapping():
    class Boom:
        def __init__(self, exc):
            self.beta = type(
                "B",
                (),
                {"messages": type("M", (), {"create": staticmethod(lambda **kw: (_ for _ in ()).throw(exc))})()},
            )()

    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    rate = anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None)
    engine = ClaudeEngine(None, timeout=10, max_retries=0, client=Boom(rate))
    with pytest.raises(EngineError) as info:
        engine.read(b"\xff\xd8", ReadContext(), model="claude-opus-5-5", effort="low", fallbacks=True)
    assert info.value.retryable is True
    auth = anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None)
    with pytest.raises(EngineError) as info:
        ClaudeEngine(None, timeout=10, max_retries=0, client=Boom(auth)).read(
            b"\xff\xd8", ReadContext(), model="claude-opus-5-5", effort="low", fallbacks=True
        )
    assert info.value.retryable is False


def test_haiku_requests_skip_fallbacks():
    engine = ClaudeEngine(None, timeout=10, max_retries=0)
    request = engine.build_request(b"\xff\xd8", ReadContext(), model="claude-haiku-5-5", effort="low", fallbacks=True)
    assert "fallbacks" not in request and "betas" not in request


def test_garbage_model_output_is_retryable(login, fake_claude):
    api = login("sara")
    fake_claude.readings = ["not json", "still not json", "nope"]
    uid = upload(api).json()["uid"]
    assert api.get(f"/api/prescriptions/{uid}").json()["status"] == "failed"
    assert len(fake_claude.calls) == 3  # retried, then gave up


def test_non_prescription_flagged(login, fake_claude):
    api = login("sara")
    fake_claude.readings = [default_reading(is_prescription=False, medications=[], overall_confidence=0.9)]
    uid = upload(api).json()["uid"]
    detail = api.get(f"/api/prescriptions/{uid}").json()
    assert detail["ai_result"]["is_prescription"] is False and detail["ai_result"]["items"] == []
