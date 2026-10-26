"""Run the pipeline for one document and record the result in the staging tables.

Opens its own DB session (D8). Any exception sets status=failed with the error message;
the uploaded file is never touched, so Retry can run the pipeline again (rule 3).
After extraction it validates, checks duplicates, scores confidence and routes: an invoice that
passes everything is handed to services/approval.py (the only writer); the rest go to review.
"""

import io
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings, llm_cost_usd
from app.models import Document, ExtractedField, Extraction
from app.pipeline.extract import PROMPT_VERSION, ExtractedInvoice, run_extraction
from app.pipeline.grounding import FieldKind, ground_value
from app.pipeline.ingest import ingest
from app.pipeline.llm.base import LLMProvider, PageImage
from app.pipeline.normalize import (
    normalize_amount,
    normalize_currency,
    normalize_date,
    normalize_invoice_number,
    normalize_quantity,
    normalize_vendor_name,
)
from app.pipeline.ocr import (
    Word,
    has_text_layer,
    ocr_text,
    words_from_tesseract,
    words_from_text_layer,
)
from app.pipeline.preprocess import BLUR_THRESHOLD, preprocess
from app.services.approval import ApprovalRefused, approve
from app.services.assessment import assess, store_assessment
from app.storage import Storage

logger = logging.getLogger(__name__)

HEADER_FIELDS: dict[str, FieldKind] = {
    "vendor_name": "text",
    "invoice_number": "text",
    "invoice_date": "date",
    "due_date": "date",
    "currency": "currency",
    "subtotal": "amount",
    "tax": "amount",
    "total": "amount",
}
LINE_FIELDS: dict[str, FieldKind] = {
    "description": "text",
    "quantity": "quantity",
    "unit_price": "amount",
    "amount": "amount",
}


@dataclass
class PipelineDeps:
    session_factory: sessionmaker[Session]
    storage: Storage
    provider_factory: Callable[[], LLMProvider]
    tesseract_cmd: str | None = None
    today: Callable[[], date] = date.today
    prompt_version: str = PROMPT_VERSION


def default_deps() -> PipelineDeps:
    from app.db import SessionLocal
    from app.pipeline.llm.factory import get_provider
    from app.storage import get_storage

    return PipelineDeps(SessionLocal, get_storage(), get_provider, get_settings().tesseract_cmd)


def page_image_key(document_id: uuid.UUID, page: int) -> str:
    return f"{document_id}/pages/{page}.jpg"


@contextmanager
def step(name: str, document_id: uuid.UUID) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - start) * 1000
        logger.info("pipeline step=%s document_id=%s duration_ms=%.0f", name, document_id, ms)


# ---------- pure helpers (unit-tested without DB or LLM) ----------


@dataclass(frozen=True)
class FieldValue:
    field_name: str
    value_text: str | None
    normalized_value: str | None
    line_item_index: int | None
    page_number: int | None
    bbox: dict[str, float] | None
    source_text: str | None
    source_match: float


