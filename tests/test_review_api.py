import json
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import CurrentUser, require_manager
from app.models import AuditLog, Invoice
from tests.conftest import login
from tests.fakes import FakeLLMProvider


def upload(client, headers, invoice, state, label_changes=None, name="inv.pdf") -> str:
    label = json.loads(invoice.label_file.read_text()) | (label_changes or {})
    state["fake"] = FakeLLMProvider(label)
    r = client.post(
        "/documents",
        headers=headers,
        files=[("files", (name, invoice.file.read_bytes(), "application/pdf"))],
    )
    return r.json()[0]["document_id"]


def detail(client, headers, doc_id) -> dict:
    return client.get(f"/documents/{doc_id}", headers=headers).json()


def test_fix_wrong_total_then_approve(api, invoice, session_factory) -> None:
    client, state = api
    headers = login(client)
    right_total = json.loads(invoice.label_file.read_text())["total"]
    doc_id = upload(client, headers, invoice, state, {"total": "99999.99"})

    d = detail(client, headers, doc_id)
    assert d["status"] == "needs_review" and "totals_math" in d["review_reasons"]
    queue = client.get("/review/queue", headers=headers).json()
    assert [q["id"] for q in queue] == [doc_id] and queue[0]["total"] == "99999.99"
    failed = [r for r in d["extraction"]["validation_results"] if not r["passed"]]
    assert any(r["rule"] == "totals_math" for r in failed)

    r = client.post(f"/review/{doc_id}/approve", headers=headers, json={})
    assert r.status_code == 422 and "totals_math" in r.json()["detail"]["reasons"]

    r = client.patch(
        f"/review/{doc_id}/fields",
        headers=headers,
        json={"changes": [{"field_name": "total", "value": right_total}]},
    )
    assert r.status_code == 200
    assert "totals_math" not in r.json()["review_reasons"], "checks re-run after the edit"
    total = next(
        f
        for f in detail(client, headers, doc_id)["extraction"]["fields"]
        if f["field_name"] == "total"
    )
    assert total["value_text"] == right_total and total["confidence"] == 1.0

    r = client.post(f"/review/{doc_id}/approve", headers=headers, json={})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.get("/review/queue", headers=headers).json() == []

    with session_factory() as s:
        inv = s.scalar(select(Invoice))
        assert str(inv.total) == right_total and inv.approval_type == "human"
        log = {
            (a.action, a.field_name, a.old_value, a.new_value) for a in s.scalars(select(AuditLog))
        }
        assert ("field_corrected", "total", "99999.99", right_total) in log
        assert any(a[0] == "approved" for a in log)
        assert all(a.user_id is not None for a in s.scalars(select(AuditLog)))


def test_line_items_edit_add_delete_are_audited(api, invoice, session_factory) -> None:
    client, state = api
    headers = login(client)
    label = json.loads(invoice.label_file.read_text())
    doc_id = upload(client, headers, invoice, state, {"vendor_name": "Someone New Traders"})
    n = len(label["line_items"])

    r = client.patch(
        f"/review/{doc_id}/fields",
        headers=headers,
        json={
            "changes": [
                {"field_name": "description", "line_item_index": 0, "value": "Edited description"},
                {"field_name": "description", "line_item_index": n, "value": "Freight"},
                {"field_name": "amount", "line_item_index": n, "value": "10.00"},
            ],
            "delete_lines": [n - 1] if n > 1 else [],
        },
    )
    assert r.status_code == 200, r.text
    fields = detail(client, headers, doc_id)["extraction"]["fields"]
    lines = {f["line_item_index"] for f in fields if f["line_item_index"] is not None}
    assert n in lines and (n == 1 or n - 1 not in lines)
    with session_factory() as s:
        audited = {a.field_name for a in s.scalars(select(AuditLog))}
    assert {
        "line_items.0.description",
        f"line_items.{n}.description",
        f"line_items.{n}.amount",
    } <= audited
    if n > 1:
        assert f"line_items.{n - 1}" in audited

    bad = client.patch(
        f"/review/{doc_id}/fields",
        headers=headers,
        json={"changes": [{"field_name": "password_hash", "value": "x"}]},
    )
    assert bad.status_code == 422


def test_reject_needs_reason_and_locks_document(api, invoice, session_factory) -> None:
    client, state = api
    headers = login(client)
    doc_id = upload(client, headers, invoice, state, {"total": "1.00"})
    assert (
        client.post(f"/review/{doc_id}/reject", headers=headers, json={"reason": ""}).status_code
        == 422
    )
    r = client.post(f"/review/{doc_id}/reject", headers=headers, json={"reason": "Not our order"})
    assert r.json()["status"] == "rejected"
    with session_factory() as s:
        entry = s.scalar(select(AuditLog).where(AuditLog.action == "rejected"))
        assert entry.note == "Not our order"
    patch = client.patch(
        f"/review/{doc_id}/fields",
        headers=headers,
        json={"changes": [{"field_name": "total", "value": "2"}]},
    )
    assert patch.status_code == 409
    assert client.post(f"/review/{doc_id}/approve", headers=headers, json={}).status_code == 409


def test_duplicate_override_needs_a_note(api, invoice, session_factory) -> None:
    client, state = api
    headers = login(client)
    label = json.loads(invoice.label_file.read_text())
    first = upload(client, headers, invoice, state, name="a.pdf")
    assert detail(client, headers, first)["status"] == "auto_approved"

    # An exact copy: even with a note it can't be booked twice.
    copy = upload(client, headers, invoice, state, name="copy.pdf")
    d = detail(client, headers, copy)
    assert "possible_duplicate" in d["review_reasons"]
    assert d["duplicate_document_id"] == first, "side-by-side link resolves to the first document"
    r = client.post(f"/review/{copy}/approve", headers=headers, json={})
    assert r.status_code == 422 and "not_duplicate" in r.json()["detail"]["reasons"]
    r = client.post(f"/review/{copy}/approve", headers=headers, json={"note": "Re-sent"})
    assert r.status_code == 422 and r.json()["detail"]["reasons"] == ["already_recorded"]

    # A look-alike (different file, invoice number one character longer): a note overrides it.
    state["fake"] = FakeLLMProvider(label | {"invoice_number": label["invoice_number"] + "A"})
    r = client.post(
        "/documents",
        headers=headers,
        files=[("files", ("b.pdf", invoice.file.read_bytes() + b"\n", "application/pdf"))],
    )
    lookalike = r.json()[0]["document_id"]
    assert "possible_duplicate" in detail(client, headers, lookalike)["review_reasons"]
    r = client.post(f"/review/{lookalike}/approve", headers=headers, json={})
    assert r.status_code == 422
    r = client.post(
        f"/review/{lookalike}/approve", headers=headers, json={"note": "Separate delivery, checked"}
    )
    assert r.status_code == 200, r.text
    with session_factory() as s:
        assert len(s.scalars(select(Invoice)).all()) == 2
        note = s.scalar(select(AuditLog).where(AuditLog.action == "approved"))
        assert note.note == "Separate delivery, checked"


def test_clerk_cannot_use_manager_routes(api) -> None:
    client, _ = api
    probe = FastAPI()

    @probe.get("/manager-only")
    def manager_only(user: Annotated[CurrentUser, Depends(require_manager)]) -> dict:
        return {"ok": True}

    clerk = login(client)
    manager = login(client, "manager@meridian.test", "manager-demo-123")
    with TestClient(probe) as p:
        assert p.get("/manager-only", headers=clerk).status_code == 403
        assert p.get("/manager-only", headers=manager).status_code == 200
        assert p.get("/manager-only").status_code == 401
