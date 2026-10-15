"""Static configuration loaded from environment variables (prefix ``RUSHD_``).

Anything an administrator may want to change at runtime (engine mode, budget,
quotas...) lives in the database instead - see ``services/settings_store.py``.
Secrets (master key, API key) are deliberately *not* editable from the web UI.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Estimated USD prices per million tokens: (input, output, cache_read, cache_write_5m).
# Used only for the cost dashboard and the monthly budget guard.
MODEL_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUSHD_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "رُشد"
    environment: Literal["production", "development", "test"] = "production"

    # --- storage -----------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    secrets_dir: Path = REPO_ROOT / "secrets"
    database_url: str | None = None
    master_key_file: Path | None = None
    master_key: SecretStr | None = None
    frontend_dir: Path = REPO_ROOT / "frontend"

    # --- HTTP & sessions ---------------------------------------------------
    cookie_secure: bool = True
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    allowed_hosts: list[str] = ["*"]
    max_body_mb: int = 25
    max_bulk_body_mb: int = 400

    # --- authentication hardening ------------------------------------------
    login_max_failures: int = 5
    lockout_minutes: int = 15
    login_ip_limit_per_15min: int = 30
    require_2fa_for_admins: bool = True
    password_min_length: int = 10

    # --- uploads -------------------------------------------------------------
    max_upload_mb: int = 15
    max_image_pixels: int = 50_000_000
    max_batch_files: int = 200
    stored_image_max_edge: int = 3000

    # --- cloud AI (Claude) ---------------------------------------------------
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("RUSHD_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    ai_model: str = "claude-opus-5-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_fallbacks: bool = True
    ai_timeout_seconds: float = 180.0
    ai_max_retries: int = 2
    ai_max_edge_px: int = 2576
    ai_fewshot_edge_px: int = 1568
    fewshot_max: int = 3
    worker_threads: int = 2

    # --- local model ---------------------------------------------------------
    local_base_model: str = "Qwen/Qwen2-VL-2B-Instruct"
    local_device: str = "auto"

    @cached_property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'rushd.db').resolve()}"

    @cached_property
    def key_file(self) -> Path:
        return self.master_key_file or (self.secrets_dir / "master.key")

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure,
        # host-only and Path=/ - it cannot be planted by a sibling sub-domain.
        return "__Host-rushd_session" if self.cookie_secure else "rushd_session"
