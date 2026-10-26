"""SQLAlchemy models for every table in spec §6.

Money columns are NUMERIC(14,2) and map to Decimal (rule 5).
Only app/services/approval.py may create Invoice / InvoiceLineItem rows (rule 1).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(14, 2)

DOCUMENT_STATUSES = (
    "uploaded",
    "processing",
    "failed",
    "needs_review",
    "auto_approved",
    "approved",
    "rejected",
)
USER_ROLES = ("clerk", "manager")
APPROVAL_TYPES = ("auto", "human")
AUDIT_ACTIONS = (
    "field_corrected",
    "approved",
    "rejected",
    "auto_approved",
    "retry",
    "settings_changed",
    "vendor_created",  # D19
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(IdMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", USER_ROLES), name="ck_users_role"),)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)


class Vendor(IdMixin, Base):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    tax_id: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Document(IdMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(_in("status", DOCUMENT_STATUSES), name="ck_documents_status"),
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="uploaded")
    review_reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Extraction(IdMixin, Base):
    """Staging: one row per processing run of a document."""

    __tablename__ = "extractions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    raw_llm_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    doc_class: Mapped[str | None] = mapped_column(String(30))
    validation_results: Mapped[list[Any] | None] = mapped_column(JSONB)
    duplicate_of_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", use_alter=True, name="fk_extractions_duplicate_invoice")
    )
    # D2: a duplicate may also point at a document that is not approved yet.
    duplicate_of_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    duplicate_score: Mapped[float | None] = mapped_column(Float)
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    llm_input_tokens: Mapped[int | None] = mapped_column(Integer)
    llm_output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 5))


class ExtractedField(IdMixin, Base):
    """Staging: one row per extracted value, with its source location (rule 2)."""

    __tablename__ = "extracted_fields"

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_text: Mapped[str | None] = mapped_column(Text)
    # D17: grounding match score (0-1), the "base" of the §10 confidence formula.
    source_match: Mapped[float | None] = mapped_column(Float)
    line_item_index: Mapped[int | None] = mapped_column(Integer)


class Invoice(IdMixin, Base):
    """Final table. Written ONLY by app/services/approval.py."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint(
            "vendor_id", "invoice_number_normalized", name="uq_invoices_vendor_number"
        ),
        CheckConstraint(_in("approval_type", APPROVAL_TYPES), name="ck_invoices_approval_type"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), unique=True, nullable=False
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extractions.id"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_number_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax: Mapped[Decimal | None] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    approval_type: Mapped[str] = mapped_column(String(10), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InvoiceLineItem(IdMixin, Base):
    __tablename__ = "invoice_line_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    amount: Mapped[Decimal | None] = mapped_column(Money)


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint(_in("action", AUDIT_ACTIONS), name="ck_audit_log_action"),)

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(50))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)


class AppSettings(IdMixin, Base):
    """Single-row table of tunable business settings."""

    __tablename__ = "settings"

    confidence_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.85"
    )
    require_review_for_new_vendor: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    amount_tolerance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0.01"
    )
    max_due_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="180")
