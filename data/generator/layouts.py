"""Five visually different invoice layouts drawn with reportlab.

Each layout prints dates and amounts in its own style, so the extractor sees realistic variety.
Every value in the label is printed somewhere on the page (copy-exactly-as-printed rule).
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from data.generator.model import BUYER, InvoiceData, fmt_qty

Layout = Callable[[str, InvoiceData], None]


# ---------- formatting helpers ----------


def western(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def indian(amount: Decimal) -> str:
    """Indian digit grouping: 1234567.50 -> 12,34,567.50"""
    whole, frac = f"{amount:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail]) + "." + frac


def d_slash(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def d_mon(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def d_long(d: date) -> str:
    return d.strftime("%d %B %Y")


def d_iso(d: date) -> str:
    return d.isoformat()


def d_dots(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _canvas(path: str, size: tuple[float, float] = A4) -> Canvas:
    # invariant=1 removes timestamps/random ids, so the same seed gives identical bytes.
    c = Canvas(path, pagesize=size, invariant=1)
    c.setAuthor("synthetic")
    return c


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "."


# ---------- layout 1: classic bordered table ----------


def classic(path: str, inv: InvoiceData) -> None:
    c = _canvas(path)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 25 * mm, inv.vendor["name"])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 31 * mm, inv.vendor_address)
    c.drawString(20 * mm, h - 36 * mm, f"GSTIN: {inv.vendor['tax_id']}   Ph: {inv.vendor_phone}")

    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(w - 20 * mm, h - 25 * mm, "TAX INVOICE")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 20 * mm, h - 33 * mm, f"Invoice No: {inv.invoice_number}")
    c.drawRightString(w - 20 * mm, h - 39 * mm, f"Invoice Date: {d_slash(inv.invoice_date)}")
    if inv.due_date:
        c.drawRightString(w - 20 * mm, h - 45 * mm, f"Due Date: {d_slash(inv.due_date)}")

    c.rect(20 * mm, h - 70 * mm, 90 * mm, 20 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22 * mm, h - 55 * mm, "Bill To:")
    c.setFont("Helvetica", 9)
    c.drawString(22 * mm, h - 60 * mm, BUYER["name"])
    c.drawString(22 * mm, h - 65 * mm, _clip(BUYER["address"], 60))

    cols = [20, 30, 110, 130, 160, 190]  # mm x positions of column edges
    top = h - 80 * mm
    row_h = 8 * mm
    c.setFillColor(colors.lightgrey)
    c.rect(20 * mm, top - row_h, 170 * mm, row_h, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for x, title in zip(cols, ["#", "Description", "Qty", "Rate", "Amount"], strict=False):
        c.drawString((x + 2) * mm, top - row_h + 2.5 * mm, title)
    c.setFont("Helvetica", 9)
    y = top - row_h
    for i, li in enumerate(inv.lines, 1):
        y -= row_h
        c.rect(20 * mm, y, 170 * mm, row_h)
        c.drawString(22 * mm, y + 2.5 * mm, str(i))
        c.drawString(32 * mm, y + 2.5 * mm, _clip(li.description, 42))
        c.drawRightString(128 * mm, y + 2.5 * mm, fmt_qty(li.quantity))
        c.drawRightString(158 * mm, y + 2.5 * mm, western(li.unit_price))
        c.drawRightString(188 * mm, y + 2.5 * mm, western(li.amount))
    for x in cols:
        c.line(x * mm, top, x * mm, y)

    y -= 10 * mm
    for title, value in [
        ("Subtotal", inv.subtotal),
        (f"GST @ {inv.gst_rate}%", inv.tax),
        ("Total (INR)", inv.total),
    ]:
        c.setFont("Helvetica-Bold" if title.startswith("Total") else "Helvetica", 10)
        c.drawRightString(158 * mm, y, title)
        c.drawRightString(188 * mm, y, western(value))
        y -= 6 * mm

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, 20 * mm, "This is a computer generated invoice.")
    c.save()


# ---------- layout 2: modern minimal, no borders ----------


def modern(path: str, inv: InvoiceData) -> None:
    c = _canvas(path)
    w, h = A4
    accent = colors.HexColor("#2E5BBA")
    c.setFillColor(accent)
    c.rect(0, h - 12 * mm, w, 12 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)

    c.setFont("Helvetica", 28)
    c.drawString(20 * mm, h - 35 * mm, "Invoice")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(w - 20 * mm, h - 28 * mm, inv.vendor["name"])
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 20 * mm, h - 33 * mm, inv.vendor_address)
    c.drawRightString(w - 20 * mm, h - 38 * mm, f"GST {inv.vendor['tax_id']}")

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20 * mm, h - 50 * mm, "INVOICE NUMBER")
    c.drawString(75 * mm, h - 50 * mm, "DATE OF ISSUE")
    c.drawString(130 * mm, h - 50 * mm, "PAYMENT DUE")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, h - 56 * mm, inv.invoice_number)
    c.drawString(75 * mm, h - 56 * mm, d_long(inv.invoice_date))
    c.drawString(130 * mm, h - 56 * mm, d_long(inv.due_date) if inv.due_date else "On receipt")

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20 * mm, h - 68 * mm, "BILLED TO")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 74 * mm, BUYER["name"])

    y = h - 92 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(accent)
    for x, title, right in [
        (20, "DESCRIPTION", False),
        (125, "QTY", True),
        (155, "UNIT PRICE", True),
        (190, "AMOUNT", True),
    ]:
        (c.drawRightString if right else c.drawString)(x * mm, y, title)
    c.setFillColor(colors.black)
    c.setStrokeColor(accent)
    c.line(20 * mm, y - 2 * mm, 190 * mm, y - 2 * mm)
    c.setFont("Helvetica", 10)
    for li in inv.lines:
        y -= 9 * mm
        c.drawString(20 * mm, y, _clip(li.description, 50))
        c.drawRightString(125 * mm, y, f"{fmt_qty(li.quantity)} {li.unit}")
        c.drawRightString(155 * mm, y, western(li.unit_price))
        c.drawRightString(190 * mm, y, western(li.amount))
    c.line(110 * mm, y - 5 * mm, 190 * mm, y - 5 * mm)

    y -= 13 * mm
    for title, value in [("Subtotal", western(inv.subtotal)), ("Tax", western(inv.tax))]:
        c.drawString(125 * mm, y, title)
        c.drawRightString(190 * mm, y, value)
        y -= 7 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(125 * mm, y - 2 * mm, "Amount due")
    c.drawRightString(190 * mm, y - 2 * mm, f"INR {western(inv.total)}")
    c.save()


# ---------- layout 3: two-column header boxes ----------


def two_column(path: str, inv: InvoiceData) -> None:
    c = _canvas(path)
    w, h = A4
    c.setFont("Times-Bold", 18)
    c.drawCentredString(w / 2, h - 20 * mm, inv.vendor["name"].upper())
    c.setFont("Times-Roman", 9)
    c.drawCentredString(w / 2, h - 26 * mm, f"{inv.vendor_address}  |  {inv.vendor_phone}")
    c.line(15 * mm, h - 30 * mm, w - 15 * mm, h - 30 * mm)

    box_top = h - 35 * mm
    c.rect(15 * mm, box_top - 32 * mm, 87 * mm, 32 * mm)
    c.rect(108 * mm, box_top - 32 * mm, 87 * mm, 32 * mm)
    c.setFont("Times-Bold", 10)
    c.drawString(18 * mm, box_top - 6 * mm, "Supplier details")
    c.drawString(111 * mm, box_top - 6 * mm, "Invoice details")
    c.setFont("Times-Roman", 10)
    c.drawString(18 * mm, box_top - 13 * mm, f"GSTIN: {inv.vendor['tax_id']}")
    c.drawString(18 * mm, box_top - 19 * mm, f"Buyer: {BUYER['name']}")
    c.drawString(18 * mm, box_top - 25 * mm, f"Buyer GSTIN: {BUYER['tax_id']}")
    c.drawString(111 * mm, box_top - 13 * mm, f"Bill No. : {inv.invoice_number}")
    c.drawString(111 * mm, box_top - 19 * mm, f"Bill Date : {d_iso(inv.invoice_date)}")
    if inv.due_date:
        c.drawString(111 * mm, box_top - 25 * mm, f"Pay By : {d_iso(inv.due_date)}")

    y = box_top - 45 * mm
    c.setFont("Times-Bold", 10)
    heads = [(15, "S.No"), (30, "Particulars"), (120, "Quantity"), (145, "Price"), (172, "Value")]
    for x, t in heads:
        c.drawString(x * mm, y, t)
    c.line(15 * mm, y - 2 * mm, 195 * mm, y - 2 * mm)
    c.setFont("Times-Roman", 10)
    for i, li in enumerate(inv.lines, 1):
        y -= 7 * mm
        c.drawString(17 * mm, y, f"{i}.")
        c.drawString(30 * mm, y, _clip(li.description, 52))
        c.drawString(120 * mm, y, f"{fmt_qty(li.quantity)} {li.unit}")
        c.drawRightString(165 * mm, y, indian(li.unit_price))
        c.drawRightString(195 * mm, y, indian(li.amount))
    c.line(15 * mm, y - 3 * mm, 195 * mm, y - 3 * mm)

    y -= 11 * mm
    c.drawString(120 * mm, y, "Taxable Value")
    c.drawRightString(195 * mm, y, indian(inv.subtotal))
    c.drawString(120 * mm, y - 6 * mm, "GST")
    c.drawRightString(195 * mm, y - 6 * mm, indian(inv.tax))
    c.setFont("Times-Bold", 12)
    c.drawString(120 * mm, y - 14 * mm, "Grand Total Rs.")
    c.drawRightString(195 * mm, y - 14 * mm, indian(inv.total))
    c.setFont("Times-Italic", 9)
    c.drawString(15 * mm, 25 * mm, "For " + inv.vendor["name"])
    c.drawString(15 * mm, 15 * mm, "Authorised Signatory")
    c.save()


# ---------- layout 4: tax-heavy GST (CGST / SGST split) ----------


def gst_heavy(path: str, inv: InvoiceData) -> None:
    c = _canvas(path)
    w, h = A4
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w / 2, h - 15 * mm, "TAX INVOICE (Original for Recipient)")
    c.rect(12 * mm, h - 55 * mm, w - 24 * mm, 35 * mm)
    c.line(w / 2, h - 55 * mm, w / 2, h - 20 * mm)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15 * mm, h - 27 * mm, inv.vendor["name"])
    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, h - 32 * mm, inv.vendor_address)
    c.drawString(15 * mm, h - 37 * mm, f"GSTIN/UIN: {inv.vendor['tax_id']}")
    c.drawString(15 * mm, h - 42 * mm, f"State: {inv.vendor['city']}")
    c.setFont("Helvetica", 9)
    rx = w / 2 + 3 * mm
    c.drawString(rx, h - 27 * mm, f"Invoice No.   {inv.invoice_number}")
    c.drawString(rx, h - 33 * mm, f"Dated   {d_mon(inv.invoice_date)}")
    if inv.due_date:
        c.drawString(rx, h - 39 * mm, f"Due on   {d_mon(inv.due_date)}")
    c.drawString(rx, h - 45 * mm, f"Buyer: {BUYER['name']}")
    c.drawString(rx, h - 50 * mm, f"Buyer GSTIN: {BUYER['tax_id']}")

    y = h - 65 * mm
    c.setFont("Helvetica-Bold", 8)
    heads = [
        (14, "Sl"),
        (22, "Description of Goods"),
        (105, "HSN"),
        (122, "Qty"),
        (140, "Rate"),
        (165, "Amount"),
    ]
    for x, t in heads:
        c.drawString(x * mm, y, t)
    c.line(12 * mm, y - 2 * mm, w - 12 * mm, y - 2 * mm)
    c.setFont("Helvetica", 8)
    for i, li in enumerate(inv.lines, 1):
        y -= 6 * mm
        c.drawString(14 * mm, y, str(i))
        c.drawString(22 * mm, y, _clip(li.description, 48))
        c.drawString(105 * mm, y, str(8400 + i * 37))
        c.drawString(122 * mm, y, f"{fmt_qty(li.quantity)} {li.unit}")
        c.drawRightString(158 * mm, y, indian(li.unit_price))
        c.drawRightString(w - 14 * mm, y, indian(li.amount))
    c.line(12 * mm, y - 3 * mm, w - 12 * mm, y - 3 * mm)

    y -= 10 * mm
    half = inv.gst_rate / 2
    rows = [
        ("Taxable Value", inv.subtotal),
        (f"CGST @ {half}%", inv.cgst),
        (f"SGST @ {half}%", inv.sgst),
        ("Total Tax", inv.tax),
    ]
    for title, value in rows:
        c.drawString(122 * mm, y, title)
        c.drawRightString(w - 14 * mm, y, indian(value))
        y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(122 * mm, y - 2 * mm, "Invoice Total")
    c.drawRightString(w - 14 * mm, y - 2 * mm, f"Rs. {indian(inv.total)}")

    y -= 18 * mm
    c.setFont("Helvetica-Bold", 7)
    c.drawString(14 * mm, y, "HSN-wise tax summary")
    c.setFont("Helvetica", 7)
    c.drawString(14 * mm, y - 4 * mm, f"Rate {inv.gst_rate}%  |  CGST {half}%  |  SGST {half}%")
    c.setFont("Helvetica", 7)
    c.drawString(
        14 * mm, 18 * mm, "Declaration: We declare that this invoice shows the actual price"
    )
    c.drawString(
        14 * mm, 14 * mm, "of the goods described and that all particulars are true and correct."
    )
    c.save()


# ---------- layout 5: compact thermal-style receipt ----------


def thermal(path: str, inv: InvoiceData) -> None:
    width = 80 * mm
    height = (110 + 10 * len(inv.lines)) * mm
    c = _canvas(path, (width, height))
    y = height - 10 * mm
    c.setFont("Courier-Bold", 9)
    c.drawCentredString(width / 2, y, _clip(inv.vendor["name"], 34))
    c.setFont("Courier", 7)
    y -= 4 * mm
    c.drawCentredString(width / 2, y, _clip(inv.vendor_address, 44))
    y -= 4 * mm
    c.drawCentredString(width / 2, y, f"GSTIN {inv.vendor['tax_id']}")
    y -= 6 * mm
    c.drawString(4 * mm, y, "-" * 44)
    y -= 4 * mm
    c.drawString(4 * mm, y, f"Inv#: {inv.invoice_number}")
    y -= 4 * mm
    c.drawString(4 * mm, y, f"Date: {d_dots(inv.invoice_date)}")
    if inv.due_date:
        y -= 4 * mm
        c.drawString(4 * mm, y, f"Due : {d_dots(inv.due_date)}")
    y -= 4 * mm
    c.drawString(4 * mm, y, "-" * 44)
    for li in inv.lines:
        y -= 4 * mm
        c.drawString(4 * mm, y, _clip(li.description, 40))
        y -= 4 * mm
        c.drawString(6 * mm, y, f"{fmt_qty(li.quantity)} x {li.unit_price:.2f}")
        c.drawRightString(width - 4 * mm, y, f"{li.amount:.2f}")
        y -= 2 * mm
    y -= 3 * mm
    c.drawString(4 * mm, y, "-" * 44)
    for title, value in [("SUBTOTAL", inv.subtotal), ("GST", inv.tax)]:
        y -= 4 * mm
        c.drawString(4 * mm, y, title)
        c.drawRightString(width - 4 * mm, y, f"{value:.2f}")
    y -= 5 * mm
    c.setFont("Courier-Bold", 9)
    c.drawString(4 * mm, y, "TOTAL INR")
    c.drawRightString(width - 4 * mm, y, f"{inv.total:.2f}")
    y -= 8 * mm
    c.setFont("Courier", 7)
    c.drawCentredString(width / 2, y, "Thank you! Visit again")
    c.save()


LAYOUTS: dict[str, Layout] = {
    "classic": classic,
    "modern": modern,
    "two_column": two_column,
    "gst_heavy": gst_heavy,
    "thermal": thermal,
}
