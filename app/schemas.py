"""Pydantic request/response models for the API."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    display_name: str


class UploadResult(BaseModel):
    filename: str
    document_id: uuid.UUID | None = None
    status: str | None = None
    error: str | None = None


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    status: str
    review_reasons: list[Any]
    error_message: str | None
    page_count: int | None
    processing_ms: int | None
    created_at: datetime
    updated_at: datetime


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_name: str
    value_text: str | None
    normalized_value: str | None
    confidence: float | None
    source_match: float | None
    page_number: int | None
    bbox: dict[str, float] | None
    source_text: str | None
    line_item_index: int | None


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    model_name: str | None
    prompt_version: str | None
    doc_class: str | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None
    cost_usd: Decimal | None
    validation_results: list[dict[str, Any]] | None = None
    overall_confidence: float | None = None
    duplicate_of_invoice_id: uuid.UUID | None = None
    duplicate_of_document_id: uuid.UUID | None = None
    duplicate_score: float | None = None
    fields: list[FieldOut] = []


class DocumentDetail(DocumentSummary):
    extraction: ExtractionOut | None = None
    # The document a suspected duplicate points at (resolved from an invoice if needed).
    duplicate_document_id: uuid.UUID | None = None
    confidence_threshold: float | None = None


class QueueItem(BaseModel):
    id: uuid.UUID
    filename: str
    vendor_name: str | None
    invoice_number: str | None
    total: str | None
    review_reasons: list[str]
    created_at: datetime
    age_seconds: int


class FieldChange(BaseModel):
    """Set one value. A line_item_index that doesn't exist yet adds a new line."""

    field_name: str
    line_item_index: int | None = None
    value: str | None


class FieldCorrections(BaseModel):
    changes: list[FieldChange] = []
    delete_lines: list[int] = []


class ApproveRequest(BaseModel):
    note: str | None = None  # required to override a possible duplicate


class RejectRequest(BaseModel):
    reason: str = Field(min_length=3)
