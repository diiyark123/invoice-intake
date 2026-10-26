"""Link each extracted value back to the OCR words it came from (spec §7, D7).

Candidates are spans of consecutive words on the same line. Typed values (amounts, dates,
quantities) match on their normalized value; text matches on rapidfuzz.ratio.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from typing import Any, Literal

from rapidfuzz import fuzz

from app.pipeline.normalize import (
    normalize_amount,
    normalize_currency,
    normalize_date,
    normalize_quantity,
)
from app.pipeline.ocr import Word

FieldKind = Literal["text", "amount", "date", "quantity", "currency"]
MAX_SPAN_WORDS = 6  # D7
MIN_MATCH_SCORE = 0.6  # below this the value counts as not found on the page


@dataclass(frozen=True)
class Grounding:
    page: int | None
    bbox: dict[str, float] | None
    source_text: str | None
    score: float  # source_match, 0-1


NOT_FOUND = Grounding(page=None, bbox=None, source_text=None, score=0.0)

_NORMALIZERS: dict[str, Callable[[str], Any]] = {
    "amount": normalize_amount,
    "date": normalize_date,
    "quantity": normalize_quantity,
    "currency": normalize_currency,  # D22: "Rs." on the page grounds "INR"
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _lines(words: list[Word]) -> list[list[Word]]:
    return [list(g) for _, g in groupby(words, key=lambda w: (w.page, w.line_id))]


_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d")


def _indian(amount: Decimal) -> str:
    whole, frac = f"{abs(amount):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail]) + "." + frac


def printed_forms(value: str, kind: FieldKind, target: Any) -> list[str]:
    """Ways a typed value is commonly printed, for fuzzy matching when OCR garbled it.

    Comparing an OCR'd "27/O5/2026" with "27/05/2026" is meaningful; comparing it with the
    ISO string the model returned ("2026-05-27") is not, and can match unrelated text.
    """
    if kind == "date" and target is not None:
        return [target.strftime(f) for f in _DATE_FORMATS]
    if kind == "amount" and target is not None:
        return [f"{target:,.2f}", _indian(target), f"{target:.2f}"]
    return [value]


def _span_score(span_text: str, kind: FieldKind, target: Any, forms: list[str]) -> float:
    if kind != "text" and target is not None:
        candidate = _NORMALIZERS[kind](span_text)
        if candidate is not None and candidate == target:
            return 1.0
    span = _clean_text(span_text)
    return max(fuzz.ratio(span, _clean_text(f)) for f in forms) / 100


def ground_value(value: str | None, kind: FieldKind, words: list[Word]) -> Grounding:
    if value is None or not str(value).strip():
        return NOT_FOUND
    value = str(value)
    target = _NORMALIZERS[kind](value) if kind != "text" else None
    forms = printed_forms(value, kind, target)
    # Long descriptions need longer spans than D7's 6 words to match fully.
    max_span = max(MAX_SPAN_WORDS, len(value.split()) + 1)

    best, best_score = None, 0.0
    for line in _lines(words):
        for start in range(len(line)):
            for end in range(start + 1, min(start + max_span, len(line)) + 1):
                span = line[start:end]
                text = " ".join(w.text for w in span)
                score = _span_score(text, kind, target, forms)
                if score > best_score:
                    best, best_score = span, score
                    if score == 1.0 and kind != "text":
                        break
    if best is None or best_score < MIN_MATCH_SCORE:
        return NOT_FOUND
    return Grounding(
        page=best[0].page,
        bbox={
            "x0": min(w.x0 for w in best),
            "y0": min(w.y0 for w in best),
            "x1": max(w.x1 for w in best),
            "y1": max(w.y1 for w in best),
        },
        source_text=" ".join(w.text for w in best),
        score=round(best_score, 4),
    )
