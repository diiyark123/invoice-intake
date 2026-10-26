import json
import random
import uuid
from datetime import date
from pathlib import Path

import pytest
from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Document, ExtractedField, Extraction
from app.pipeline.extract import PROMPT_VERSION
from app.pipeline.llm.base import LLMError
from app.pipeline.orchestrator import PipelineDeps, page_image_key, process_document
from app.storage import LocalStorage
from data.generator.generate import write_invoice
from data.generator.model import make_invoice
from tests.fakes import FakeLLMProvider

TODAY = date(2026, 10, 26)


@pytest.fixture
def generated(tmp_path: Path):
    rng = random.Random(21)
    faker = Faker("en_IN")
    faker.seed_instance(21)
    inv = make_invoice(rng, faker, TODAY)
    return write_invoice(inv, tmp_path / "gen", "inv", "gst_heavy", False, rng)


def make_deps(
    sf: sessionmaker[Session], storage: LocalStorage, fake: FakeLLMProvider
) -> PipelineDeps:
    return PipelineDeps(session_factory=sf, storage=storage, provider_factory=lambda: fake)


def add_document(sf: sessionmaker[Session], storage: LocalStorage, data: bytes) -> uuid.UUID:
    doc_id = uuid.uuid4()
    key = f"{doc_id}/original/invoice.pdf"
    storage.save(data, key)
    with sf() as s:
        s.add(
            Document(
                id=doc_id,
                filename="invoice.pdf",
                storage_key=key,
                mime_type="application/pdf",
                sha256="x" * 64,
            )
        )
        s.commit()
    return doc_id


def test_success_writes_extraction_and_grounded_fields(
    session_factory, tmp_path, generated
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    label = json.loads(generated.label_file.read_text())
    fake = FakeLLMProvider(label)
    doc_id = add_document(session_factory, storage, generated.file.read_bytes())

    process_document(doc_id, make_deps(session_factory, storage, fake))

    with session_factory() as s:
        doc = s.get(Document, doc_id)
        assert doc.status == "needs_review", doc.error_message
        assert doc.page_count == 1 and doc.processing_ms is not None
        extractions = s.scalars(select(Extraction).where(Extraction.document_id == doc_id)).all()
        assert len(extractions) == 1
        ex = extractions[0]
        assert ex.model_name == "fake-model" and ex.prompt_version == PROMPT_VERSION
        assert ex.llm_input_tokens == 1000 and ex.llm_output_tokens == 200
        assert ex.doc_class == "invoice" and ex.raw_llm_output == label
        fields = s.scalars(
            select(ExtractedField).where(ExtractedField.extraction_id == ex.id)
        ).all()

    assert len(fields) == 8 + 4 * len(label["line_items"])
    by_name = {f.field_name: f for f in fields if f.line_item_index is None}
    for name in ("vendor_name", "invoice_number", "invoice_date", "subtotal", "tax", "total"):
        f = by_name[name]
        assert f.page_number == 1, name
        assert f.source_text, name
        assert f.bbox and f.bbox["x1"] > f.bbox["x0"], name
        assert f.source_match == 1.0, name
    assert by_name["total"].normalized_value == label["total"]
    assert by_name["invoice_date"].normalized_value == label["invoice_date"]
    assert storage.exists(page_image_key(doc_id, 1))
    assert fake.calls[0]["images"][0].mime_type == "image/jpeg"
    assert label["invoice_number"] in fake.calls[0]["ocr_text"]


def test_bad_json_twice_marks_failed_and_keeps_file(session_factory, tmp_path, generated) -> None:
    storage = LocalStorage(tmp_path / "storage")
    data = generated.file.read_bytes()
    doc_id = add_document(session_factory, storage, data)

    process_document(doc_id, make_deps(session_factory, storage, FakeLLMProvider("nope", "nope")))

    with session_factory() as s:
        doc = s.get(Document, doc_id)
        assert doc.status == "failed"
        assert "invalid JSON after 2 attempts" in doc.error_message
        assert s.scalars(select(Extraction)).all() == []
        assert storage.load(doc.storage_key) == data, "the upload is never lost"


def test_exception_marks_failed_then_retry_succeeds(session_factory, tmp_path, generated) -> None:
    storage = LocalStorage(tmp_path / "storage")
    doc_id = add_document(session_factory, storage, generated.file.read_bytes())

    process_document(doc_id, make_deps(session_factory, storage, FakeLLMProvider(LLMError("503"))))
    with session_factory() as s:
        doc = s.get(Document, doc_id)
        assert doc.status == "failed" and "LLMError: 503" in doc.error_message

    label = json.loads(generated.label_file.read_text())
    process_document(doc_id, make_deps(session_factory, storage, FakeLLMProvider(label)))
    with session_factory() as s:
        doc = s.get(Document, doc_id)
        assert doc.status == "needs_review" and doc.error_message is None


def test_broken_file_fails_in_ingest(session_factory, tmp_path) -> None:
    storage = LocalStorage(tmp_path / "storage")
    doc_id = add_document(session_factory, storage, b"%PDF-1.7 truncated garbage")
    fake = FakeLLMProvider({})
    process_document(doc_id, make_deps(session_factory, storage, fake))
    with session_factory() as s:
        assert s.get(Document, doc_id).status == "failed"
    assert fake.calls == [], "the LLM is not called for an unreadable file"


def test_non_invoice_gets_review_reason(session_factory, tmp_path, generated) -> None:
    storage = LocalStorage(tmp_path / "storage")
    label = json.loads(generated.label_file.read_text()) | {"doc_class": "credit_note"}
    doc_id = add_document(session_factory, storage, generated.file.read_bytes())
    process_document(doc_id, make_deps(session_factory, storage, FakeLLMProvider(label)))
    with session_factory() as s:
        doc = s.get(Document, doc_id)
        assert doc.status == "needs_review" and "credit_note" in doc.review_reasons
