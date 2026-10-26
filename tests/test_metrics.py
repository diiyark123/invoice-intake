from decimal import Decimal

from eval.metrics import DocResult, comparable, compare_document, summarize

LABEL = {
    "vendor_name": "Apex Industrial Supplies Pvt Ltd",
    "invoice_number": "INV-0042",
    "invoice_date": "2026-03-12",
    "due_date": None,
    "currency": "INR",
    "subtotal": "1000.00",
    "tax": "180.00",
    "total": "1180.00",
    "line_items": [
        {"description": "Bolts  box", "quantity": "10", "unit_price": "100.00", "amount": "1000.00"}
    ],
}


def test_comparable_normalizes_like_the_pipeline() -> None:
    assert comparable("total", "1,180.00") == comparable("total", "1180")
    assert comparable("invoice_date", "12/03/2026") == comparable("invoice_date", "2026-03-12")
    assert comparable("invoice_number", "INV-0042") == comparable("invoice_number", "42")
    assert comparable("vendor_name", "APEX INDUSTRIAL SUPPLIES") == comparable(
        "vendor_name", "Apex Industrial Supplies Pvt. Ltd."
    )
    assert comparable("currency", "Rs.") == "INR"
    assert comparable("quantity", "10 pcs") == comparable("quantity", "10.0")
    assert comparable("total", None) is None and comparable("total", " ") is None


def test_perfect_extraction_is_all_correct() -> None:
    header = {k: v for k, v in LABEL.items() if k != "line_items"} | {"total": "1,180.00"}
    outcomes = compare_document(
        header, [{**LABEL["line_items"][0], "description": "bolts box"}], LABEL
    )
    assert len(outcomes) == 8 + 4
    assert all(o.correct for o in outcomes)


def test_wrong_missing_and_extra_values() -> None:
    header = {k: v for k, v in LABEL.items() if k != "line_items"} | {
        "total": "1,118.00",  # misread
        "due_date": "2026-04-11",  # invented (label is null)
    }
    lines = [LABEL["line_items"][0], {"description": "Freight", "amount": "50.00"}]  # extra line
    outcomes = compare_document(header, lines, LABEL)
    wrong = {(o.field, o.line_index) for o in outcomes if not o.correct}
    assert ("total", None) in wrong and ("due_date", None) in wrong
    assert ("line_items.amount", 1) in wrong and ("line_items.quantity", 1) in wrong
    assert ("line_items.amount", 0) not in wrong


def test_summarize() -> None:
    good = compare_document(
        {k: v for k, v in LABEL.items() if k != "line_items"}, LABEL["line_items"], LABEL
    )
    bad = compare_document({"vendor_name": "Apex"}, [], LABEL)
    docs = [
        DocResult("a.pdf", "auto_approved", [], 4000, Decimal("0.0016"), good),
        DocResult("b.pdf", "needs_review", ["vendor_known"], 6000, Decimal("0.0020"), bad),
        DocResult("c.pdf", "needs_review", ["possible_duplicate"], 5000, Decimal("0.0018"), good),
        DocResult("d.pdf", "needs_review", ["possible_duplicate"], 5000, Decimal("0.0018"), good),
    ]
    dups = [
        {"file": "c.pdf", "duplicate_of": "a.pdf", "kind": "exact_copy"},
        {"file": "e.pdf", "duplicate_of": "a.pdf", "kind": "rescanned_copy"},
    ]
    m = summarize(docs, dups)
    assert m["documents"] == 4 and m["auto_approval_rate"] == 0.25
    assert m["wrong_field_rate_in_auto_approved"] == 0.0
    assert m["duplicates_caught"] == "1/2" and m["duplicates_missed"] == ["e.pdf"]
    assert m["false_duplicate_flags"] == ["d.pdf"]
    # 'bad' gets one header field right: due_date, which is null in both
    assert m["field_accuracy_header"] == round((8 + 1 + 8 + 8) / 32, 4)
    assert m["avg_processing_seconds"] == 5.0
    assert m["cost_per_invoice_usd"] == 0.0018 and m["projected_monthly_cost_usd"] == 3.6


def test_threshold_sweep_reroutes_without_llm() -> None:
    from eval.metrics import threshold_sweep

    good = compare_document(
        {k: v for k, v in LABEL.items() if k != "line_items"}, LABEL["line_items"], LABEL
    )
    wrong = compare_document(
        {k: v for k, v in LABEL.items() if k != "line_items"} | {"total": "1.00"},
        LABEL["line_items"],
        LABEL,
    )
    docs = [
        DocResult("a", "auto_approved", [], 1, None, good, overall_confidence=0.95),
        DocResult("b", "needs_review", ["low_confidence"], 1, None, wrong, overall_confidence=0.7),
        DocResult("c", "needs_review", ["vendor_known"], 1, None, good, overall_confidence=1.0),
    ]
    rows = {r["threshold"]: r for r in threshold_sweep(docs, [0.6, 0.85, 0.99])}
    assert rows[0.6]["auto_approval_rate"] == round(2 / 3, 4)
    assert rows[0.6]["auto_approved_with_any_wrong_field"] == 1
    assert rows[0.85]["auto_approval_rate"] == round(1 / 3, 4)
    assert rows[0.85]["wrong_field_rate_in_auto_approved"] == 0.0
    assert rows[0.99]["auto_approval_rate"] == 0.0
