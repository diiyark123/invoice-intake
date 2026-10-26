"""Value normalization (spec §7): dates, amounts, invoice numbers, vendor names."""

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from dateutil import parser as date_parser
from rapidfuzz import fuzz

_VENDOR_SUFFIXES = {"pvt", "private", "ltd", "limited", "llc", "inc", "co"}
_CURRENCY_TOKENS = re.compile(r"(₹|rs\.?|inr|usd|eur|gbp|\$|€|£)", re.IGNORECASE)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INVOICE_PREFIXES = ("INVOICE", "INV", "NO", "#")
CENT = Decimal("0.01")


# ---------- dates ----------


def normalize_date(text: str | None) -> date | None:
    """Parse common date formats, preferring day-first (DD/MM/YYYY). Returns None if unparseable.

    ISO dates are handled first: dateutil with dayfirst=True reads 2026-03-12 as 3 December.
    """
    if not text or not text.strip():
        return None
    text = text.strip()
    try:
        if _ISO_DATE.match(text):
            return date.fromisoformat(text)
        return date_parser.parse(text, dayfirst=True).date()
    except (ValueError, OverflowError):
        return None


# ---------- amounts ----------


def _parse_number(text: str) -> Decimal | None:
    """Parse a bare number with any mix of thousands/decimal separators. Not rounded."""
    s = _CURRENCY_TOKENS.sub("", text).replace(" ", "").replace("\u00a0", "").strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = True, s[1:]
    s = s.rstrip(".")  # "Rs. 100." style trailing dot
    if not s or not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        return None

    if "," in s and "." in s:
        # Whichever separator comes last is the decimal point.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # A single comma followed by 1-2 digits at the end is a decimal comma ("12,50").
        if s.count(",") == 1 and re.search(r",\d{1,2}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")  # "1.234.567" thousands dots

    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def normalize_amount(text: str | None) -> Decimal | None:
    """'₹ 1,23,456.00' -> 123456.00, '1.234,56' -> 1234.56. None if not a clean amount."""
    if text is None:
        return None
    value = _parse_number(str(text))
    return None if value is None else value.quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_quantity(text: str | None) -> Decimal | None:
    """Up to 3 decimals; ignores a trailing unit ('24.5 L' -> 24.500)."""
    if text is None:
        return None
    match = re.match(r"^\s*(-?[\d.,]+)", str(text))
    value = _parse_number(match.group(1)) if match else None
    return None if value is None else value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# ---------- currency ----------

_CURRENCY_ALIASES = {
    "INR": "INR",
    "RS": "INR",
    "RUPEES": "INR",
    "₹": "INR",
    "USD": "USD",
    "$": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
}


def normalize_currency(text: str | None) -> str | None:
    """'Rs.' / '₹' / '(INR)' -> 'INR'. Unknown 3-letter codes pass through uppercased."""
    if not text:
        return None
    s = re.sub(r"[\s().:,]", "", text.upper())  # OCR often reads "Rs." as "Rs,"
    if s in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[s]
    return s if re.fullmatch(r"[A-Z]{3}", s) else None


# ---------- invoice numbers ----------


def normalize_invoice_number(text: str | None) -> str | None:
    """Uppercase, strip spaces, the prefixes INV/INVOICE/NO/#, and leading zeros.

    'INV-0042' -> '42', 'Invoice No. 00123' -> '123', 'MS/26-27/0042' -> 'MS/26-27/0042'
    """
    if not text:
        return None
    s = re.sub(r"\s+", "", text.upper())
    changed = True
    while changed:
        changed = False
        for prefix in _INVOICE_PREFIXES:
            if s.startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix) :].lstrip(".:-_/#")
                changed = True
    s = s.lstrip("0")
    return s or "0"


# ---------- vendors ----------


def normalize_vendor_name(name: str) -> str:
    """Lowercase, drop punctuation and company suffixes, collapse spaces.

    >>> normalize_vendor_name("Acme Traders Pvt. Ltd.")
    'acme traders'
    """
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    words = [w for w in cleaned.split() if w not in _VENDOR_SUFFIXES]
    return " ".join(words)


@dataclass(frozen=True)
class VendorRef:
    id: uuid.UUID
    normalized_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class VendorMatch:
    vendor_id: uuid.UUID
    method: str  # exact | alias | fuzzy
    score: float  # 0-1


FUZZY_VENDOR_THRESHOLD = 90


def match_vendor(name: str | None, vendors: list[VendorRef]) -> VendorMatch | None:
    """Exact normalized name, then aliases, then rapidfuzz token_sort_ratio >= 90."""
    if not name:
        return None
    target = normalize_vendor_name(name)
    if not target:
        return None
    for v in vendors:
        if v.normalized_name == target:
            return VendorMatch(v.id, "exact", 1.0)
    for v in vendors:
        if any(normalize_vendor_name(a) == target for a in v.aliases):
            return VendorMatch(v.id, "alias", 1.0)
    best: VendorMatch | None = None
    for v in vendors:
        for candidate in (v.normalized_name, *(normalize_vendor_name(a) for a in v.aliases)):
            score = fuzz.token_sort_ratio(target, candidate)
            if score >= FUZZY_VENDOR_THRESHOLD and (best is None or score / 100 > best.score):
                best = VendorMatch(v.id, "fuzzy", score / 100)
    return best
