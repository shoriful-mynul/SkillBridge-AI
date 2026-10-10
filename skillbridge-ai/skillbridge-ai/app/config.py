"""Runtime settings.

Settings are re-read on every call, so editing `.env` while the server runs
takes effect immediately - no restart needed after adding an API key.

Precedence: a non-empty value in `.env` wins; otherwise the process
environment is used (that is how hosted deployments such as Render work,
where there is no `.env` file).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _env(name: str, default: str = "") -> str:
    file_values = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    value = (file_values.get(name) or "").strip()
    if value:
        return value
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    provider: str
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_model: str
    gemini_thinking_level: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    temperature_override: Optional[float]
    timeout_seconds: float

    @property
    def active_model(self) -> str:
        if self.provider == "gemini":
            return self.gemini_model
        if self.provider == "openai":
            return self.openai_model or "(set OPENAI_MODEL)"
        return "mock-test-double"

    @property
    def has_key(self) -> bool:
        if self.provider == "gemini":
            return bool(self.gemini_api_key)
        if self.provider == "openai":
            return bool(self.openai_api_key)
        return True  # mock needs no key


def get_settings() -> Settings:
    temp = _env("LLM_TEMPERATURE")
    try:
        temperature_override = float(temp) if temp else None
    except ValueError:
        temperature_override = None
    try:
        timeout = float(_env("LLM_TIMEOUT_SECONDS", "60"))
    except ValueError:
        timeout = 60.0
    return Settings(
        provider=_env("LLM_PROVIDER", "gemini").lower(),
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_fallback_model=_env("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
        gemini_thinking_level=_env("GEMINI_THINKING_LEVEL", "low").lower(),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        openai_model=_env("OPENAI_MODEL"),
        temperature_override=temperature_override,
        timeout_seconds=timeout,
    )
