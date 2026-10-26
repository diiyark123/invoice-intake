"""Pick the LLM provider from settings (LLM_PROVIDER=gemini|anthropic, D16)."""

from app.config import Settings, get_settings
from app.pipeline.llm.base import LLMProvider


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    model = settings.resolved_llm_model
    if settings.llm_provider == "anthropic":
        from app.pipeline.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, model, settings.llm_max_tokens)
    from app.pipeline.llm.gemini_provider import GeminiProvider

    return GeminiProvider(settings.gemini_api_key, model, settings.llm_max_tokens)
