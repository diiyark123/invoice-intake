"""Duplicate detection (spec §9). Pure: the caller loads the existing records from the DB."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from rapidfuzz import fuzz

MatchKind = Literal["exact_file", "strong", "fuzzy", "weak"]
FUZZY_DATE_DAYS = 3
FUZZY_NUMBER_RATIO = 85
WEAK_NUMBER_RATIO = 90


@dataclass(frozen=True)
class DupRecord:
    """An approved invoice, or a document still in review/processing."""

    source: Literal["invoice", "document"]
    document_id: uuid.UUID
    invoice_id: uuid.UUID | None
    sha256: str | None
    vendor_id: uuid.UUID | None
    vendor_name_normalized: str | None
    invoice_number_normalized: str | None
    invoice_date: date | None
    total: Decimal | None


@dataclass(frozen=True)
class DupCandidate:
    sha256: str
    vendor_id: uuid.UUID | None
    vendor_name_normalized: str | None
    invoice_number_normalized: str | None
    invoice_date: date | None
    total: Decimal | None


@dataclass(frozen=True)
class DuplicateMatch:
    record: DupRecord
    kind: MatchKind
    score: float  # 1.0 for exact/strong; number similarity for fuzzy/weak

    @property
    def message(self) -> str:
        where = "an approved invoice" if self.record.source == "invoice" else "another document"
        labels = {
            "exact_file": "is the same file as",
            "strong": "has the same vendor and invoice number as",
            "fuzzy": "has the same vendor and total, a close date and a similar number to",
            "weak": "has the same total, date and a near-identical number to",
        }
        return f"Possible duplicate: this invoice {labels[self.kind]} {where}"


def _same_vendor(c: DupCandidate, r: DupRecord) -> bool:
    if c.vendor_id and r.vendor_id:
        return c.vendor_id == r.vendor_id
    return bool(c.vendor_name_normalized) and c.vendor_name_normalized == r.vendor_name_normalized


def _ratio(a: str | None, b: str | None) -> float:
    return fuzz.ratio(a, b) if a and b else 0.0


def check(c: DupCandidate, r: DupRecord) -> DuplicateMatch | None:
    """The four §9 checks, strongest first."""
    if r.sha256 and c.sha256 == r.sha256:
        return DuplicateMatch(r, "exact_file", 1.0)
    same_vendor = _same_vendor(c, r)
    if (
        same_vendor
        and c.invoice_number_normalized
        and c.invoice_number_normalized == r.invoice_number_normalized
    ):
        return DuplicateMatch(r, "strong", 1.0)
    if c.total is None or c.total != r.total or c.invoice_date is None or r.invoice_date is None:
        return None
    ratio = _ratio(c.invoice_number_normalized, r.invoice_number_normalized)
    day_gap = abs((c.invoice_date - r.invoice_date).days)
    if same_vendor and day_gap <= FUZZY_DATE_DAYS and ratio >= FUZZY_NUMBER_RATIO:
        return DuplicateMatch(r, "fuzzy", ratio / 100)
    if not same_vendor and day_gap == 0 and ratio >= WEAK_NUMBER_RATIO:
        return DuplicateMatch(r, "weak", ratio / 100)
    return None


_STRENGTH = {"exact_file": 3, "strong": 2, "fuzzy": 1, "weak": 0}


def find_duplicate(c: DupCandidate, records: list[DupRecord]) -> DuplicateMatch | None:
    """Best match across all records; approved invoices win ties over documents in review."""
    matches = [m for r in records if (m := check(c, r))]
    if not matches:
        return None
    return max(
        matches,
        key=lambda m: (_STRENGTH[m.kind], m.score, m.record.source == "invoice"),
    )
