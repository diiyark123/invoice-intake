import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

from app.pipeline.duplicates import DupCandidate, DupRecord, find_duplicate

VENDOR_A, VENDOR_B = uuid.uuid4(), uuid.uuid4()

APPROVED = DupRecord(
    source="invoice",
    document_id=uuid.uuid4(),
    invoice_id=uuid.uuid4(),
    sha256="a" * 64,
    vendor_id=VENDOR_A,
    vendor_name_normalized="apex industrial supplies",
    invoice_number_normalized="2026-0042",
    invoice_date=date(2026, 9, 1),
    total=D("1180.00"),
)

NEW = DupCandidate(
    sha256="b" * 64,
    vendor_id=VENDOR_A,
    vendor_name_normalized="apex industrial supplies",
    invoice_number_normalized="2026-0099",
    invoice_date=date(2026, 9, 20),
    total=D("500.00"),
)


def test_unrelated_invoice_is_not_a_duplicate() -> None:
    assert find_duplicate(NEW, [APPROVED]) is None
    assert find_duplicate(NEW, []) is None


def test_exact_file() -> None:
    m = find_duplicate(replace(NEW, sha256=APPROVED.sha256), [APPROVED])
    assert m and m.kind == "exact_file" and m.score == 1.0


def test_strong_same_vendor_same_number() -> None:
    # INV-2026-0042 and "2026-0042" normalize to the same number
    m = find_duplicate(replace(NEW, invoice_number_normalized="2026-0042"), [APPROVED])
    assert m and m.kind == "strong" and m.record is APPROVED
    assert "same vendor and invoice number" in m.message and "approved invoice" in m.message


def test_strong_match_uses_vendor_name_when_ids_missing() -> None:
    in_review = replace(APPROVED, source="document", invoice_id=None, vendor_id=None)
    m = find_duplicate(replace(NEW, invoice_number_normalized="2026-0042"), [in_review])
    assert m and m.kind == "strong" and "another document" in m.message


def test_fuzzy_same_vendor_total_close_date_similar_number() -> None:
    cand = replace(
        NEW,
        invoice_number_normalized="2026-042",  # one character dropped by OCR
        invoice_date=date(2026, 9, 3),  # 2 days later
        total=D("1180.00"),
    )
    m = find_duplicate(cand, [APPROVED])
    assert m and m.kind == "fuzzy" and m.score >= 0.85


def test_weak_different_vendor_same_total_date_and_number() -> None:
    cand = replace(
        NEW,
        vendor_id=VENDOR_B,
        vendor_name_normalized="apex industrial",
        invoice_number_normalized="2026-0042",
        invoice_date=date(2026, 9, 1),
        total=D("1180.00"),
    )
    m = find_duplicate(cand, [APPROVED])
    assert m and m.kind == "weak"


def test_near_misses_are_not_duplicates() -> None:
    base = replace(NEW, invoice_number_normalized="2026-042", total=D("1180.00"))
    # same vendor + number-ish + total, but 4 days apart: outside the ±3 day window
    assert find_duplicate(replace(base, invoice_date=date(2026, 9, 5)), [APPROVED]) is None
    # close date + similar number, but a different total
    assert (
        find_duplicate(replace(base, invoice_date=date(2026, 9, 2), total=D("1181.00")), [APPROVED])
        is None
    )
    # same total + date, but numbers are not similar enough (monthly repeat order)
    assert (
        find_duplicate(
            replace(base, invoice_date=date(2026, 9, 1), invoice_number_normalized="2026-0517"),
            [APPROVED],
        )
        is None
    )
    # different vendor, same total and date, number only fairly similar (< 90)
    other = replace(
        base,
        vendor_id=VENDOR_B,
        vendor_name_normalized="bharat packaging",
        invoice_date=date(2026, 9, 1),
        invoice_number_normalized="2026-0142",  # 89% similar to 2026-0042
    )
    assert find_duplicate(other, [APPROVED]) is None


def test_strongest_match_wins() -> None:
    fuzzy_rec = replace(
        APPROVED, document_id=uuid.uuid4(), sha256="c" * 64, invoice_number_normalized="2026-042"
    )
    cand = replace(
        NEW,
        invoice_number_normalized="2026-0042",
        invoice_date=date(2026, 9, 2),
        total=D("1180.00"),
    )
    m = find_duplicate(cand, [fuzzy_rec, APPROVED])
    assert m and m.kind == "strong" and m.record is APPROVED
