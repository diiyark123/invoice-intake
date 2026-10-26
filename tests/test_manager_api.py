import json

from sqlalchemy import select

from app.models import AuditLog
from app.services.dashboard import field_group
from tests.conftest import login
from tests.fakes import FakeLLMProvider

MANAGER = ("manager@meridian.test", "manager-demo-123")


def test_clerk_is_blocked_from_every_manager_route(api) -> None:
    client, _ = api
    clerk = login(client)
    for method, path in [
        ("GET", "/dashboard/metrics"),
        ("GET", "/settings"),
        ("PUT", "/settings"),
        ("GET", "/vendors"),
        ("POST", "/vendors"),
    ]:
        r = client.request(method, path, headers=clerk, json={})
        assert r.status_code == 403, (method, path)


def test_settings_change_is_audited_and_validated(api, session_factory) -> None:
    client, _ = api
    manager = login(client, *MANAGER)
    assert client.get("/settings", headers=manager).json()["confidence_threshold"] == 0.85
    r = client.put(
        "/settings", headers=manager, json={"confidence_threshold": 0.9, "amount_tolerance": "0.05"}
    )
    assert r.status_code == 200 and r.json()["confidence_threshold"] == 0.9
    assert (
        client.put("/settings", headers=manager, json={"confidence_threshold": 1.5}).status_code
        == 422
    )
    with session_factory() as s:
        log = {
            (a.field_name, a.old_value, a.new_value)
            for a in s.scalars(select(AuditLog).where(AuditLog.action == "settings_changed"))
        }
    assert ("confidence_threshold", "0.85", "0.9") in log
    assert ("amount_tolerance", "0.01", "0.05") in log


def test_threshold_setting_changes_routing(api, invoice) -> None:
    client, state = api
    manager = login(client, *MANAGER)
    client.put("/settings", headers=manager, json={"confidence_threshold": 1.0})
    label = json.loads(invoice.label_file.read_text())
    # vendor name slightly off the printed text -> confidence < 1.0
    state["fake"] = FakeLLMProvider(label | {"vendor_name": label["vendor_name"] + "."})
    clerk = login(client)
    doc = client.post(
        "/documents",
        headers=clerk,
        files=[("files", ("a.pdf", invoice.file.read_bytes(), "application/pdf"))],
    ).json()[0]
    status = client.get(f"/documents/{doc['document_id']}", headers=clerk).json()
    # At the default 0.85 this invoice auto-approves (see test_api); at 1.0 the slightly-off
    # vendor name is no longer "sure enough".
    assert status["status"] == "needs_review"
    assert status["review_reasons"] == ["low_confidence"]


def test_vendor_create_update_and_conflict(api, session_factory) -> None:
    client, _ = api
    manager = login(client, *MANAGER)
    r = client.post(
        "/vendors",
        headers=manager,
        json={
            "name": "Pinnacle Uniforms Pvt Ltd",
            "aliases": ["Pinnacle", " "],
            "tax_id": "24AAPFP6789W1Z2",
        },
    )
    assert r.status_code == 201
    vendor = r.json()
    assert vendor["normalized_name"] == "pinnacle uniforms" and vendor["aliases"] == ["Pinnacle"]
    dup = client.post("/vendors", headers=manager, json={"name": "Pinnacle Uniforms"})
    assert dup.status_code == 409
    r = client.put(
        f"/vendors/{vendor['id']}",
        headers=manager,
        json={"name": "Pinnacle Uniforms Pvt Ltd", "aliases": ["Pinnacle"], "is_active": False},
    )
    assert r.json()["is_active"] is False
    with session_factory() as s:
        actions = [(a.action, a.field_name) for a in s.scalars(select(AuditLog))]
    assert ("vendor_created", None) in actions
    assert ("settings_changed", "is_active") in actions and (
        "settings_changed",
        "tax_id",
    ) in actions
    assert len(client.get("/vendors", headers=manager).json()) == 16


def test_dashboard_metrics(api, invoice) -> None:
    client, state = api
    clerk = login(client)
    label = json.loads(invoice.label_file.read_text())
    state["fake"] = FakeLLMProvider(label | {"total": "1.00"})
    doc_id = client.post(
        "/documents",
        headers=clerk,
        files=[("files", ("a.pdf", invoice.file.read_bytes(), "application/pdf"))],
    ).json()[0]["document_id"]
    client.patch(
        f"/review/{doc_id}/fields",
        headers=clerk,
        json={
            "changes": [
                {"field_name": "total", "value": label["total"]},
                {"field_name": "amount", "line_item_index": 0, "value": "9.99"},
            ]
        },
    )
    m = client.get("/dashboard/metrics", headers=login(client, *MANAGER)).json()
    assert m["processed"] == {"today": 1, "this_week": 1, "this_month": 1}
    assert m["queue_size"] == 1 and m["oldest_in_queue_hours"] is not None
    assert m["auto_approval_rate"] == 0.0 and m["failed"] == 0
    assert m["corrections_by_field"] == {"total": 1, "line item: amount": 1}
    assert m["llm_cost_per_invoice_usd"] is None, "the fake model has no price"
    assert m["avg_processing_seconds"] is not None


def test_field_group() -> None:
    assert field_group("total") == "total"
    assert field_group("line_items.12.unit_price") == "line item: unit_price"
    assert field_group("line_items.3") == "line item: deleted"
