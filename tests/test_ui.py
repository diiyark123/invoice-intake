"""Headless UI tests with Streamlit's AppTest. A fake API client stands in for the server."""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

UI = Path(__file__).resolve().parents[1] / "ui"
sys.path.insert(0, str(UI))

from api_client import ApiError  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

DOC_ID = "11111111-1111-1111-1111-111111111111"
CLERK = {"role": "clerk", "name": "Asha (AP Clerk)"}
MANAGER = {"role": "manager", "name": "Ravi (AP Manager)"}


def field(name, value, conf=1.0, idx=None, bbox=True):
    return {
        "field_name": name,
        "value_text": value,
        "normalized_value": value,
        "confidence": conf,
        "source_match": conf,
        "page_number": 1 if bbox else None,
        "bbox": {"x0": 10, "y0": 10, "x1": 60, "y1": 30} if bbox else None,
        "source_text": value,
        "line_item_index": idx,
    }


DOC = {
    "id": DOC_ID,
    "filename": "apex.pdf",
    "mime_type": "application/pdf",
    "status": "needs_review",
    "review_reasons": ["totals_math", "low_confidence"],
    "error_message": None,
    "page_count": 1,
    "processing_ms": 6000,
    "created_at": "2026-10-27T09:00:00+00:00",
    "updated_at": "2026-10-27T09:00:10+00:00",
    "confidence_threshold": 0.85,
    "duplicate_document_id": None,
    "extraction": {
        "validation_results": [
            {
                "rule": "totals_math",
                "passed": False,
                "message": "Subtotal 100.00 + tax 18.00 = 118.00, but total is 999.00",
                "fields": ["subtotal", "tax", "total"],
                "severity": "error",
            }
        ],
        "fields": [
            field("vendor_name", "Apex Industrial Supplies Pvt Ltd"),
            field("invoice_number", "INV-0042"),
            field("invoice_date", "2026-09-01"),
            field("due_date", None, None, bbox=False),
            field("currency", "INR"),
            field("subtotal", "100.00"),
            field("tax", "18.00"),
            field("total", "999.00", 0.5),
            field("description", "Bolts", idx=0),
            field("quantity", "2", idx=0),
            field("unit_price", "50.00", idx=0),
            field("amount", "100.00", idx=0),
        ],
    },
}


class FakeApi:
    def __init__(self, doc=DOC, approve_error: ApiError | None = None):
        self.doc = doc
        self.approve_error = approve_error
        self.calls: list[tuple] = []

    def login(self, email, password):
        self.calls.append(("login", email))
        if password != "right":
            raise ApiError(401, "Wrong email or password")
        return {"token": "t", "role": "clerk", "display_name": "Asha (AP Clerk)"}

    def get_document(self, doc_id):
        return self.doc

    def page_image(self, doc_id, page):
        buf = io.BytesIO()
        Image.new("RGB", (200, 280), "white").save(buf, format="JPEG")
        return buf.getvalue()

    def queue(self):
        return [
            {
                "id": DOC_ID,
                "filename": "apex.pdf",
                "vendor_name": "Apex Industrial Supplies Pvt Ltd",
                "invoice_number": "INV-0042",
                "total": "999.00",
                "review_reasons": ["totals_math"],
                "created_at": "2026-10-27T09:00:00+00:00",
                "age_seconds": 7200,
            }
        ]

    def list_documents(self, **params):
        return [
            {**DOC, "status": "failed", "error_message": "LLMError: quota", "review_reasons": []},
            DOC,
        ]

    def correct(self, doc_id, changes, delete_lines):
        self.calls.append(("correct", changes, delete_lines))
        return DOC

    def approve(self, doc_id, note=None):
        self.calls.append(("approve", note))
        if self.approve_error:
            raise self.approve_error
        return {**DOC, "status": "approved"}

    def reject(self, doc_id, reason):
        self.calls.append(("reject", reason))
        return {**DOC, "status": "rejected"}

    def dashboard(self):
        return {
            "processed": {"today": 3, "this_week": 12, "this_month": 40},
            "auto_approval_rate": 0.75,
            "queue_size": 4,
            "oldest_in_queue_hours": 5.5,
            "failed": 1,
            "avg_processing_seconds": 6.2,
            "corrections_by_field": {"total": 3, "line item: amount": 1},
            "llm_cost_per_invoice_usd": 0.0016,
            "projected_monthly_cost_usd": 3.2,
            "projected_monthly_volume_at_current_pace": 46,
            "monthly_volume_assumed": 2000,
        }

    def get_settings(self):
        return {
            "confidence_threshold": 0.85,
            "require_review_for_new_vendor": True,
            "amount_tolerance": "0.01",
            "max_due_days": 180,
        }

    def update_settings(self, **changes):
        self.calls.append(("update_settings", changes))
        return self.get_settings() | changes

    def vendors(self):
        return [
            {
                "id": "v1",
                "name": "Apex Industrial Supplies Pvt Ltd",
                "normalized_name": "apex industrial supplies",
                "aliases": ["AISPL"],
                "tax_id": None,
                "is_active": True,
            }
        ]

    def retry(self, doc_id):
        self.calls.append(("retry", doc_id))
        return DOC


