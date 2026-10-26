"""Confidence scoring (spec §10), exactly as written; tune only in M5 on dev data.

confidence = source_match * (0.5 + 0.5 * format_ok) * rule_penalty
"""

from dataclasses import dataclass

from app.pipeline.validate import REQUIRED_FIELDS, RuleResult, field_key

FAILED_RULE_PENALTY = 0.5


@dataclass(frozen=True)
class FieldInput:
    field_name: str
    line_item_index: int | None
    value_text: str | None
    normalized_value: str | None
    source_match: float


def field_confidence(source_match: float, format_ok: bool, in_failed_rule: bool) -> float:
    rule_penalty = FAILED_RULE_PENALTY if in_failed_rule else 1.0
    return round(source_match * (0.5 + 0.5 * int(format_ok)) * rule_penalty, 4)


def failed_field_keys(results: list[RuleResult]) -> set[str]:
    """Fields involved in a failed rule. Warnings (D20) don't penalise."""
    return {f for r in results if not r.passed and r.severity == "error" for f in r.fields}


def score_fields(
    fields: list[FieldInput], results: list[RuleResult]
) -> tuple[dict[str, float | None], float]:
    """Return ({field_key: confidence or None}, overall).

    Missing required field -> 0. A blank optional field (e.g. no due date printed) has no
    confidence and is left out of the overall score (D21). Overall = min over header fields.
    """
    failed = failed_field_keys(results)
    scores: dict[str, float | None] = {}
    for f in fields:
        key = field_key(f.field_name, f.line_item_index)
        blank = f.value_text is None or not str(f.value_text).strip()
        if blank:
            is_required = f.line_item_index is None and f.field_name in REQUIRED_FIELDS
            scores[key] = 0.0 if is_required else None
            continue
        format_ok = f.normalized_value is not None  # normalize returns None if it can't parse
        scores[key] = field_confidence(f.source_match, format_ok, key in failed)
    header = [
        v
        for f in fields
        if f.line_item_index is None and (v := scores[field_key(f.field_name, None)]) is not None
    ]
    overall = min(header) if header else 0.0
    return scores, overall
