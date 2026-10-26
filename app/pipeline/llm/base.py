"""The provider interface. The rest of the pipeline never knows which LLM is behind it."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PageImage:
    data: bytes
    mime_type: str  # image/jpeg or image/png


@dataclass(frozen=True)
class LLMResult:
    text: str  # raw model output; extract.py parses the JSON
    input_tokens: int
    output_tokens: int  # includes thinking tokens, which are billed as output
    model: str


class LLMError(RuntimeError):
    """The provider could not produce an answer (refusal, empty response, API error)."""


class LLMProvider(Protocol):
    name: str
    model: str

    def extract(self, images: list[PageImage], ocr_text: str, prompt: str) -> LLMResult: ...
