import json

import pytest
from sqlalchemy import select

from app.auth import create_token, read_token
from app.models import AuditLog
from app.pipeline.extract import PROMPT_VERSION
from app.pipeline.llm.base import LLMError
from tests.conftest import login
from tests.fakes import FakeLLMProvider


def test_login_and_token_roles(api) -> None:
    client, _ = api
    assert (
        client.post(
            "/auth/login", json={"email": "clerk@meridian.test", "password": "x"}
        ).status_code
        == 401
    )
    r = client.post(
        "/auth/login", json={"email": "manager@meridian.test", "password": "manager-demo-123"}
    )
    assert r.json()["role"] == "manager"
    assert read_token(r.json()["token"]).role == "manager"


def test_endpoints_require_login(api) -> None:
    client, _ = api
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_expired_token_rejected() -> None:
    import uuid

    from fastapi import HTTPException

    token = create_token(uuid.uuid4(), "clerk")
    with pytest.raises(HTTPException) as exc:
        read_token(token, max_age=-1)
    assert exc.value.status_code == 401


def test_upload_processes_in_background_and_returns_fields(api, invoice) -> None:
    client, state = api
    label = json.loads(invoice.label_file.read_text())
    state["fake"] = FakeLLMProvider(label)
    headers = login(client)

    r = client.post(
        "/documents",
        headers=headers,
        files=[("files", ("invoice.pdf", invoice.file.read_bytes(), "application/pdf"))],
    )
    assert r.status_code == 202, r.text
    doc_id = r.json()[0]["document_id"]

    detail = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert detail["status"] == "auto_approved", detail["review_reasons"]  # clean + known vendor
    ex = detail["extraction"]
    assert ex["model_name"] == "fake-model" and ex["prompt_version"] == PROMPT_VERSION
    total = next(f for f in ex["fields"] if f["field_name"] == "total")
    assert total["normalized_value"] == label["total"] and total["page_number"] == 1
    assert total["source_text"] and total["bbox"]

    page = client.get(f"/documents/{doc_id}/pages/1", headers=headers)
    assert page.status_code == 200 and page.headers["content-type"] == "image/jpeg"

    listed = client.get("/documents", params={"status": "auto_approved"}, headers=headers).json()
    assert [d["id"] for d in listed] == [doc_id]
    vendor_word = label["vendor_name"].split()[0]
    assert client.get("/documents", params={"vendor": vendor_word}, headers=headers).json()
    assert client.get("/documents", params={"vendor": "zzz"}, headers=headers).json() == []


def test_upload_rejects_unsupported_and_oversized(api) -> None:
    client, _ = api
    headers = login(client)
    big = b"%PDF-" + b"0" * (15 * 1024 * 1024)
    r = client.post(
        "/documents",
        headers=headers,
        files=[
            ("files", ("notes.txt", b"hello", "text/plain")),
            ("files", ("big.pdf", big, "application/pdf")),
        ],
    )
    results = r.json()
    assert results[0]["error"].startswith("Unsupported file type")
    assert "15 MB" in results[1]["error"]
    assert all(x["document_id"] is None for x in results)


def test_failed_document_can_be_retried(api, invoice, session_factory) -> None:
    client, state = api
    headers = login(client)
    state["fake"] = FakeLLMProvider(LLMError("rate limited"))
    r = client.post(
        "/documents",
        headers=headers,
        files=[("files", ("inv.pdf", invoice.file.read_bytes(), "application/pdf"))],
    )
    doc_id = r.json()[0]["document_id"]
    detail = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert detail["status"] == "failed" and "rate limited" in detail["error_message"]

    state["fake"] = FakeLLMProvider(json.loads(invoice.label_file.read_text()))
    assert client.post(f"/documents/{doc_id}/retry", headers=headers).status_code == 202
    assert client.get(f"/documents/{doc_id}", headers=headers).json()["status"] == "auto_approved"
    assert client.post(f"/documents/{doc_id}/retry", headers=headers).status_code == 409

    with session_factory() as s:
        entries = s.scalars(select(AuditLog).where(AuditLog.action == "retry")).all()
        assert len(entries) == 1 and "rate limited" in entries[0].old_value


def test_retry_refused_when_original_file_is_gone(api, invoice, session_factory, tmp_path) -> None:
    import uuid

    from app.models import Document

    client, state = api
    headers = login(client)
    state["fake"] = FakeLLMProvider(LLMError("rate limited"))
    r = client.post(
        "/documents",
        headers=headers,
        files=[("files", ("inv.pdf", invoice.file.read_bytes(), "application/pdf"))],
    )
    doc_id = r.json()[0]["document_id"]
    with session_factory() as s:
        key = s.get(Document, uuid.UUID(doc_id)).storage_key
    (tmp_path / "storage" / key).unlink()

    r = client.post(f"/documents/{doc_id}/retry", headers=headers)
    assert r.status_code == 410 and "upload it again" in r.json()["detail"]
    assert client.get(f"/documents/{doc_id}", headers=headers).json()["status"] == "failed"
