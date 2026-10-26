"""Google Gemini provider (default, D16)."""

import logging
import re
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.pipeline.llm.base import LLMError, LLMResult, PageImage

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 3
MAX_WAIT_SECONDS = 65.0


def retry_delay(message: str, attempt: int) -> float:
    """Use the wait Google suggests ("retry in 51.1s"), else back off 5s, 10s, ..."""
    match = re.search(r"retry in ([\d.]+)s", message)
    wait = float(match.group(1)) + 1 if match else 5.0 * 2 ** (attempt - 1)
    return min(wait, MAX_WAIT_SECONDS)


class GeminiProvider:
    """Retries rate limits (429) and server errors, since the free tier allows ~15 requests/min."""

    name = "gemini"
    sleep = staticmethod(time.sleep)

    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def extract(self, images: list[PageImage], ocr_text: str, prompt: str) -> LLMResult:
        contents: list[types.Part | str] = [
            types.Part.from_bytes(data=img.data, mime_type=img.mime_type) for img in images
        ]
        contents.append(f"{prompt}\n\nOCR text of the document:\n{ocr_text}")
        config = types.GenerateContentConfig(
            response_mime_type="application/json", max_output_tokens=self.max_tokens
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                break
            except genai_errors.APIError as exc:
                transient = exc.code == 429 or (exc.code or 0) >= 500
                if not transient or attempt == MAX_ATTEMPTS:
                    raise LLMError(f"Gemini API error {exc.code}: {exc.message}") from exc
                wait = retry_delay(str(exc.message), attempt)
                logger.warning(
                    "gemini %s, retrying in %.0fs (attempt %d/%d)",
                    exc.code,
                    wait,
                    attempt,
                    MAX_ATTEMPTS,
                )
                self.sleep(wait)

        usage = response.usage_metadata
        input_tokens = (usage.prompt_token_count or 0) if usage else 0
        output_tokens = (
            ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
            if usage
            else 0
        )
        text = response.text
        if not text:
            reason = (
                response.candidates[0].finish_reason if response.candidates else "no candidates"
            )
            raise LLMError(f"Gemini returned no text (finish reason: {reason})")
        logger.info(
            "llm call provider=gemini model=%s input_tokens=%d output_tokens=%d",
            self.model,
            input_tokens,
            output_tokens,
        )
        return LLMResult(text, input_tokens, output_tokens, self.model)
