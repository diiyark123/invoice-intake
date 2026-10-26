"""Human review: queue, field corrections, approve, reject (spec §11). Every action is audited."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_user
from app.db import get_session
from app.models import Document, ExtractedField
from app.pipeline.orchestrator import LINE_FIELDS, normalize_field
from app.pipeline.router import NON_RULE_REASONS
from app.pipeline.validate import field_key
from app.schemas import (
    ApproveRequest,
    DocumentSummary,
    FieldCorrections,
    QueueItem,
    RejectRequest,
)
from app.services import audit
from app.services.approval import ApprovalRefused, approve
from app.services.assessment import (
    assess,
    extraction_fields,
    latest_extraction,
    store_assessment,
)

router = APIRouter(prefix="/review", tags=["review"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[CurrentUser, Depends(require_user)]
HEADER_EDITABLE = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
)
HUMAN_SOURCE_MATCH = 1.0  # D23: a value typed by a reviewer counts as fully confident


def _reviewable(session: Session, document_id: uuid.UUID) -> Document:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if doc.status != "needs_review":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only documents in review can be changed (this one is {doc.status})",
        )
    return doc


@router.get("/queue")
def review_queue(session: SessionDep, _: UserDep) -> list[QueueItem]:
    """Documents waiting for a person, oldest first."""
    now = datetime.now(UTC)
    docs = session.scalars(
        select(Document).where(Document.status == "needs_review").order_by(Document.created_at)
    )
    items = []
    for d in docs:
        header: dict[str, str | None] = {}
        ex = latest_extraction(session, d.id)
        if ex is not None:
            header = {
                f.field_name: f.value_text
                for f in extraction_fields(session, ex.id)
                if f.line_item_index is None
            }
        items.append(
            QueueItem(
                id=d.id,
                filename=d.filename,
                vendor_name=header.get("vendor_name"),
                invoice_number=header.get("invoice_number"),
                total=header.get("total"),
                review_reasons=list(d.review_reasons or []),
                created_at=d.created_at,
                age_seconds=int((now - d.created_at).total_seconds()),
            )
        )
    return items


@router.patch("/{document_id}/fields")
def correct_fields(
    document_id: uuid.UUID, body: FieldCorrections, session: SessionDep, user: UserDep
) -> DocumentSummary:
    """Apply corrections, audit each one, then re-run every check (D23)."""
    doc = _reviewable(session, document_id)
    extraction = latest_extraction(session, document_id)
    if extraction is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing extracted yet")
    rows = {(f.field_name, f.line_item_index): f for f in extraction_fields(session, extraction.id)}

    for index in sorted(set(body.delete_lines)):
        line_rows = [f for (_, i), f in rows.items() if i == index]
        if not line_rows:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"No line {index}")
        old = ", ".join(f"{f.field_name}={f.value_text}" for f in line_rows)
        for f in line_rows:
            session.delete(f)
            del rows[(f.field_name, index)]
        audit.record(
            session,
            entity_type="document",
            entity_id=doc.id,
            action="field_corrected",
            user_id=user.id,
            field_name=f"line_items.{index}",
            old_value=old,
            new_value=None,
            note="line deleted",
        )

    for change in body.changes:
        allowed = LINE_FIELDS if change.line_item_index is not None else HEADER_EDITABLE
        if change.field_name not in allowed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown field {change.field_name}"
            )
        value = change.value.strip() if change.value and change.value.strip() else None
        key = (change.field_name, change.line_item_index)
        row = rows.get(key)
        if row is None:
            row = ExtractedField(
                extraction_id=extraction.id,
                field_name=change.field_name,
                line_item_index=change.line_item_index,
            )
            session.add(row)
            rows[key] = row
        elif row.value_text == value:
            continue
        old_value = row.value_text
        row.value_text = value
        row.normalized_value = normalize_field(change.field_name, value)
        row.source_match = HUMAN_SOURCE_MATCH if value is not None else 0.0
        audit.record(
            session,
            entity_type="document",
            entity_id=doc.id,
            action="field_corrected",
            user_id=user.id,
            field_name=field_key(change.field_name, change.line_item_index),
            old_value=old_value,
            new_value=value,
        )

    session.flush()
    keep = [r for r in (doc.review_reasons or []) if r in NON_RULE_REASONS]
    a = assess(session, doc, extraction, datetime.now(UTC).date(), keep)
    store_assessment(session, extraction, a)
    doc.review_reasons = a.reasons
    session.commit()
    return DocumentSummary.model_validate(doc)


@router.post("/{document_id}/approve")
def approve_document(
    document_id: uuid.UUID, body: ApproveRequest, session: SessionDep, user: UserDep
) -> DocumentSummary:
    """Re-validates the current values; a possible duplicate can be overridden with a note."""
    doc = _reviewable(session, document_id)
    try:
        approve(session, doc.id, approval_type="human", user_id=user.id, note=body.note)
    except ApprovalRefused as refused:
        session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "This invoice can't be approved yet", "reasons": refused.reasons},
        ) from refused
    session.refresh(doc)
    return DocumentSummary.model_validate(doc)


@router.post("/{document_id}/reject")
def reject_document(
    document_id: uuid.UUID, body: RejectRequest, session: SessionDep, user: UserDep
) -> DocumentSummary:
    doc = _reviewable(session, document_id)
    doc.status = "rejected"
    audit.record(
        session,
        entity_type="document",
        entity_id=doc.id,
        action="rejected",
        user_id=user.id,
        note=body.reason.strip(),
    )
    session.commit()
    return DocumentSummary.model_validate(doc)
