"""Evaluation metrics (spec §13 M3, §14, D11). Pure functions: no DB, no LLM.

A field is correct when its normalized extracted value equals the normalized label
(amounts exact to 2 dp; text case-insensitive after normalization). A field that is null in
both is correct. Line items are matched by position (D11).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.pipeline.normalize import (
    normalize_amount,
    normalize_currency,
    normalize_date,
    normalize_invoice_number,
    normalize_quantity,
    normalize_vendor_name,
)

HEADER_FIELDS = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
)
LINE_FIELDS = ("description", "quantity", "unit_price", "amount")
MONTHLY_VOLUME = 2000


def comparable(field_name: str, value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    v = str(value)
    if field_name in ("subtotal", "tax", "total", "unit_price", "amount"):
        result: Any = normalize_amount(v)
    elif field_name == "quantity":
        result = normalize_quantity(v)
    elif field_name in ("invoice_date", "due_date"):
        result = normalize_date(v)
    elif field_name == "invoice_number":
        result = normalize_invoice_number(v)
    elif field_name == "vendor_name":
        result = normalize_vendor_name(v)
    elif field_name == "currency":
        result = normalize_currency(v)
    else:
        result = " ".join(v.lower().split())
    # Unparseable values fall back to their text so they still compare (and fail) sensibly.
    return str(result) if result is not None else " ".join(v.lower().split())


@dataclass(frozen=True)
class FieldOutcome:
    field: str  # 'total' or 'line_items.amount'
    line_index: int | None
    correct: bool
    expected: Any
    got: Any


def compare_document(
    header: dict[str, Any], lines: list[dict[str, Any]], label: dict[str, Any]
) -> list[FieldOutcome]:
    outcomes = []
    for f in HEADER_FIELDS:
        exp, got = label.get(f), header.get(f)
        outcomes.append(FieldOutcome(f, None, comparable(f, exp) == comparable(f, got), exp, got))
    label_lines = label.get("line_items") or []
    for i in range(max(len(label_lines), len(lines))):
        exp_line = label_lines[i] if i < len(label_lines) else {}
        got_line = lines[i] if i < len(lines) else {}
        for f in LINE_FIELDS:
            exp, got = exp_line.get(f), got_line.get(f)
            if i >= len(label_lines):
                ok = False  # an extra line the model invented
            else:
                ok = comparable(f, exp) == comparable(f, got)
            outcomes.append(FieldOutcome(f"line_items.{f}", i, ok, exp, got))
    return outcomes


@dataclass
class DocResult:
    file: str
    status: str
    review_reasons: list[str]
    processing_ms: int | None
    cost_usd: Decimal | None
    outcomes: list[FieldOutcome] = field(default_factory=list)
    error: str | None = None
    overall_confidence: float | None = None  # min header confidence (§10)

    @property
    def blocking_reasons(self) -> list[str]:
        """Reasons that would still send it to review at any threshold."""
        return [r for r in self.review_reasons if r != "low_confidence"]


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


SWEEP_THRESHOLDS = [round(0.60 + 0.05 * i, 2) for i in range(8)]  # 0.60 .. 0.95


def threshold_sweep(
    docs: list[DocResult], thresholds: list[float] = SWEEP_THRESHOLDS
) -> list[dict[str, Any]]:
    """Re-route stored results at other thresholds, without calling the LLM again.

    A document auto-approves at threshold t when nothing but low confidence held it back and
    its overall (min header) confidence is >= t. Approximation: duplicate links are taken as
    they happened at the run's own threshold.
    """
    rows = []
    for t in thresholds:
        auto = [
            d
            for d in docs
            if d.status != "failed"
            and not d.blocking_reasons
            and d.overall_confidence is not None
            and d.overall_confidence >= t
        ]
        fields = [o.correct for d in auto for o in d.outcomes]
        rows.append(
            {
                "threshold": t,
                "auto_approval_rate": _rate(len(auto), len(docs)),
                "wrong_field_rate_in_auto_approved": _rate(len(fields) - sum(fields), len(fields)),
                "auto_approved_with_any_wrong_field": sum(
                    not all(o.correct for o in d.outcomes) for d in auto
                ),
            }
        )
    return rows


def summarize(docs: list[DocResult], duplicates: list[dict[str, str]]) -> dict[str, Any]:
    by_file = {d.file: d for d in docs}
    per_field: dict[str, list[bool]] = defaultdict(list)
    for d in docs:
        for o in d.outcomes:
            per_field[o.field].append(o.correct)

    header = [o.correct for d in docs for o in d.outcomes if o.line_index is None]
    allf = [o.correct for d in docs for o in d.outcomes]
    auto = [d for d in docs if d.status == "auto_approved"]
    auto_fields = [o.correct for d in auto for o in d.outcomes]

    dup_files = {x["file"] for x in duplicates}
    caught = [
        x
        for x in duplicates
        if x["file"] in by_file
        and "possible_duplicate" in by_file[x["file"]].review_reasons
        and by_file[x["file"]].status != "auto_approved"
    ]
    false_flags = [
        d.file for d in docs if d.file not in dup_files and "possible_duplicate" in d.review_reasons
    ]

    times = [d.processing_ms for d in docs if d.processing_ms is not None]
    costs = [d.cost_usd for d in docs if d.cost_usd is not None]
    cost_per_invoice = (sum(costs, Decimal(0)) / len(costs)) if costs else None
    reasons: dict[str, int] = defaultdict(int)
    for d in docs:
        for r in d.review_reasons:
            reasons[r] += 1

    return {
        "documents": len(docs),
        "failed": sum(d.status == "failed" for d in docs),
        "field_accuracy_overall": _rate(sum(allf), len(allf)),
        "field_accuracy_header": _rate(sum(header), len(header)),
        "field_accuracy_per_field": {
            f: _rate(sum(v), len(v)) for f, v in sorted(per_field.items())
        },
        "fields_compared": len(allf),
        "auto_approval_rate": _rate(len(auto), len(docs)),
        "auto_approved": len(auto),
        "wrong_field_rate_in_auto_approved": _rate(
            len(auto_fields) - sum(auto_fields), len(auto_fields)
        ),
        "wrong_fields_in_auto_approved": len(auto_fields) - sum(auto_fields),
        "auto_approved_with_any_wrong_field": [
            d.file for d in auto if not all(o.correct for o in d.outcomes)
        ],
        "duplicates_caught": f"{len(caught)}/{len(duplicates)}",
        "duplicates_missed": sorted(dup_files - {x["file"] for x in caught}),
        "false_duplicate_flags": false_flags,
        "review_reason_counts": dict(sorted(reasons.items())),
        "avg_processing_seconds": round(sum(times) / len(times) / 1000, 2) if times else None,
        "cost_per_invoice_usd": float(round(cost_per_invoice, 5)) if cost_per_invoice else None,
        "projected_monthly_cost_usd": (
            float(round(cost_per_invoice * MONTHLY_VOLUME, 2)) if cost_per_invoice else None
        ),
    }
