from __future__ import annotations

import base64
import io
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pydantic import SecretStr

from rushd.config import Settings
from rushd.main import create_app
from rushd.models import User
from rushd.security.passwords import hash_password

PASSWORD = "Str0ng!Passw0rd"


def default_reading(**overrides) -> dict:
    reading = {
        "is_prescription": True,
        "doctor": {"name": "د. أحمد علي", "specialty": "باطنة", "clinic": "عيادة النور", "phone": "01001234567"},
        "patient": {"name": "محمد", "age": "40"},
        "date": "2026-10-01",
        "diagnosis": None,
        "medications": [
            {
                "line_text": "Augmantin 1gm 1x2 p.c 7 days",
                "drug_name": "Augmantin",
                "alternatives": ["Augmentin"],
                "strength": "1 gm",
                "form": "tablet",
                "sig_text": "1x2 p.c 7 days",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "times_per_day": 2,
                "timing": "after_meal",
                "duration_days": 7,
                "confidence": 0.62,
            },
            {
                "line_text": "Panadol 500 1x3 prn",
                "drug_name": "Panadol",
                "strength": "500 mg",
                "form": "tablet",
                "sig_text": "1x3 prn",
                "confidence": 0.95,
            },
            {
                "line_text": "Congestal 1x3",
                "drug_name": "Congestal",
                "form": "tablet",
                "sig_text": "1x3",
                "confidence": 0.9,
            },
        ],
        "notes": "السطر الأول غير واضح",
        "overall_confidence": 0.6,
    }
    reading.update(overrides)
    return reading


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        if self.owner.error is not None:
            raise self.owner.error
        reading = self.owner.readings.pop(0) if self.owner.readings else default_reading()
        text = reading if isinstance(reading, str) else json.dumps(reading, ensure_ascii=False)
        return SimpleNamespace(
            stop_reason=self.owner.stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(
                input_tokens=5000, output_tokens=800, cache_read_input_tokens=1000, cache_creation_input_tokens=0
            ),
            model=kwargs["model"],
        )


class FakeClaude:
    """Stands in for anthropic.Anthropic(): records requests, returns scripted readings."""

    def __init__(self):
        self.calls: list[dict] = []
        self.readings: list = []
        self.error: Exception | None = None
        self.stop_reason = "end_turn"
        self.beta = SimpleNamespace(messages=FakeMessages(self))

    def images_in(self, call_index: int = -1) -> int:
        content = self.calls[call_index]["messages"][0]["content"]
        return sum(1 for block in content if block["type"] == "image")


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        environment="test",
        data_dir=tmp_path / "data",
        secrets_dir=tmp_path / "secrets",
        master_key=SecretStr(base64.urlsafe_b64encode(os.urandom(32)).decode()),
        cookie_secure=False,
        worker_threads=0,
        frontend_dir=tmp_path / "no-frontend",
        anthropic_api_key=None,
        require_2fa_for_admins=False,
        login_ip_limit_per_15min=1000,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake_claude():
    return FakeClaude()


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def app(settings, fake_claude):
    return create_app(settings, claude_client=fake_claude, start_background=False)


@pytest.fixture
def ctx(app):
    return app.state.ctx


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def add_user(ctx, username: str, role: str = "pharmacist", password: str = PASSWORD, **fields) -> User:
    with ctx.sf() as db:
        values = {"must_change_password": False, **fields}
        user = User(
            username=username, full_name=username.title(), role=role, password_hash=hash_password(password), **values
        )
        db.add(user)
        db.commit()
        return user


class Api:
    """A logged-in browser: keeps the cookie jar and sends the CSRF header."""

    def __init__(self, app, username: str, password: str = PASSWORD, totp: str | None = None):
        self.client = TestClient(app, base_url="http://testserver")
        response = self.client.post("/api/auth/login", json={"username": username, "password": password, "totp": totp})
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf"]
        self.me = response.json()

    def _headers(self, extra):
        return {"X-CSRF-Token": self.csrf, **(extra or {})}

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, headers=None, **kw):
        return self.client.post(url, headers=self._headers(headers), **kw)

    def put(self, url, headers=None, **kw):
        return self.client.put(url, headers=self._headers(headers), **kw)

    def delete(self, url, headers=None, **kw):
        return self.client.delete(url, headers=self._headers(headers), **kw)


@pytest.fixture
def login(app, ctx):
    def _login(username: str, role: str = "pharmacist", **fields) -> Api:
        add_user(ctx, username, role, **fields)
        return Api(app, username)

    return _login


def prescription_image(text: str = "R/ Augmentin 1g 1x2", size=(900, 1200), fmt="JPEG", seed: int = 0) -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0], 140], fill=(220, 235, 245))
    draw.text((40, 50), "Dr. Ahmed Ali - Internal Medicine", fill="black")
    for i, line in enumerate(text.split("\n")):
        draw.text((60, 260 + 80 * i), line, fill=(20, 20, 120))
    draw.point((seed % size[0], 10 + seed // size[0]), fill=(seed % 255, 0, 0))  # make each image unique
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def upload(api: Api, image: bytes | None = None, **form):
    files = {"image": ("rx.jpg", image or prescription_image(), "image/jpeg")}
    return api.post("/api/prescriptions", files=files, data={k: str(v) for k, v in form.items()})
