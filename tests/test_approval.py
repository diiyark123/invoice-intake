import json
import random
import re
import uuid
from datetime import date
from pathlib import Path

import pytest
from faker import Faker
from sqlalchemy import func, select

from app.models import AppSettings, AuditLog, Document, Extraction, Invoice, InvoiceLineItem, Vendor
from app.pipeline.orchestrator import PipelineDeps, process_document
from app.seed import seed
from app.seed_data import UNKNOWN_VENDORS
from app.services.approval import ApprovalRefused, approve
from app.storage import LocalStorage
from data.generator.generate import write_invoice
from data.generator.model import make_invoice
from tests.fakes import FakeLLMProvider

TODAY = date(2026, 10, 27)
APP_DIR = Path(__file__).resolve().parents[1] / "app"


# ---------- D9 (a): static proof that only approval.py creates invoices ----------


def test_only_approval_py_writes_invoices() -> None:
    pattern = re.compile(r"\b(Invoice|InvoiceLineItem)\(|insert\((Invoice|InvoiceLineItem)\b")
    allowed = {APP_DIR / "services" / "approval.py", APP_DIR / "models.py"}
    offenders = [
        f"{path.relative_to(APP_DIR.parent)}:{n}"
        for path in APP_DIR.rglob("*.py")
        if path not in allowed
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == [], f"Invoices written outside approval.py: {offenders}"
    assert pattern.search((APP_DIR / "services" / "approval.py").read_text())


# ---------- helpers ----------


@pytest.fixture
def env(session_factory, tmp_path):
    with session_factory() as s:
        seed(s)
    storage = LocalStorage(tmp_path / "storage")
    state: dict = {}

    def run(
        inv, name: str, label_changes: dict | None = None, layout: str = "classic"
    ) -> uuid.UUID:
        rng = random.Random(name)
        g = write_invoice(inv, tmp_path / "gen", name, layout, False, rng)
        label = json.loads(g.label_file.read_text()) | (label_changes or {})
        doc_id = uuid.uuid4()
        data = g.file.read_bytes()
        storage.save(data, f"{doc_id}/original/{name}.pdf")
        import hashlib

        with session_factory() as s:
            s.add(
                Document(
                    id=doc_id,
                    filename=f"{name}.pdf",
                    storage_key=f"{doc_id}/original/{name}.pdf",
                    mime_type="application/pdf",
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            )
            s.commit()
        deps = PipelineDeps(
            session_factory, storage, lambda: FakeLLMProvider(label), today=lambda: TODAY
        )
        process_document(doc_id, deps)
        return doc_id

    state["run"] = run
    return state


def new_invoice(seed_value: int, vendors=None):
    rng = random.Random(seed_value)
    faker = Faker("en_IN")
    faker.seed_instance(seed_value)
    return make_invoice(rng, faker, TODAY, vendors)


def doc_status(sf, doc_id) -> tuple[str, list]:
    with sf() as s:
        d = s.get(Document, doc_id)
        return d.status, d.review_reasons


# ---------- pipeline + approval ----------


def test_clean_invoice_is_auto_approved_with_lines_and_audit(env, session_factory) -> None:
    inv = new_invoice(1)
    doc_id = env["run"](inv, "clean")
    assert doc_status(session_factory, doc_id) == ("auto_approved", [])
    with session_factory() as s:
        invoice = s.scalar(select(Invoice).where(Invoice.document_id == doc_id))
        assert invoice.approval_type == "auto" and invoice.approved_by is None
        assert invoice.total == inv.total and invoice.invoice_date == inv.invoice_date
        lines = s.scalars(
            select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id)
        ).all()
        assert len(lines) == len(inv.lines)
        ex = s.scalar(select(Extraction).where(Extraction.document_id == doc_id))
        assert ex.overall_confidence >= 0.85
        assert all(r["passed"] or r["severity"] == "warning" for r in ex.validation_results)
        assert (
            s.scalar(select(AuditLog).where(AuditLog.entity_id == doc_id)).action == "auto_approved"
        )


def test_failed_rule_goes_to_review_and_auto_approve_is_refused(env, session_factory) -> None:
    """D9 (b): approve() re-checks and refuses an extraction with a failed rule."""
    inv = new_invoice(2)
    wrong_total = f"{inv.total + 100:.2f}"
    doc_id = env["run"](inv, "bad_total", {"total": wrong_total})
    status, reasons = doc_status(session_factory, doc_id)
    assert status == "needs_review" and "totals_math" in reasons

    with session_factory() as s, pytest.raises(ApprovalRefused) as refused:
        approve(s, doc_id, approval_type="auto", today=TODAY)
    assert "totals_math" in refused.value.reasons

    clerk_id = _clerk_id(session_factory)
    with session_factory() as s, pytest.raises(ApprovalRefused) as refused:
        approve(s, doc_id, approval_type="human", user_id=clerk_id, today=TODAY)
    assert "totals_math" in refused.value.reasons, "a human must fix the values first"
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Invoice)) == 0


