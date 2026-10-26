"""Business rules (spec §8). One pure function per rule; `validate` runs them all.

Rules take a `Candidate`: typed, normalized values rebuilt from the stored fields, so the
orchestrator and the approval service check exactly the same thing.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

Severity = Literal["error", "warning"]
REQUIRED_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "total")
MAX_INVOICE_AGE_DAYS = 730  # "not older than 2 years"


def field_key(field_name: str, line_item_index: int | None) -> str:
    """'total' for header fields, 'line_items.2.amount' for line-item fields."""
    return field_name if line_item_index is None else f"line_items.{line_item_index}.{field_name}"


@dataclass(frozen=True)
class CandidateLine:
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


@dataclass(frozen=True)
class Candidate:
    vendor_name: str | None = None
    vendor_id: uuid.UUID | None = None  # set when matched to the vendors table
    invoice_number: str | None = None
    invoice_number_normalized: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    lines: tuple[CandidateLine, ...] = ()

    @classmethod
    def from_fields(
        cls,
        rows: Iterable[tuple[str, str | None, str | None, int | None]],
        vendor_id: uuid.UUID | None,
    ) -> "Candidate":
        """Build from (field_name, value_text, normalized_value, line_item_index) rows."""
        header: dict[str, tuple[str | None, str | None]] = {}
        lines: dict[int, dict[str, str | None]] = {}
        for name, raw, norm, index in rows:
            if index is None:
                header[name] = (raw, norm)
            else:
                lines.setdefault(index, {})[name] = norm

        def norm(name: str) -> str | None:
            return header.get(name, (None, None))[1]

        def dec(value: str | None) -> Decimal | None:
            return Decimal(value) if value not in (None, "") else None

        def day(value: str | None) -> date | None:
            return date.fromisoformat(value) if value else None

        return cls(
            vendor_name=header.get("vendor_name", (None, None))[0],
            vendor_id=vendor_id,
            invoice_number=header.get("invoice_number", (None, None))[0],
            invoice_number_normalized=norm("invoice_number"),
            invoice_date=day(norm("invoice_date")),
            due_date=day(norm("due_date")),
            currency=norm("currency"),
            subtotal=dec(norm("subtotal")),
            tax=dec(norm("tax")),
            total=dec(norm("total")),
            lines=tuple(
                CandidateLine(
                    description=lines[i].get("description"),
                    quantity=dec(lines[i].get("quantity")),
                    unit_price=dec(lines[i].get("unit_price")),
                    amount=dec(lines[i].get("amount")),
                )
                for i in sorted(lines)
            ),
        )


@dataclass(frozen=True)
class RuleSettings:
    amount_tolerance: Decimal = Decimal("0.01")
    max_due_days: int = 180


@dataclass(frozen=True)
class RuleResult:
    rule: str
    passed: bool
    message: str
    fields: tuple[str, ...] = field(default_factory=tuple)
    severity: Severity = "error"

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "message": self.message,
            "fields": list(self.fields),
            "severity": self.severity,
        }


def _ok(rule: str, message: str = "OK") -> RuleResult:
    return RuleResult(rule, True, message)


def _money(d: Decimal | None) -> str:
    return "missing" if d is None else f"{d:,.2f}"


# ---------- the rules ----------


def required_fields(c: Candidate) -> RuleResult:
    missing = tuple(f for f in REQUIRED_FIELDS if getattr(c, f) in (None, ""))
    if missing:
        return RuleResult("required_fields", False, f"Missing: {', '.join(missing)}", missing)
    return _ok("required_fields")


def line_items_sum(c: Candidate, s: RuleSettings) -> RuleResult:
    if not c.lines:
        return RuleResult("line_items_sum", False, "No line items to check", (), severity="warning")
    amounts = [li.amount for li in c.lines]
    line_keys = tuple(field_key("amount", i) for i in range(len(c.lines)))
    if c.subtotal is None or any(a is None for a in amounts):
        return RuleResult(
            "line_items_sum",
            False,
            "Subtotal or a line amount is missing",
            ("subtotal", *line_keys),
        )
    total = sum(amounts, Decimal("0"))  # type: ignore[arg-type]
    if abs(total - c.subtotal) > s.amount_tolerance:
        return RuleResult(
            "line_items_sum",
            False,
            f"Line amounts add up to {_money(total)}, but subtotal is {_money(c.subtotal)}",
            ("subtotal", *line_keys),
        )
    return _ok("line_items_sum")


def line_math(c: Candidate, s: RuleSettings) -> RuleResult:
    bad: list[str] = []
    messages = []
    for i, li in enumerate(c.lines):
        if li.quantity is None or li.unit_price is None:
            continue
        expected = li.quantity * li.unit_price
        if li.amount is None or abs(expected - li.amount) > s.amount_tolerance:
            bad += [field_key(f, i) for f in ("quantity", "unit_price", "amount")]
            messages.append(
                f"line {i + 1}: {li.quantity.normalize()} x {li.unit_price} = "
                f"{_money(expected)}, not {_money(li.amount)}"
            )
    if bad:
        return RuleResult("line_math", False, "; ".join(messages), tuple(bad))
    return _ok("line_math")


def totals_math(c: Candidate, s: RuleSettings) -> RuleResult:
    if c.subtotal is None or c.total is None:
        return RuleResult(
            "totals_math", False, "Subtotal or total is missing", ("subtotal", "tax", "total")
        )
    tax = c.tax or Decimal("0")
    if abs(c.subtotal + tax - c.total) > s.amount_tolerance:
        return RuleResult(
            "totals_math",
            False,
            f"Subtotal {_money(c.subtotal)} + tax {_money(tax)} = {_money(c.subtotal + tax)}, "
            f"but total is {_money(c.total)}",
            ("subtotal", "tax", "total"),
        )
    return _ok("totals_math")


def positive_amounts(c: Candidate) -> RuleResult:
    if c.total is None or c.total <= 0:
        return RuleResult("positive_amounts", False, "Total must be more than zero", ("total",))
    return _ok("positive_amounts")


def date_valid(c: Candidate, today: date) -> RuleResult:
    d = c.invoice_date
    if d is None:
        return RuleResult(
            "date_valid", False, "Invoice date is missing or unreadable", ("invoice_date",)
        )
    if d > today:
        return RuleResult(
            "date_valid", False, f"Invoice date {d} is in the future", ("invoice_date",)
        )
    if d < today - timedelta(days=MAX_INVOICE_AGE_DAYS):
        return RuleResult(
            "date_valid", False, f"Invoice date {d} is more than 2 years ago", ("invoice_date",)
        )
    return _ok("date_valid")


def due_after_invoice(c: Candidate, s: RuleSettings) -> RuleResult:
    if c.due_date is None or c.invoice_date is None:
        return _ok("due_after_invoice", "No due date to check")
    if c.due_date < c.invoice_date:
        return RuleResult(
            "due_after_invoice",
            False,
            "Due date is before the invoice date",
            ("due_date", "invoice_date"),
        )
    if c.due_date > c.invoice_date + timedelta(days=s.max_due_days):
        return RuleResult(
            "due_after_invoice",
            False,
            f"Due date is more than {s.max_due_days} days after the invoice date",
            ("due_date",),
        )
    return _ok("due_after_invoice")


def vendor_known(c: Candidate) -> RuleResult:
    if c.vendor_id is None:
        return RuleResult(
            "vendor_known",
            False,
            f"Vendor '{c.vendor_name}' is not in the vendor list",
            ("vendor_name",),
        )
    return _ok("vendor_known")


def not_duplicate(duplicate_message: str | None) -> RuleResult:
    if duplicate_message:
        return RuleResult(
            "not_duplicate",
            False,
            duplicate_message,
            ("vendor_name", "invoice_number", "invoice_date", "total"),
        )
    return _ok("not_duplicate")


def validate(
    c: Candidate,
    settings: RuleSettings,
    today: date,
    duplicate_message: str | None = None,
) -> list[RuleResult]:
    return [
        required_fields(c),
        line_items_sum(c, settings),
        line_math(c, settings),
        totals_math(c, settings),
        positive_amounts(c),
        date_valid(c, today),
        due_after_invoice(c, settings),
        vendor_known(c),
        not_duplicate(duplicate_message),
    ]
