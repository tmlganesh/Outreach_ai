"""
Centralized application configuration.

Uses pydantic-settings for type-safe environment variable parsing
with validation. All config is loaded once and cached via lru_cache
so every module shares the same validated Settings instance.
"""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve project root — two levels up from this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ocean.io ─────────────────────────────────────────────
    ocean_api_key: str = ""
    ocean_base_url: str = "https://api.ocean.io/v3"

    # ── OpenRouter ───────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Prospeo ──────────────────────────────────────────────
    prospeo_api_key: str = ""
    prospeo_base_url: str = "https://api.prospeo.io"

    # ── Eazyreach ────────────────────────────────────────────
    eazyreach_api_key: str = ""
    eazyreach_token: str = ""
    eazyreach_base_url: str = "https://api.eazyreach.io/v1"

    # ── Brevo ────────────────────────────────────────────────
    brevo_api_key: str = ""
    brevo_base_url: str = "https://api.brevo.com/v3"
    brevo_sender_name: str = "OutreachPilot"
    brevo_sender_email: str = "outreach@outreachpilot.com"

    # ── Application ──────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    max_retries: int = 3
    retry_backoff_factor: float = 2.0
    request_timeout: int = 30
    rate_limit_delay: float = 1.0
    max_companies: int = 50
    max_contacts_per_company: int = 10

    # ── Dashboard ────────────────────────────────────────────
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8000

    # ── Derived paths ────────────────────────────────────────
    @property
    def logs_dir(self) -> Path:
        path = PROJECT_ROOT / "logs"
        path.mkdir(exist_ok=True)
        return path

    @property
    def exports_dir(self) -> Path:
        path = PROJECT_ROOT / "exports"
        path.mkdir(exist_ok=True)
        return path

    @property
    def data_dir(self) -> Path:
        path = PROJECT_ROOT / "app" / "data"
        path.mkdir(exist_ok=True)
        return path

    @property
    def templates_dir(self) -> Path:
        return PROJECT_ROOT / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return PROJECT_ROOT / "app" / "static"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()
