"""Run the real application with a scripted fake AI, for browser (UI) tests.

    python -m tests.e2e_server --port 8765 [--data /tmp/rushd-e2e] [--font handwriting.ttf]

Never use this for real prescriptions: the "AI" here returns canned readings.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import random
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import uvicorn
from PIL import Image, ImageDraw, ImageFont
from pydantic import SecretStr

from rushd.config import Settings
from rushd.db import utcnow
from rushd.main import create_app
from rushd.models import Prescription, User
from rushd.security.passwords import hash_password
from rushd.services.intake import ingest_image
from rushd.services.verification import verify

from .conftest import FakeClaude, default_reading

PASSWORD = "Demo!Pass-2026"

RX_LINES = [
    "R/ Augmantin 1gm tab\n   1x2 p.c 7 days",
    "R/ Panadol 500\n   1x3 prn",
    "R/ Congestal tab\n   1x3",
]


def handwritten(font_path: str | None, seed: int) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", (1000, 1400), (252, 250, 244))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1000, 210], fill=(228, 240, 246))
    try:
        title = ImageFont.truetype(os.environ.get("RUSHD_E2E_ARABIC_FONT", ""), 44)
        d.text((950, 40), "د. أحمد علي", font=title, fill=(15, 50, 80), anchor="ra")
        d.text(
            (950, 110),
            "استشاري الأمراض الباطنة",
            font=ImageFont.truetype(os.environ["RUSHD_E2E_ARABIC_FONT"], 30),
            fill=(40, 70, 90),
            anchor="ra",
        )
    except (OSError, KeyError):
        d.text((60, 60), "Dr. Ahmed Ali - Internal Medicine", fill=(15, 50, 80))
    d.text((60, 160), "Tel: 0100 123 4567", fill=(40, 70, 90))
    try:
        hand = ImageFont.truetype(font_path, 74) if font_path else ImageFont.load_default()
    except OSError:
        hand = ImageFont.load_default()
    y = 290
    for block in RX_LINES:
        for line in block.split("\n"):
            d.text((90 + rng.randint(-10, 10), y + rng.randint(-6, 6)), line, font=hand, fill=(25, 35, 120))
            y += 92
        y += 40
    img = img.rotate(rng.uniform(-1.5, 1.5), fillcolor=(252, 250, 244), expand=False)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class SlowFakeClaude(FakeClaude):
    """Adds latency so the reading animation is visible."""

    def __init__(self, delay: float):
        super().__init__()
        original = self.beta.messages.create

        def create(**kwargs):
            time.sleep(delay)
            return original(**kwargs)

        self.beta.messages.create = create


def seed(app, font: str | None) -> None:
    ctx = app.state.ctx
    with ctx.sf() as db:
        for username, role, name in [
            ("admin", "admin", "د. ضياء أبوزيد"),
            ("mona", "trainer", "منى حسن"),
            ("sara", "pharmacist", "سارة محمود"),
            ("tamer", "trainee", "تامر سعيد"),
        ]:
            db.add(
                User(
                    username=username,
                    full_name=name,
                    role=role,
                    password_hash=hash_password(PASSWORD),
                    must_change_password=False,
                )
            )
        db.commit()
        trainer = db.query(User).filter_by(username="mona").one()
        reader = ctx.worker.reader
        now = utcnow()
        for week in range(10):
            for n in range(3):
                rx = ingest_image(db, ctx, handwritten(font, week * 10 + n), user=trainer, source="bulk", priority=10)
                db.commit()
                reader.process(rx.id)
                db.refresh(rx)
                items = [
                    {
                        "brand": "Augmentin",
                        "strength": "1g",
                        "form": "tablet",
                        "sig_text": "1x2 p.c 7 days",
                        "times_per_day": 2,
                        "timing": "after_meal",
                        "duration_days": 7,
                        "ai_index": 0,
                    },
                    {
                        "brand": "Panadol",
                        "strength": "500mg",
                        "form": "tablet",
                        "sig_text": "1x3 prn",
                        "prn": True,
                        "times_per_day": 3,
                        "ai_index": 1,
                    },
                    {
                        "brand": "Comtrex Max" if week < 3 else "Congestal",
                        "form": "tablet",
                        "sig_text": "1x3",
                        "times_per_day": 3,
                        "ai_index": 2,
                    },
                ]
                verify(
                    db,
                    ctx,
                    rx,
                    {
                        "items": items,
                        "doctor": {"name": "د. أحمد علي", "specialty": "باطنة"},
                        "academy_approved": n == 0,
                    },
                    trainer,
                    "127.0.0.1",
                    can_approve_academy=True,
                )
                rx = db.get(Prescription, rx.id)
                rx.verified_at = now - timedelta(weeks=9 - week, days=n)
                rx.acc_drug = min(1.0, 0.58 + week * 0.045 + n * 0.01)
                db.commit()
        for n in range(2):  # waiting in the review queue
            rx = ingest_image(db, ctx, handwritten(font, 500 + n), user=trainer, source="bulk", priority=10)
            db.commit()
            reader.process(rx.id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default=None)
    parser.add_argument("--font", default=None, help="a handwriting .ttf for realistic sample prescriptions")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()
    data = Path(args.data or tempfile.mkdtemp(prefix="rushd-e2e-"))
    settings = Settings(
        environment="development",
        data_dir=data / "data",
        secrets_dir=data / "secrets",
        master_key=SecretStr(base64.urlsafe_b64encode(os.urandom(32)).decode()),
        cookie_secure=False,
        worker_threads=1,
        require_2fa_for_admins=False,
        anthropic_api_key=None,
    )
    fake = SlowFakeClaude(0)
    readings = [default_reading() for _ in range(200)]
    fake.readings = readings
    app = create_app(settings, claude_client=fake)
    seed(app, args.font)
    fake_delay = SlowFakeClaude(args.delay)
    fake_delay.readings = fake.readings
    app.state.ctx.claude._client = fake_delay
    print(f"seeded; users admin/mona/sara/tamer password {PASSWORD}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
