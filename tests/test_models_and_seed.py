from sqlalchemy import Numeric, func, select
from sqlalchemy.orm import Session

from app.models import AppSettings, Base, Invoice, InvoiceLineItem, User, Vendor
from app.pipeline.normalize import normalize_vendor_name
from app.seed import seed
from app.seed_data import KNOWN_VENDORS, UNKNOWN_VENDORS

SPEC_TABLES = {
    "users",
    "vendors",
    "documents",
    "extractions",
    "extracted_fields",
    "invoices",
    "invoice_line_items",
    "audit_log",
    "settings",
}


def test_all_spec_tables_defined() -> None:
    assert set(Base.metadata.tables) == SPEC_TABLES


def test_money_columns_are_numeric_14_2() -> None:
    for col in ("subtotal", "tax", "total"):
        t = Invoice.__table__.c[col].type
        assert isinstance(t, Numeric) and (t.precision, t.scale) == (14, 2)
    for col in ("unit_price", "amount"):
        t = InvoiceLineItem.__table__.c[col].type
        assert (t.precision, t.scale) == (14, 2)
    assert Invoice.__table__.c.total.type.asdecimal


def test_d2_duplicate_document_link_exists() -> None:
    from app.models import Extraction

    assert "duplicate_of_document_id" in Extraction.__table__.c


def test_invoice_unique_vendor_number() -> None:
    names = {c.name for c in Invoice.__table__.constraints}
    assert "uq_invoices_vendor_number" in names


def test_normalize_vendor_name() -> None:
    assert normalize_vendor_name("Apex Industrial Supplies Pvt. Ltd.") == "apex industrial supplies"
    assert normalize_vendor_name("  Bharat  Packaging Co ") == "bharat packaging"
    assert normalize_vendor_name("Nova Tools & Hardware") == "nova tools hardware"


def test_seed_vendor_lists() -> None:
    assert len(KNOWN_VENDORS) == 15
    normalized = [normalize_vendor_name(v["name"]) for v in KNOWN_VENDORS + UNKNOWN_VENDORS]
    assert len(set(normalized)) == len(normalized), "normalized vendor names are unique"


# ---------- database tests (need Postgres; skipped if it is not reachable) ----------


def test_seed_is_idempotent(db_session: Session) -> None:
    first = seed(db_session)
    assert first == {"users": 2, "vendors": 15, "settings": 1}
    second = seed(db_session)
    assert second == {"users": 0, "vendors": 0, "settings": 0}

    assert db_session.scalar(select(func.count()).select_from(User)) == 2
    assert db_session.scalar(select(func.count()).select_from(Vendor)) == 15
    settings = db_session.scalar(select(AppSettings))
    assert settings.confidence_threshold == 0.85
    assert str(settings.amount_tolerance) == "0.01"
    roles = set(db_session.scalars(select(User.role)))
    assert roles == {"clerk", "manager"}
    clerk = db_session.scalar(select(User).where(User.email == "clerk@meridian.test"))
    assert clerk.password_hash.startswith("$2"), "passwords are bcrypt-hashed"
