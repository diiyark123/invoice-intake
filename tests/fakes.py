"""Test doubles. Tests never call a real LLM API."""

import json
from typing import Any

from app.pipeline.llm.base import LLMResult, PageImage


class FakeLLMProvider:
    """Returns queued replies in order (str, dict -> JSON, or Exception -> raised)."""

    name = "fake"
    model = "fake-model"

    def __init__(self, *replies: str | dict[str, Any] | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def extract(self, images: list[PageImage], ocr_text: str, prompt: str) -> LLMResult:
        self.calls.append({"images": images, "ocr_text": ocr_text, "prompt": prompt})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        text = json.dumps(reply) if isinstance(reply, dict) else reply
        return LLMResult(text=text, input_tokens=1000, output_tokens=200, model=self.model)
