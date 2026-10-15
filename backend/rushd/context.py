"""Application wiring: one AppContext per running app (tests build isolated ones)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from .ai.engines import ClaudeEngine
from .ai.lexicon import LexiconCache
from .ai.safety import build_class_map
from .config import Settings
from .db import Base, make_engine, make_session_factory
from .security.audit import AuditLogger
from .security.crypto import KeyRing, load_master_key
from .security.ratelimit import RateLimiter
from .security.sessions import StepUpWindow
from .services import drugs as drug_service
from .services.settings_store import SettingsStore
from .storage import BlobStore

log = logging.getLogger("rushd")


@dataclass
class AppContext:
    settings: Settings
    engine: Engine
    sf: sessionmaker
    keyring: KeyRing
    blobs: BlobStore
    audit: AuditLogger
    limiter: RateLimiter
    step_up: StepUpWindow
    store: SettingsStore
    lexicon: LexiconCache
    claude: ClaudeEngine
    local: object = None  # training.local_engine.LocalEngine (loaded lazily)
    worker: object = None  # services.worker.Worker
    trainer: object = None  # services.training_runner.TrainingRunner

    def class_map(self) -> dict[str, str]:
        return build_class_map(self.lexicon.get().drugs)

    def drugs_changed(self) -> None:
        self.lexicon.invalidate()


def build_context(settings: Settings, *, claude_client=None) -> AppContext:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    inline_key = settings.master_key.get_secret_value() if settings.master_key else None
    keyring = KeyRing(load_master_key(settings.key_file, inline_key))

    engine = make_engine(settings.db_url)
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    with sf() as db:
        seeded = drug_service.seed_if_empty(db)
        db.commit()
    if seeded:
        log.info("seeded %d drugs", seeded)

    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    claude = ClaudeEngine(
        api_key, timeout=settings.ai_timeout_seconds, max_retries=settings.ai_max_retries, client=claude_client
    )
    return AppContext(
        settings=settings,
        engine=engine,
        sf=sf,
        keyring=keyring,
        blobs=BlobStore(settings.blobs_dir, keyring),
        audit=AuditLogger(sf, keyring, settings.data_dir / "audit.head"),
        limiter=RateLimiter(),
        step_up=StepUpWindow(settings.step_up_minutes),
        store=SettingsStore(settings),
        lexicon=LexiconCache(drug_service.loader(sf), drug_service.fingerprint(sf)),
        claude=claude,
    )