def test_human_approval_needs_a_user(env, session_factory) -> None:
    doc_id = env["run"](new_invoice(3, UNKNOWN_VENDORS), "needs_user")
    with session_factory() as s, pytest.raises(ApprovalRefused, match="login_required"):
        approve(s, doc_id, approval_type="human", today=TODAY)


def test_duplicate_goes_to_review_and_human_override_needs_note(env, session_factory) -> None:
    inv = new_invoice(4)
    first = env["run"](inv, "original", layout="classic")
    assert doc_status(session_factory, first)[0] == "auto_approved"

    copy = env["run"](inv, "rescan", layout="modern")  # same invoice, different file
    status, reasons = doc_status(session_factory, copy)
    # the failed rule also halves those fields' confidence (§10), so low_confidence too
    assert status == "needs_review" and "possible_duplicate" in reasons
    with session_factory() as s:
        ex = s.scalar(select(Extraction).where(Extraction.document_id == copy))
        original_invoice = s.scalar(select(Invoice).where(Invoice.document_id == first))
        assert ex.duplicate_of_invoice_id == original_invoice.id and ex.duplicate_score == 1.0

    clerk_id = _clerk_id(session_factory)
    with session_factory() as s, pytest.raises(ApprovalRefused, match="not_duplicate"):
        approve(s, copy, approval_type="human", user_id=clerk_id, today=TODAY)


def test_duplicate_of_document_still_in_review_is_linked(env, session_factory) -> None:
    inv = new_invoice(5, UNKNOWN_VENDORS)  # unknown vendor -> first copy waits in review
    first = env["run"](inv, "first")
    status, reasons = doc_status(session_factory, first)
    assert (
        status == "needs_review"
        and "vendor_known" in reasons
        and "possible_duplicate" not in reasons
    )
    second = env["run"](inv, "second", layout="two_column")
    assert {"vendor_known", "possible_duplicate"} <= set(doc_status(session_factory, second)[1])
    with session_factory() as s:
        ex = s.scalar(select(Extraction).where(Extraction.document_id == second))
        assert ex.duplicate_of_document_id == first and ex.duplicate_of_invoice_id is None


def test_human_approves_unknown_vendor_which_is_added_and_audited(env, session_factory) -> None:
    inv = new_invoice(6, UNKNOWN_VENDORS)
    doc_id = env["run"](inv, "new_vendor")
    clerk_id = _clerk_id(session_factory)
    with session_factory() as s:
        invoice = approve(s, doc_id, approval_type="human", user_id=clerk_id, today=TODAY)
        assert invoice.approval_type == "human" and invoice.approved_by == clerk_id
    with session_factory() as s:
        vendor = s.scalar(select(Vendor).where(Vendor.name == inv.vendor["name"]))
        assert vendor is not None
        actions = {a.action for a in s.scalars(select(AuditLog))}
        assert {"vendor_created", "approved"} <= actions
        assert s.get(Document, doc_id).status == "approved"
    with session_factory() as s, pytest.raises(ApprovalRefused, match="already_approved"):
        approve(s, doc_id, approval_type="human", user_id=clerk_id, today=TODAY)


def test_setting_off_auto_approves_and_adds_new_vendor(env, session_factory) -> None:
    with session_factory() as s:
        s.scalar(select(AppSettings)).require_review_for_new_vendor = False
        s.commit()
    inv = new_invoice(7, UNKNOWN_VENDORS)
    doc_id = env["run"](inv, "auto_new_vendor")
    assert doc_status(session_factory, doc_id)[0] == "auto_approved"
    with session_factory() as s:
        assert s.scalar(select(Vendor).where(Vendor.name == inv.vendor["name"])) is not None


def test_low_confidence_goes_to_review(env, session_factory) -> None:
    inv = new_invoice(8)
    # The model "reads" a vendor name that is not printed anywhere -> grounding fails
    doc_id = env["run"](
        inv, "hallucinated", {"vendor_name": inv.vendor["name"] + " Group Holdings"}
    )
    status, reasons = doc_status(session_factory, doc_id)
    assert status == "needs_review" and "low_confidence" in reasons


def _clerk_id(sf) -> uuid.UUID:
    from app.models import User

    with sf() as s:
        return s.scalar(select(User.id).where(User.role == "clerk"))
