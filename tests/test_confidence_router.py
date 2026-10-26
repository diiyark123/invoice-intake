import pytest

from app.pipeline.confidence import FieldInput, field_confidence, score_fields
from app.pipeline.router import RoutingPolicy, route
from app.pipeline.validate import RuleResult


@pytest.mark.parametrize(
    "source_match,format_ok,failed,expected",
    [
        (1.0, True, False, 1.0),
        (1.0, False, False, 0.5),
        (1.0, True, True, 0.5),
        (0.9, True, False, 0.9),
        (0.8, False, True, 0.2),
        (0.0, True, False, 0.0),
    ],
)
def test_formula_exactly_as_spec(source_match, format_ok, failed, expected) -> None:
    assert field_confidence(source_match, format_ok, failed) == pytest.approx(expected)


def fi(name, value="x", norm="x", match=1.0, index=None) -> FieldInput:
    return FieldInput(name, index, value, norm, match)


FIELDS = [
    fi("vendor_name"),
    fi("invoice_number"),
    fi("invoice_date"),
    fi("due_date", None, None, 0.0),  # not printed: optional, left out (D21)
    fi("currency"),
    fi("subtotal", match=0.9),
    fi("tax"),
    fi("total"),
    fi("amount", match=0.4, index=0),  # line items don't affect the overall score
]


def test_scores_and_overall_is_min_header() -> None:
    scores, overall = score_fields(FIELDS, [])
    assert scores["due_date"] is None
    assert scores["subtotal"] == 0.9 and scores["line_items.0.amount"] == 0.4
    assert overall == 0.9


def test_missing_required_field_is_zero() -> None:
    fields = [f if f.field_name != "total" else fi("total", None, None, 0.0) for f in FIELDS]
    scores, overall = score_fields(fields, [])
    assert scores["total"] == 0.0 and overall == 0.0


def test_unparseable_value_halves_confidence() -> None:
    fields = [
        f if f.field_name != "invoice_date" else fi("invoice_date", "31/02/2026", None)
        for f in FIELDS
    ]
    scores, _ = score_fields(fields, [])
    assert scores["invoice_date"] == 0.5


def test_failed_rule_penalises_its_fields_but_warnings_do_not() -> None:
    results = [
        RuleResult("totals_math", False, "", ("subtotal", "tax", "total")),
        RuleResult("line_items_sum", False, "", ("vendor_name",), severity="warning"),
    ]
    scores, overall = score_fields(FIELDS, results)
    assert scores["total"] == 0.5 and scores["subtotal"] == 0.45
    assert scores["vendor_name"] == 1.0
    assert overall == 0.45


OK = [RuleResult(r, True, "OK") for r in ("required_fields", "totals_math", "vendor_known")]
HIGH = {"vendor_name": 0.95, "total": 1.0, "due_date": None}


def test_route_auto_approves_clean_invoice() -> None:
    assert route(OK, HIGH, RoutingPolicy()) == ("auto_approve", [])


def test_route_reasons() -> None:
    results = OK + [
        RuleResult("totals_math", False, "bad", ("total",)),
        RuleResult("not_duplicate", False, "dup", ("total",)),
        RuleResult("line_items_sum", False, "none", (), severity="warning"),
    ]
    decision, reasons = route(results, HIGH, RoutingPolicy(), ["low_image_quality"])
    assert decision == "needs_review"
    assert reasons == ["low_image_quality", "totals_math", "possible_duplicate"]


def test_route_low_confidence_uses_threshold() -> None:
    scores = {"vendor_name": 0.84, "total": 1.0}
    assert route(OK, scores, RoutingPolicy(0.85)) == ("needs_review", ["low_confidence"])
    assert route(OK, scores, RoutingPolicy(0.80)) == ("auto_approve", [])


def test_route_new_vendor_depends_on_setting() -> None:
    results = [RuleResult("vendor_known", False, "unknown", ("vendor_name",))]
    assert (
        route(results, HIGH, RoutingPolicy(require_review_for_new_vendor=True))[0] == "needs_review"
    )
    assert route(results, HIGH, RoutingPolicy(require_review_for_new_vendor=False)) == (
        "auto_approve",
        [],
    )
