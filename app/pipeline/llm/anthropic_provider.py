"""Anthropic Claude provider (alternative to Gemini, selected with LLM_PROVIDER=anthropic)."""

import base64
import logging
from typing import Any

import anthropic

from app.pipeline.llm.base import LLMError, LLMResult, PageImage

logger = logging.getLogger(__name__)

# Models that accept the server-side refusal fallback ("default" routing by refusal category).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        # An empty key lets the SDK use its own credential chain (e.g. `ant auth login`).
        self.client = anthropic.Anthropic(api_key=api_key or None)
        self.model = model
        self.max_tokens = max_tokens

    def extract(self, images: list[PageImage], ocr_text: str, prompt: str) -> LLMResult:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": base64.standard_b64encode(img.data).decode(),
                },
            }
            for img in images
        ]
        content.append(
            {"type": "text", "text": f"{prompt}\n\nOCR text of the document:\n{ocr_text}"}
        )
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        try:
            if self.model in _FALLBACK_MODELS:
                response = self.client.beta.messages.create(
                    **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                response = self.client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Claude API connection error: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Claude declined the request (refusal)")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise LLMError(f"Claude returned no text (stop reason: {response.stop_reason})")
        usage = response.usage
        logger.info(
            "llm call provider=anthropic model=%s input_tokens=%d output_tokens=%d",
            response.model,
            usage.input_tokens,
            usage.output_tokens,
        )
        return LLMResult(text, usage.input_tokens, usage.output_tokens, response.model)
