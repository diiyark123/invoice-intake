"""Application settings, read from environment variables (and `.env` when present)."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://invoice:invoice@localhost:5432/invoice"

    # LLM (used from M2). Keys are never hardcoded; they come from the environment only.
    llm_provider: Literal["gemini", "anthropic"] = "gemini"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = ""  # empty = the provider's default below
    llm_max_tokens: int = 8000  # includes the model's thinking tokens, so not too low

    # File storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "auto"  # Cloudflare R2 uses "auto"

    session_secret: str = ""
    api_base_url: str = "http://localhost:8000"
    tesseract_cmd: str = "/usr/bin/tesseract"
    max_upload_mb: int = 15

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, url: str) -> str:
        """Hosts like Render hand out postgres:// URLs; SQLAlchemy needs the psycopg driver."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]


DEFAULT_MODELS = {"gemini": "gemini-3.5-flash-lite", "anthropic": "claude-opus-5-5"}

# USD per 1M tokens (input, output), paid tier. Output includes thinking tokens.
# Looked up 2026-10-26: ai.google.dev/gemini-api/docs/pricing and Anthropic's model table.
LLM_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50")),
    "gemini-3.1-flash-lite": (Decimal("0.25"), Decimal("1.50")),
    "gemini-2.5-flash-lite": (Decimal("0.10"), Decimal("0.40")),
    "gemini-3.8-flash": (Decimal("0.75"), Decimal("3.75")),  # rises to 1.50 / 7.50 in 2027
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
}


def llm_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    """D10. None when the model has no known price (cost is then not stored)."""
    if model not in LLM_PRICES:
        return None
    in_price, out_price = LLM_PRICES[model]
    cost = (input_tokens * in_price + output_tokens * out_price) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.00001"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
