"""Upload, list, inspect and retry documents (spec §11)."""

import hashlib
import uuid
from datetime import UTC, date, datetime, time
from pathlib import PurePath
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_user
from app.config import get_settings
from app.db import get_session
from app.models import Document, ExtractedField, Extraction, Invoice
from app.pipeline.ingest import MIME_TYPES, UnsupportedFileError, detect_type
from app.pipeline.orchestrator import PipelineDeps, default_deps, page_image_key, process_document
from app.schemas import DocumentDetail, DocumentSummary, ExtractionOut, FieldOut, UploadResult
from app.services import audit
from app.services.assessment import latest_extraction, load_settings

router = APIRouter(prefix="/documents", tags=["documents"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[CurrentUser, Depends(require_user)]


def get_pipeline_deps() -> PipelineDeps:
    """Dependency so tests can swap in a fake LLM, temp storage and a test database."""
    return default_deps()


DepsDep = Annotated[PipelineDeps, Depends(get_pipeline_deps)]


def _get_document(session: Session, document_id: uuid.UUID) -> Document:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    files: list[UploadFile],
    background: BackgroundTasks,
    session: SessionDep,
    user: UserDep,
    deps: DepsDep,
) -> list[UploadResult]:
    """Store each file, create a document row, and start processing in the background."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    results = []
    for upload in files:
        filename = PurePath(upload.filename or "upload").name
        data = await upload.read(max_bytes + 1)
        if len(data) > max_bytes:
            results.append(UploadResult(filename=filename, error="File is larger than 15 MB"))
            continue
        try:
            kind = detect_type(data)
        except UnsupportedFileError as exc:
            results.append(UploadResult(filename=filename, error=str(exc)))
            continue

        doc_id = uuid.uuid4()
        key = f"{doc_id}/original/{filename}"
        deps.storage.save(data, key)  # stored before anything else can fail (rule 3)
        doc = Document(
            id=doc_id,
            filename=filename,
            storage_key=key,
            mime_type=MIME_TYPES[kind],
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_by=user.id,
            status="uploaded",
        )
        session.add(doc)
        session.commit()
        background.add_task(process_document, doc_id, deps)
        results.append(UploadResult(filename=filename, document_id=doc_id, status="uploaded"))
    return results


@router.get("")
def list_documents(
    session: SessionDep,
    _: UserDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    vendor: str | None = None,
    limit: Annotated[int, Query(le=500)] = 100,
) -> list[DocumentSummary]:
    query = select(Document).order_by(Document.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Document.status == status_filter)
    if date_from:
        query = query.where(Document.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        query = query.where(Document.created_at <= datetime.combine(date_to, time.max, UTC))
    if vendor:
        vendor_docs = (
            select(Extraction.document_id)
            .join(ExtractedField, ExtractedField.extraction_id == Extraction.id)
            .where(ExtractedField.field_name == "vendor_name")
            .where(ExtractedField.value_text.ilike(f"%{vendor}%"))
        )
        query = query.where(Document.id.in_(vendor_docs))
    return [DocumentSummary.model_validate(d) for d in session.scalars(query)]


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, session: SessionDep, _: UserDep) -> DocumentDetail:
    doc = _get_document(session, document_id)
    detail = DocumentDetail.model_validate(doc)
    extraction = latest_extraction(session, document_id)
    if extraction is not None:
        fields = session.scalars(
            select(ExtractedField)
            .where(ExtractedField.extraction_id == extraction.id)
            .order_by(ExtractedField.line_item_index.nulls_first(), ExtractedField.created_at)
        )
        detail.extraction = ExtractionOut.model_validate(extraction)
        detail.extraction.fields = [FieldOut.model_validate(f) for f in fields]
        detail.duplicate_document_id = extraction.duplicate_of_document_id
        if extraction.duplicate_of_invoice_id:
            dup = session.get(Invoice, extraction.duplicate_of_invoice_id)
            detail.duplicate_document_id = dup.document_id if dup else None
    detail.confidence_threshold = load_settings(session).confidence_threshold
    return detail


@router.get("/{document_id}/pages/{page}", response_class=Response)
def get_page_image(
    document_id: uuid.UUID, page: int, session: SessionDep, _: UserDep, deps: DepsDep
) -> Response:
    """The rendered page that bounding boxes refer to (200 DPI, deskewed if it was a scan)."""
    _get_document(session, document_id)
    key = page_image_key(document_id, page)
    if not deps.storage.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page image not available yet")
    return Response(deps.storage.load(key), media_type="image/jpeg")


@router.post("/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_document(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    session: SessionDep,
    user: UserDep,
    deps: DepsDep,
) -> DocumentSummary:
    """Re-run the pipeline on a failed document. A new extraction row is created (D8)."""
    doc = _get_document(session, document_id)
    if doc.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed documents can be retried")
    if not deps.storage.exists(doc.storage_key):  # e.g. wiped by a restart on Render's free disk
        raise HTTPException(
            status.HTTP_410_GONE, "The original file is no longer stored. Please upload it again."
        )
    audit.record(
        session,
        entity_type="document",
        entity_id=doc.id,
        action="retry",
        user_id=user.id,
        old_value=doc.error_message,
    )
    doc.status, doc.error_message = "uploaded", None
    session.commit()
    background.add_task(process_document, doc.id, deps)
    return DocumentSummary.model_validate(doc)
