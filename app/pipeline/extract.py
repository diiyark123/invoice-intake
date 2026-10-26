"""LLM extraction: build the request, parse the JSON reply, retry once on a bad reply (spec §7)."""

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.pipeline.llm.base import LLMProvider, LLMResult, PageImage

PROMPT_VERSION = "extract_v2"  # M5: v2 tuned on data/dev (v1 kept for comparison)
PROMPTS_DIR = Path(__file__).parent / "prompts"
DOC_CLASSES = {"invoice", "credit_note", "multi_invoice", "delivery_note", "other"}


class ExtractionError(RuntimeError):
    pass


def _to_str(v: Any) -> Any:
    # Models sometimes return numbers instead of strings; keep the text form.
    return str(v) if isinstance(v, int | float) and not isinstance(v, bool) else v


class LineItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def _numbers_as_text(cls, v: Any) -> Any:
        return _to_str(v)


class ExtractedInvoice(BaseModel):
    """The §7 schema plus doc_class (D3)."""

    model_config = ConfigDict(extra="ignore")
    doc_class: str = "invoice"
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    total: str | None = None
    line_items: list[LineItemOut] = []

    @field_validator("invoice_number", "subtotal", "tax", "total", mode="before")
    @classmethod
    def _numbers_as_text(cls, v: Any) -> Any:
        return _to_str(v)

    @field_validator("doc_class", mode="before")
    @classmethod
    def _doc_class(cls, v: Any) -> str:
        v = str(v or "invoice").strip().lower()
        return v if v in DOC_CLASSES else "other"

    @field_validator("line_items", mode="before")
    @classmethod
    def _null_lines(cls, v: Any) -> Any:
        return v or []


@dataclass
class ExtractionOutput:
    invoice: ExtractedInvoice
    raw: dict[str, Any]
    calls: list[LLMResult] = field(default_factory=list)

    @property
    def model(self) -> str:
        return self.calls[-1].model

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)


@cache
def load_prompt(version: str = PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"{version}.txt").read_text()


def parse_llm_json(text: str) -> dict[str, Any]:
    """Strip code fences and surrounding chatter, then json.loads. Raises ValueError."""
    s = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fenced:
        s = fenced.group(1).strip()
    if not s.startswith("{"):
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object in model output")
        s = s[start : end + 1]
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("Model output is not a JSON object")
    return data


def run_extraction(
    provider: LLMProvider,
    images: list[PageImage],
    ocr_text: str,
    prompt_version: str = PROMPT_VERSION,
    max_attempts: int = 2,
) -> ExtractionOutput:
    """Call the LLM; on unparseable output retry once, then raise ExtractionError."""
    prompt = load_prompt(prompt_version)
    calls: list[LLMResult] = []
    last_error = ""
    for _ in range(max_attempts):
        result = provider.extract(images, ocr_text, prompt)
        calls.append(result)
        try:
            raw = parse_llm_json(result.text)
            return ExtractionOutput(ExtractedInvoice.model_validate(raw), raw, calls)
        except (ValueError, ValidationError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:300]
    raise ExtractionError(f"LLM returned invalid JSON after {max_attempts} attempts ({last_error})")
