import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.pipeline.normalize import (
    VendorRef,
    match_vendor,
    normalize_amount,
    normalize_date,
    normalize_invoice_number,
    normalize_quantity,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12/03/2026", date(2026, 3, 12)),  # day-first
        ("12-03-2026", date(2026, 3, 12)),
        ("12.03.2026", date(2026, 3, 12)),
        ("12-Mar-2026", date(2026, 3, 12)),
        ("12 March 2026", date(2026, 3, 12)),
        ("March 12, 2026", date(2026, 3, 12)),
        ("2026-03-12", date(2026, 3, 12)),  # ISO must not be read day-first
        ("2026-12-03", date(2026, 12, 3)),
        ("25-Sep-2026", date(2026, 9, 25)),
        ("31/12/2025", date(2025, 12, 31)),
        ("", None),
        (None, None),
        ("not a date", None),
        ("31/02/2026", None),
    ],
)
def test_normalize_date(text: str | None, expected: date | None) -> None:
    assert normalize_date(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),  # European
        ("₹ 1,23,456.00", "123456.00"),  # Indian grouping
        ("Rs. 95,889.75", "95889.75"),
        ("INR 5,459.39", "5459.39"),
        ("12,50", "12.50"),  # decimal comma
        ("1,234", "1234.00"),  # thousands comma
        ("1.234.567", "1234567.00"),
        ("1 234 567,89", "1234567.89"),
        ("100", "100.00"),
        ("0.5", "0.50"),
        ("$1,000.005", "1000.01"),  # rounds half up
        ("(1,200.00)", "-1200.00"),
        ("-45.10", "-45.10"),
        ("", None),
        (None, None),
        ("abc", None),
        ("Total (INR) 117,753.76", None),  # not a clean amount
    ],
)
def test_normalize_amount(text: str | None, expected: str | None) -> None:
    result = normalize_amount(text)
    assert result == (Decimal(expected) if expected else None)
    if result is not None:
        assert isinstance(result, Decimal)


@pytest.mark.parametrize(
    "text,expected",
    [("24.5 L", "24.500"), ("100 pcs", "100.000"), ("2.25", "2.250"), ("1,000", "1000.000")],
)
def test_normalize_quantity(text: str, expected: str) -> None:
    assert normalize_quantity(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("INV-0042", "42"),
        ("42", "42"),
        ("0042", "42"),
        ("inv 0042", "42"),
        ("Invoice No. 00123", "123"),
        ("#A-10234", "A-10234"),
        ("INV00915", "915"),
        ("INV-2026-0042", "2026-0042"),
        ("MS/26-27/0042", "MS/26-27/0042"),
        ("No: 7", "7"),
        ("0000", "0"),
        (None, None),
    ],
)
def test_normalize_invoice_number(text: str | None, expected: str | None) -> None:
    assert normalize_invoice_number(text) == expected


VENDORS = [
    VendorRef(uuid.uuid4(), "apex industrial supplies", ("Apex Industrial", "AISPL")),
    VendorRef(uuid.uuid4(), "bharat packaging", ("Bharat Pack",)),
    VendorRef(uuid.uuid4(), "nova tools hardware", ("Nova Tools",)),
]


def test_match_vendor_exact_after_normalizing() -> None:
    m = match_vendor("APEX INDUSTRIAL SUPPLIES PVT. LTD.", VENDORS)
    assert m and m.vendor_id == VENDORS[0].id and m.method == "exact"


def test_match_vendor_alias() -> None:
    m = match_vendor("AISPL", VENDORS)
    assert m and m.vendor_id == VENDORS[0].id and m.method == "alias"


def test_match_vendor_fuzzy() -> None:
    m = match_vendor("Bharat Packagng", VENDORS)  # OCR-style typo
    assert m and m.vendor_id == VENDORS[1].id and m.method == "fuzzy" and m.score >= 0.9
    m = match_vendor("Hardware Nova Tools", VENDORS)  # word order ignored
    assert m and m.vendor_id == VENDORS[2].id


def test_match_vendor_unknown() -> None:
    assert match_vendor("Pinnacle Uniforms", VENDORS) is None
    assert match_vendor(None, VENDORS) is None
    assert match_vendor("Pvt Ltd", VENDORS) is None