def page(name: str, user=CLERK, api=None, doc_id=DOC_ID) -> tuple[AppTest, FakeApi]:
    api = api or FakeApi()
    at = AppTest.from_file(str(UI / "pages" / name), default_timeout=20)
    at.session_state["api"] = api
    if user:
        at.session_state["user"] = user
    if doc_id:
        at.session_state["review_doc_id"] = doc_id
    return at.run(), api


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def all_text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += (
        [e.value for e in at.error] + [w.value for w in at.warning] + [s.value for s in at.success]
    )
    return "\n".join(str(p) for p in parts)


# ---------- login ----------


def test_login_page_wrong_then_right_password() -> None:
    at = AppTest.from_file(str(UI / "Home.py"), default_timeout=20)
    api = FakeApi()
    at.session_state["api"] = api
    at.run()
    assert at.title[0].value.startswith("Invoice Intake")
    at.text_input[0].input("clerk@meridian.test")
    at.text_input[1].input("wrong")
    button(at, "Log in").click().run()
    assert "Wrong email or password." in [e.value for e in at.error]
    at.text_input[1].input("right")
    button(at, "Log in").click().run()
    assert at.session_state["user"]["role"] == "clerk"


def test_pages_require_login() -> None:
    at, _ = page("2_Review_Queue.py", user=None)
    assert "Please log in first." in [w.value for w in at.warning]


@pytest.mark.parametrize("name", ["4_Dashboard.py", "5_Settings.py"])
def test_manager_pages_block_clerks(name: str) -> None:
    at, _ = page(name, user=CLERK)
    assert "This page is for AP managers only." in [e.value for e in at.error]
    at, _ = page(name, user=MANAGER)
    assert not at.error and at.title


# ---------- queue + upload ----------


def test_queue_shows_plain_reasons_and_age() -> None:
    at, _ = page("2_Review_Queue.py")
    text = all_text(at)
    assert "Subtotal + tax doesn't equal total" in text
    assert "totals_math" not in text
    assert "2 h" in text
    assert any(b.label == "Open" for b in at.button)


def test_upload_page_lists_recent_with_retry() -> None:
    at, api = page("1_Upload.py")
    assert "LLMError: quota" in all_text(at)
    button(at, "Retry").click().run()
    assert ("retry", DOC_ID) in api.calls


# ---------- review invoice ----------


def test_review_screen_shows_values_badges_and_rule_messages() -> None:
    at, _ = page("3_Review_Invoice.py")
    assert at.title[0].value == "Apex Industrial Supplies Pvt Ltd"
    assert at.text_input(key="h-total").value == "999.00"
    labels = " ".join(t.label for t in at.text_input)
    assert "50% sure" in labels and "100% sure" in labels
    text = all_text(at)
    assert "but total is 999.00" in text
    assert "Subtotal + tax doesn't equal total" in text
    assert len(at.get("dataframe")) == 1
    assert at.get("image"), "page image with boxes is shown"


def test_fix_total_save_and_approve() -> None:
    at, api = page("3_Review_Invoice.py")
    at.text_input(key="h-total").input("118.00")
    button(at, "Save and approve").click().run()
    assert (
        "correct",
        [{"field_name": "total", "line_item_index": None, "value": "118.00"}],
        [],
    ) in api.calls
    assert ("approve", None) in api.calls
    assert "Invoice approved." in [s.value for s in at.success]


def test_unchanged_save_sends_nothing() -> None:
    at, api = page("3_Review_Invoice.py")
    button(at, "Save changes").click().run()
    assert not [c for c in api.calls if c[0] == "correct"]


def test_refused_approval_shows_plain_reasons() -> None:
    err = ApiError(422, {"message": "no", "reasons": ["totals_math", "not_duplicate"]})
    at, _ = page("3_Review_Invoice.py", api=FakeApi(approve_error=err))
    button(at, "Save and approve").click().run()
    text = all_text(at)
    assert "Subtotal + tax doesn't equal total" in text
    assert "Looks like a duplicate of another invoice" in text


def test_reject_requires_reason() -> None:
    at, api = page("3_Review_Invoice.py")
    assert button(at, "Reject").disabled
    at.text_input(key="reject-reason").input("Not our order").run()
    button(at, "Reject").click().run()
    assert ("reject", "Not our order") in api.calls


def test_approved_invoice_is_read_only() -> None:
    at, _ = page(
        "3_Review_Invoice.py", api=FakeApi(doc={**DOC, "status": "approved", "review_reasons": []})
    )
    assert at.text_input(key="h-total").disabled
    assert button(at, "Save and approve").disabled


def test_dashboard_shows_metrics() -> None:
    at, _ = page("4_Dashboard.py", user=MANAGER)
    values = {m.label: m.value for m in at.metric}
    assert values["This month"] == "40"
    assert values["Approved automatically"] == "75%"
    assert values["Per invoice"] == "$0.0016"
    assert values["Per month at 2,000 invoices"] == "$3.20"
    assert "5.5 hours" in all_text(at)


def test_settings_save_sends_changes() -> None:
    at, api = page("5_Settings.py", user=MANAGER)
    at.slider[0].set_value(0.9)
    button(at, "Save settings").click().run()
    sent = [c[1] for c in api.calls if c[0] == "update_settings"]
    assert sent and sent[0]["confidence_threshold"] == 0.9 and sent[0]["amount_tolerance"] == "0.01"
    assert "Settings saved." in [s.value for s in at.success]
