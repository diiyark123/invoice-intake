"""Decide: auto-approve, or send to a human with plain reasons (spec §10)."""

from dataclasses import dataclass
from typing import Literal

from app.pipeline.validate import RuleResult

Decision = Literal["auto_approve", "needs_review"]
# Reasons that come from the document itself, not from a rule; they survive re-checks.
NON_RULE_REASONS = ("low_image_quality", "credit_note", "multi_invoice", "delivery_note", "other")


@dataclass(frozen=True)
class RoutingPolicy:
    confidence_threshold: float = 0.85
    require_review_for_new_vendor: bool = True


def route(
    results: list[RuleResult],
    header_confidences: dict[str, float | None],
    policy: RoutingPolicy,
    extra_reasons: list[str] | None = None,
) -> tuple[Decision, list[str]]:
    """Auto-approve only if every rule passes, not a duplicate, vendor known (unless the
    manager allows new vendors), and every header field confidence >= threshold.

    `extra_reasons` (low_image_quality, a non-invoice doc_class) always force review.
    """
    reasons = list(extra_reasons or [])
    for r in results:
        if r.passed or r.severity == "warning":
            continue
        if r.rule == "vendor_known" and not policy.require_review_for_new_vendor:
            continue  # D19: approval.py will add the vendor
        reasons.append("possible_duplicate" if r.rule == "not_duplicate" else r.rule)
    low = [
        k
        for k, v in header_confidences.items()
        if v is not None and v < policy.confidence_threshold
    ]
    if low:
        reasons.append("low_confidence")
    return ("needs_review" if reasons else "auto_approve"), reasons
