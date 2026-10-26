import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.pipeline.validate import (
    Candidate,
    CandidateLine,
    RuleSettings,
    date_valid,
    due_after_invoice,
    line_items_sum,
    line_math,
    not_duplicate,
    positive_amounts,
    required_fields,
    totals_math,
    validate,
    vendor_known,
)

TODAY = date(2026, 10, 27)
S = RuleSettings(amount_tolerance=D("0.01"), max_due_days=180)

GOOD = Candidate(
    vendor_name="Apex Industrial Supplies Pvt Ltd",
    vendor_id=uuid.uuid4(),
    invoice_number="INV-0042",
    invoice_number_normalized="42",
    invoice_date=date(2026, 9, 1),
    due_date=date(2026, 10, 1),
    currency="INR",
    subtotal=D("250.00"),
    tax=D("45.00"),
    total=D("295.00"),
    lines=(
        CandidateLine("Bolts", D("2"), D("50.00"), D("100.00")),
        CandidateLine("Copper wire", D("2.5"), D("60.00"), D("150.00")),
    ),
)


def test_good_invoice_passes_every_rule() -> None:
    results = validate(GOOD, S, TODAY)
    assert [r.rule for r in results] == [
        "required_fields",
        "line_items_sum",
        "line_math",
        "totals_math",
        "positive_amounts",
        "date_valid",
        "due_after_invoice",
        "vendor_known",
        "not_duplicate",
    ]
    assert all(r.passed for r in results), [r for r in results if not r.passed]


@pytest.mark.parametrize("field", ["vendor_name", "invoice_number", "invoice_date", "total"])
def test_required_fields_fail(field: str) -> None:
    r = required_fields(replace(GOOD, **{field: None}))
    assert not r.passed and r.fields == (field,)


def test_line_items_sum() -> None:
    assert line_items_sum(GOOD, S).passed
    r = line_items_sum(replace(GOOD, subtotal=D("260.00")), S)
    assert not r.passed and "subtotal" in r.fields and "line_items.1.amount" in r.fields
    assert line_items_sum(replace(GOOD, subtotal=D("250.01")), S).passed, "within tolerance"


def test_line_items_sum_without_lines_is_a_warning() -> None:
    r = line_items_sum(replace(GOOD, lines=()), S)
    assert not r.passed and r.severity == "warning"


def test_line_math() -> None:
    assert line_math(GOOD, S).passed
    bad = replace(GOOD, lines=(CandidateLine("Bolts", D("2"), D("50.00"), D("110.00")),))
    r = line_math(bad, S)
    assert not r.passed and "line_items.0.amount" in r.fields and "line 1" in r.message
    no_qty = replace(GOOD, lines=(CandidateLine("Service", None, None, D("999.00")),))
    assert line_math(no_qty, S).passed, "lines without qty/price are skipped"


def test_totals_math() -> None:
    assert totals_math(GOOD, S).passed
    r = totals_math(replace(GOOD, total=D("300.00")), S)
    assert not r.passed and set(r.fields) == {"subtotal", "tax", "total"}
    assert totals_math(replace(GOOD, tax=None, total=D("250.00")), S).passed, "no tax = 0"
    assert not totals_math(replace(GOOD, subtotal=None), S).passed


def test_positive_amounts() -> None:
    assert positive_amounts(GOOD).passed
    assert not positive_amounts(replace(GOOD, total=D("0.00"))).passed
    assert not positive_amounts(replace(GOOD, total=D("-5.00"))).passed


def test_date_valid() -> None:
    assert date_valid(GOOD, TODAY).passed
    assert date_valid(replace(GOOD, invoice_date=TODAY), TODAY).passed
    assert not date_valid(replace(GOOD, invoice_date=date(2026, 10, 28)), TODAY).passed
    assert not date_valid(replace(GOOD, invoice_date=date(2024, 10, 26)), TODAY).passed
    assert not date_valid(replace(GOOD, invoice_date=None), TODAY).passed


def test_due_after_invoice() -> None:
    assert due_after_invoice(GOOD, S).passed
    assert due_after_invoice(replace(GOOD, due_date=None), S).passed, "due date is optional"
    assert not due_after_invoice(replace(GOOD, due_date=date(2026, 8, 31)), S).passed
    assert due_after_invoice(replace(GOOD, due_date=date(2027, 2, 28)), S).passed  # 180 days
    r = due_after_invoice(replace(GOOD, due_date=date(2027, 3, 1)), S)
    assert not r.passed and "180" in r.message


def test_vendor_known() -> None:
    assert vendor_known(GOOD).passed
    r = vendor_known(replace(GOOD, vendor_id=None))
    assert not r.passed and r.fields == ("vendor_name",)


def test_not_duplicate() -> None:
    assert not_duplicate(None).passed
    assert not not_duplicate("Possible duplicate: ...").passed


def test_tolerance_comes_from_settings() -> None:
    off_by_five_paise = replace(GOOD, total=D("295.05"))
    assert not totals_math(off_by_five_paise, S).passed
    assert totals_math(off_by_five_paise, RuleSettings(D("0.05"), 180)).passed


def test_candidate_from_stored_fields() -> None:
    rows = [
        ("vendor_name", "Apex Industrial", "apex industrial", None),
        ("invoice_number", "INV-0042", "42", None),
        ("invoice_date", "2026-09-01", "2026-09-01", None),
        ("total", "1,180.00", "1180.00", None),
        ("amount", "1,000.00", "1000.00", 0),
        ("quantity", "10", "10.000", 0),
    ]
    vid = uuid.uuid4()
    c = Candidate.from_fields(rows, vid)
    assert c.vendor_name == "Apex Industrial" and c.vendor_id == vid
    assert c.invoice_number == "INV-0042" and c.invoice_number_normalized == "42"
    assert c.invoice_date == date(2026, 9, 1) and c.total == D("1180.00")
    assert c.lines[0].amount == D("1000.00") and c.lines[0].quantity == D("10")
    assert c.due_date is None and c.subtotal is None
