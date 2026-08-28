"""Environment-driven application configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env dosyasını çalışma klasöründen bağımsız olarak proje kökünden yükle.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_FILE, override=False)


class CouncilSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    strategist_model: str = "openai/gpt-5.6-luna"
    strategist_fallbacks: str = "gemini/gemini-2.5-flash"

    critic_model: str = "gemini/gemini-2.5-flash"
    critic_fallbacks: str = "openai/gpt-5.6-luna"

    synthesizer_model: str = "openai/gpt-5.6-luna"
    synthesizer_fallbacks: str = "gemini/gemini-2.5-flash"

    request_timeout_seconds: float = Field(default=90.0, gt=0)
    max_attempts_per_model: int = Field(default=3, ge=1, le=8)
    max_revision_rounds: int = Field(default=1, ge=0, le=5)
    min_verdict_confidence: float = Field(default=0.78, ge=0.0, le=1.0)
    max_unresolved_questions: int = Field(default=3, ge=0, le=20)
    max_critic_contradictions: int = Field(default=0, ge=0, le=20)
    max_context_chars: int = Field(default=42_000, ge=8_000)
    log_level: str = "INFO"

    def missing_required_api_keys(self) -> tuple[str, ...]:
        """Return API key names required by the configured primary agents."""
        configured_models = (
            self.strategist_model,
            self.critic_model,
            self.synthesizer_model,
        )
        missing: list[str] = []
        if any(
            model.startswith("openai/") for model in configured_models
        ) and not self._has_api_key("OPENAI_API_KEY"):
            missing.append("OPENAI_API_KEY")
        if any(
            model.startswith("gemini/") for model in configured_models
        ) and not self._has_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            missing.append("GEMINI_API_KEY")
        return tuple(missing)

    @staticmethod
    def _has_api_key(*names: str) -> bool:
        placeholders = {"...", "your-api-key", "your_api_key", "api-key", "api_key"}
        return any(
            value and value.lower() not in placeholders
            for name in names
            if (value := os.getenv(name, "").strip())
        )

    @staticmethod
    def model_list(csv_value: str) -> tuple[str, ...]:
        return tuple(item.strip() for item in csv_value.split(",") if item.strip())
