"""THE ONLY code path that writes to `invoices` / `invoice_line_items` (rule 1).

It never trusts the caller: it reloads the latest extraction and re-runs every check itself.
- auto:  allowed only if the router would auto-approve.
- human: needs a logged-in user; every error rule must pass, except
         * a possible duplicate, which the user may override with a note, and
         * an unknown vendor, which is added to the vendor list (D19).
The invoice, its lines, the document status and the audit rows are committed together.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Invoice, InvoiceLineItem, Vendor
from app.pipeline.normalize import normalize_vendor_name
from app.services import audit
from app.services.assessment import assess, latest_extraction, store_assessment

ApprovalType = Literal["auto", "human"]
HUMAN_OVERRIDABLE = {"vendor_known"}


class ApprovalRefused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def _add_vendor(session: Session, name: str, user_id: uuid.UUID | None) -> Vendor:
    vendor = Vendor(name=name, normalized_name=normalize_vendor_name(name), aliases=[])
    session.add(vendor)
    session.flush()
    audit.record(
        session,
        entity_type="vendor",
        entity_id=vendor.id,
        action="vendor_created",
        user_id=user_id,
        new_value=name,
        note="Added automatically when its first invoice was approved (D19)",
    )
    return vendor


def approve(
    session: Session,
    document_id: uuid.UUID,
    *,
    approval_type: ApprovalType,
    user_id: uuid.UUID | None = None,
    note: str | None = None,
    today: date | None = None,
) -> Invoice:
    today = today or date.today()
    doc = session.get(Document, document_id)
    extraction = latest_extraction(session, document_id) if doc else None
    if doc is None or extraction is None:
        raise ApprovalRefused(["no_extraction"])
    if doc.status in ("approved", "auto_approved"):
        raise ApprovalRefused(["already_approved"])

    a = assess(session, doc, extraction, today)
    store_assessment(session, extraction, a)

    if approval_type == "auto":
        if a.decision != "auto_approve":
            raise ApprovalRefused(a.reasons)
    else:
        if user_id is None:
            raise ApprovalRefused(["login_required"])
        blocking = [
            r.rule
            for r in a.results
            if not r.passed
            and r.severity == "error"
            and r.rule not in HUMAN_OVERRIDABLE
            and not (r.rule == "not_duplicate" and note and note.strip())
        ]
        if blocking:
            raise ApprovalRefused(blocking)

    c = a.candidate
    assert c.vendor_name and c.invoice_number and c.invoice_date and c.total is not None
    number_normalized = c.invoice_number_normalized or c.invoice_number
    if c.vendor_id and session.scalar(
        select(Invoice.id).where(
            Invoice.vendor_id == c.vendor_id,
            Invoice.invoice_number_normalized == number_normalized,
        )
    ):
        # A duplicate note can't override this: the same vendor + number is already booked.
        raise ApprovalRefused(["already_recorded"])
    vendor_id = c.vendor_id or _add_vendor(session, c.vendor_name, user_id).id

    invoice = Invoice(
        document_id=doc.id,
        extraction_id=extraction.id,
        vendor_id=vendor_id,
        invoice_number=c.invoice_number,
        invoice_number_normalized=number_normalized,
        invoice_date=c.invoice_date,
        due_date=c.due_date,
        currency=c.currency or "INR",
        subtotal=c.subtotal,
        tax=c.tax,
        total=c.total,
        approval_type=approval_type,
        approved_by=user_id,
        approved_at=datetime.now(UTC),
    )
    session.add(invoice)
    session.flush()
    session.add_all(
        InvoiceLineItem(
            invoice_id=invoice.id,
            line_no=i + 1,
            description=line.description or "",
            quantity=line.quantity,
            unit_price=line.unit_price,
            amount=line.amount,
        )
        for i, line in enumerate(c.lines)
    )
    doc.status = "auto_approved" if approval_type == "auto" else "approved"
    doc.review_reasons = []
    audit.record(
        session,
        entity_type="document",
        entity_id=doc.id,
        action="auto_approved" if approval_type == "auto" else "approved",
        user_id=user_id,
        note=note,
    )
    session.commit()
    return invoice