def normalize_field(name: str, value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    result: Any
    if name in ("invoice_date", "due_date"):
        result = normalize_date(value)
        return result.isoformat() if result else None
    if name in ("subtotal", "tax", "total", "unit_price", "amount"):
        result = normalize_amount(value)
    elif name == "quantity":
        result = normalize_quantity(value)
    elif name == "invoice_number":
        result = normalize_invoice_number(value)
    elif name == "vendor_name":
        result = normalize_vendor_name(value)
    elif name == "currency":
        result = normalize_currency(value)
    else:
        result = " ".join(value.split())
    return None if result is None else str(result)


def build_field_values(invoice: ExtractedInvoice, words: list[Word]) -> list[FieldValue]:
    """Normalize and ground every header and line-item value."""
    items: list[tuple[str, str | None, int | None, FieldKind]] = [
        (name, getattr(invoice, name), None, kind) for name, kind in HEADER_FIELDS.items()
    ]
    for index, line in enumerate(invoice.line_items):
        items += [(name, getattr(line, name), index, kind) for name, kind in LINE_FIELDS.items()]

    values = []
    for name, raw, index, kind in items:
        g = ground_value(raw, kind, words)
        values.append(
            FieldValue(
                field_name=name,
                value_text=raw,
                normalized_value=normalize_field(name, raw),
                line_item_index=index,
                page_number=g.page,
                bbox=g.bbox,
                source_text=g.source_text,
                source_match=g.score,
            )
        )
    return values


def _jpeg(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ---------- the pipeline ----------


def process_document(document_id: uuid.UUID, deps: PipelineDeps | None = None) -> None:
    deps = deps or default_deps()
    with deps.session_factory() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            logger.error("process_document: document %s not found", document_id)
            return
        doc.status, doc.error_message, doc.review_reasons = "processing", None, []
        session.commit()

        start = time.perf_counter()
        try:
            _run(session, doc, deps)
        except Exception as exc:
            session.rollback()
            logger.exception("pipeline failed document_id=%s", document_id)
            doc = session.get(Document, document_id)
            assert doc is not None
            doc.status = "failed"
            doc.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        doc.processing_ms = int((time.perf_counter() - start) * 1000)
        session.commit()
        logger.info(
            "pipeline done document_id=%s status=%s duration_ms=%d",
            document_id,
            doc.status,
            doc.processing_ms,
        )


def _run(session: Session, doc: Document, deps: PipelineDeps) -> None:
    reasons: list[str] = []

    with step("ingest", doc.id):
        data = deps.storage.load(doc.storage_key)
        mime_type, pages = ingest(data)
        doc.mime_type = mime_type
        doc.page_count = len(pages)

    words: list[Word] = []
    images: list[PageImage] = []
    for page in pages:
        with step(f"ocr_page_{page.number}", doc.id):
            if has_text_layer(page.text_layer):
                page_words = words_from_text_layer(page.text_layer, page.number)
                shown = page.image
            else:
                pre = preprocess(page.image)
                page_words = words_from_tesseract(pre.gray, page.number, deps.tesseract_cmd)
                shown = pre.rotated
                if pre.blur_score < BLUR_THRESHOLD and "low_image_quality" not in reasons:
                    reasons.append("low_image_quality")  # D6: flag, but keep processing
            words += page_words
            jpeg = _jpeg(shown)
            deps.storage.save(jpeg, page_image_key(doc.id, page.number))
            images.append(PageImage(jpeg, "image/jpeg"))

    with step("extract", doc.id):
        output = run_extraction(
            deps.provider_factory(), images, ocr_text(words), deps.prompt_version
        )

    with step("normalize_and_ground", doc.id):
        values = build_field_values(output.invoice, words)

    if output.invoice.doc_class != "invoice":
        reasons.append(output.invoice.doc_class)

    extraction = Extraction(
        document_id=doc.id,
        model_name=output.model,
        prompt_version=deps.prompt_version,
        raw_llm_output=output.raw,
        doc_class=output.invoice.doc_class,
        llm_input_tokens=output.input_tokens,
        llm_output_tokens=output.output_tokens,
        cost_usd=llm_cost_usd(output.model, output.input_tokens, output.output_tokens),
    )
    session.add(extraction)
    session.flush()
    session.add_all(
        ExtractedField(
            extraction_id=extraction.id,
            field_name=v.field_name,
            value_text=v.value_text,
            normalized_value=v.normalized_value,
            page_number=v.page_number,
            bbox=v.bbox,
            source_text=v.source_text,
            source_match=v.source_match,
            line_item_index=v.line_item_index,
        )
        for v in values
    )
    session.flush()

    with step("validate_and_route", doc.id):
        assessment = assess(session, doc, extraction, deps.today(), reasons)
        store_assessment(session, extraction, assessment)
        doc.status, doc.review_reasons = "needs_review", assessment.reasons
        if assessment.decision == "auto_approve":
            try:
                approve(session, doc.id, approval_type="auto", today=deps.today())
            except ApprovalRefused as refused:  # approval.py re-checked and disagreed
                doc.status, doc.review_reasons = "needs_review", refused.reasons
