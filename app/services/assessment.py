"""Load what the pure checks need from the DB, run them, and store the outcome on the staging rows.

Used by the orchestrator (after extraction) and by approval.py (which re-checks before writing).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSettings, Document, ExtractedField, Extraction, Invoice, Vendor
from app.pipeline.confidence import FieldInput, score_fields
from app.pipeline.duplicates import DupCandidate, DuplicateMatch, DupRecord, find_duplicate
from app.pipeline.normalize import VendorRef, match_vendor, normalize_vendor_name
from app.pipeline.router import Decision, RoutingPolicy, route
from app.pipeline.validate import Candidate, RuleResult, RuleSettings, field_key, validate

OPEN_STATUSES = ("needs_review", "processing")


@dataclass
class Assessment:
    candidate: Candidate
    results: list[RuleResult]
    duplicate: DuplicateMatch | None
    scores: dict[str, float | None]
    overall: float
    decision: Decision
    reasons: list[str]


def load_settings(session: Session) -> AppSettings:
    return session.scalar(select(AppSettings)) or AppSettings(
        confidence_threshold=0.85,
        require_review_for_new_vendor=True,
        amount_tolerance=Decimal("0.01"),
        max_due_days=180,
    )


def load_vendor_refs(session: Session) -> list[VendorRef]:
    vendors = session.scalars(select(Vendor).where(Vendor.is_active.is_(True)))
    return [VendorRef(v.id, v.normalized_name, tuple(v.aliases or ())) for v in vendors]


def latest_extraction(session: Session, document_id: uuid.UUID) -> Extraction | None:
    return session.scalar(
        select(Extraction)
        .where(Extraction.document_id == document_id)
        .order_by(Extraction.created_at.desc())
        .limit(1)
    )


def extraction_fields(session: Session, extraction_id: uuid.UUID) -> list[ExtractedField]:
    return list(
        session.scalars(select(ExtractedField).where(ExtractedField.extraction_id == extraction_id))
    )


def duplicate_records(session: Session, exclude_document_id: uuid.UUID) -> list[DupRecord]:
    """Approved invoices plus documents still open (needs_review / processing)."""
    records: list[DupRecord] = []
    approved = session.execute(
        select(Invoice, Document.sha256, Vendor.normalized_name)
        .join(Document, Document.id == Invoice.document_id)
        .join(Vendor, Vendor.id == Invoice.vendor_id)
        .where(Invoice.document_id != exclude_document_id)
    )
    for inv, sha, vendor_name in approved:
        records.append(
            DupRecord(
                "invoice",
                inv.document_id,
                inv.id,
                sha,
                inv.vendor_id,
                vendor_name,
                inv.invoice_number_normalized,
                inv.invoice_date,
                inv.total,
            )
        )

    open_docs = session.scalars(
        select(Document).where(
            Document.status.in_(OPEN_STATUSES), Document.id != exclude_document_id
        )
    ).all()
    for d in open_docs:
        ex = latest_extraction(session, d.id)
        norm = {}
        if ex is not None:
            norm = {
                f.field_name: f.normalized_value
                for f in extraction_fields(session, ex.id)
                if f.line_item_index is None
            }
        records.append(
            DupRecord(
                "document",
                d.id,
                None,
                d.sha256,
                None,
                norm.get("vendor_name"),
                norm.get("invoice_number"),
                date.fromisoformat(norm["invoice_date"]) if norm.get("invoice_date") else None,
                Decimal(norm["total"]) if norm.get("total") else None,
            )
        )
    return records


def assess(
    session: Session,
    document: Document,
    extraction: Extraction,
    today: date,
    extra_reasons: list[str] | None = None,
) -> Assessment:
    settings = load_settings(session)
    fields = extraction_fields(session, extraction.id)
    vendor_name = next(
        (
            f.value_text
            for f in fields
            if f.field_name == "vendor_name" and f.line_item_index is None
        ),
        None,
    )
    match = match_vendor(vendor_name, load_vendor_refs(session))
    candidate = Candidate.from_fields(
        ((f.field_name, f.value_text, f.normalized_value, f.line_item_index) for f in fields),
        match.vendor_id if match else None,
    )

    duplicate = find_duplicate(
        DupCandidate(
            sha256=document.sha256,
            vendor_id=candidate.vendor_id,
            vendor_name_normalized=normalize_vendor_name(vendor_name) if vendor_name else None,
            invoice_number_normalized=candidate.invoice_number_normalized,
            invoice_date=candidate.invoice_date,
            total=candidate.total,
        ),
        duplicate_records(session, document.id),
    )
    results = validate(
        candidate,
        RuleSettings(Decimal(settings.amount_tolerance), settings.max_due_days),
        today,
        duplicate.message if duplicate else None,
    )
    if not settings.require_review_for_new_vendor:
        # D19: the manager allows new vendors, so an unknown vendor is only a warning and
        # must not lower the vendor name's confidence either.
        results = [
            replace(r, severity="warning") if r.rule == "vendor_known" else r for r in results
        ]
    scores, overall = score_fields(
        [
            FieldInput(
                f.field_name,
                f.line_item_index,
                f.value_text,
                f.normalized_value,
                f.source_match or 0.0,
            )
            for f in fields
        ],
        results,
    )
    header_scores = {k: v for k, v in scores.items() if not k.startswith("line_items.")}
    decision, reasons = route(
        results,
        header_scores,
        RoutingPolicy(settings.confidence_threshold, settings.require_review_for_new_vendor),
        extra_reasons,
    )
    return Assessment(candidate, results, duplicate, scores, overall, decision, reasons)


def store_assessment(session: Session, extraction: Extraction, a: Assessment) -> None:
    """Write confidences, rule results and the duplicate link onto the staging rows."""
    for f in extraction_fields(session, extraction.id):
        f.confidence = a.scores.get(field_key(f.field_name, f.line_item_index))
    extraction.validation_results = [r.to_dict() for r in a.results]
    extraction.overall_confidence = a.overall
    extraction.duplicate_of_invoice_id = a.duplicate.record.invoice_id if a.duplicate else None
    extraction.duplicate_of_document_id = (
        a.duplicate.record.document_id
        if a.duplicate and a.duplicate.record.source == "document"
        else None
    )
    extraction.duplicate_score = a.duplicate.score if a.duplicate else None
