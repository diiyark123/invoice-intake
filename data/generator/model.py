"""Random but internally consistent invoice data, plus its §7 label.

All money is Decimal and every total adds up exactly (subtotal + tax = total).
"""

import random
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from faker import Faker

from app.seed_data import KNOWN_VENDORS, VendorSeed

CENT = Decimal("0.01")

BUYER = {
    "name": "Meridian Supplies Pvt Ltd",
    "address": "Plot 14, MIDC Industrial Area, Andheri East, Mumbai 400093",
    "tax_id": "27AAECM4321B1Z6",
}

# (description, unit, min price, max price, allows fractional qty)
CATALOG: list[tuple[str, str, int, int, bool]] = [
    ("Corrugated carton box 18x12x10", "pcs", 18, 65, False),
    ("Stretch wrap film 500mm", "roll", 350, 900, False),
    ("Hex bolt M10 x 50 (box of 100)", "box", 420, 780, False),
    ("Nitrile safety gloves", "pair", 45, 120, False),
    ("A4 copier paper 75 GSM", "ream", 240, 330, False),
    ("Industrial degreaser 5L", "can", 650, 1400, False),
    ("Copper wire 2.5 sq mm", "m", 22, 48, True),
    ("MS angle 40x40x5", "kg", 58, 82, True),
    ("Laser toner cartridge", "pcs", 1800, 4200, False),
    ("Floor cleaning liquid 1L", "btl", 90, 210, False),
    ("Safety helmet ISI marked", "pcs", 180, 450, False),
    ("Packing tape 48mm x 65m", "roll", 38, 75, False),
    ("Courier charges - domestic", "shp", 120, 650, False),
    ("Annual maintenance - printers", "job", 4500, 15000, False),
    ("LED tube light 20W", "pcs", 160, 340, False),
    ("Pallet wooden 1200x1000", "pcs", 650, 1200, False),
    ("Canteen meal vouchers", "pcs", 60, 140, False),
    ("Hydraulic oil 68 grade", "L", 140, 260, True),
    ("Shrink sleeves printing", "pcs", 2, 9, False),
    ("Fire extinguisher refill 4kg", "pcs", 550, 950, False),
]

GST_RATES = [Decimal("5"), Decimal("12"), Decimal("18")]
PAYMENT_TERMS = [15, 30, 45, 60]


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_qty(q: Decimal) -> str:
    """Print a quantity without trailing zeros: 3 -> '3', 2.50 -> '2.5'."""
    return format(q.normalize(), "f")


@dataclass
class LineItem:
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)


@dataclass
class InvoiceData:
    vendor: VendorSeed
    vendor_address: str
    vendor_phone: str
    invoice_number: str
    invoice_date: date
    due_date: date | None
    currency: str
    gst_rate: Decimal
    lines: list[LineItem] = field(default_factory=list)
    doc_class: str = "invoice"

    @property
    def subtotal(self) -> Decimal:
        return sum((li.amount for li in self.lines), Decimal("0.00"))

    @property
    def cgst(self) -> Decimal:
        return money(self.subtotal * self.gst_rate / 2 / 100)

    @property
    def sgst(self) -> Decimal:
        return self.cgst

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tax

    def label(self) -> dict[str, Any]:
        """The ground-truth label, in the §7 extraction schema plus doc_class (D3)."""
        return {
            "doc_class": self.doc_class,
            "vendor_name": self.vendor["name"],
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "currency": self.currency,
            "subtotal": f"{self.subtotal:.2f}",
            "tax": f"{self.tax:.2f}",
            "total": f"{self.total:.2f}",
            "line_items": [
                {
                    "description": li.description,
                    "quantity": fmt_qty(li.quantity),
                    "unit_price": f"{li.unit_price:.2f}",
                    "amount": f"{li.amount:.2f}",
                }
                for li in self.lines
            ],
        }


def _invoice_number(rng: random.Random, inv_date: date) -> str:
    n = rng.randint(1, 9999)
    style = rng.randrange(5)
    if style == 0:
        return f"INV-{inv_date.year}-{n:04d}"
    if style == 1:
        return f"MS/{inv_date.year % 100}-{inv_date.year % 100 + 1}/{n:04d}"
    if style == 2:
        return f"{rng.choice('ABCDEFGH')}-{rng.randint(10000, 99999)}"
    if style == 3:
        return f"{rng.randint(1000, 999999):07d}"
    return f"INV{n:05d}"


def make_invoice(
    rng: random.Random,
    faker: Faker,
    today: date,
    vendors: list[VendorSeed] | None = None,
) -> InvoiceData:
    vendor = rng.choice(vendors or KNOWN_VENDORS)
    inv_date = today - timedelta(days=rng.randint(1, 365))
    due = inv_date + timedelta(days=rng.choice(PAYMENT_TERMS)) if rng.random() < 0.85 else None

    lines = []
    for desc, unit, lo, hi, fractional in rng.sample(CATALOG, rng.randint(1, 8)):
        if fractional:
            qty = Decimal(rng.randint(5, 400)) / Decimal(rng.choice([1, 2, 10]))
        else:
            qty = Decimal(rng.choice([1, 1, 2, 3, 4, 5, 6, 10, 12, 20, 24, 50, 100]))
        price = money(Decimal(rng.randint(lo * 100, hi * 100)) / 100)
        lines.append(LineItem(desc, unit, qty, price))

    return InvoiceData(
        vendor=vendor,
        vendor_address=f"{faker.building_number()}, {faker.street_name()}, {vendor['city']}",
        vendor_phone=f"+91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}",
        invoice_number=_invoice_number(rng, inv_date),
        invoice_date=inv_date,
        due_date=due,
        currency="INR",
        gst_rate=rng.choice(GST_RATES),
        lines=lines,
    )


def with_changes(inv: InvoiceData, **changes: Any) -> InvoiceData:
    """Copy an invoice with some fields changed (used to build seeded duplicates)."""
    return replace(inv, **changes)
