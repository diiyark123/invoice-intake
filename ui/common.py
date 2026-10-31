"""Shared UI helpers: session, plain-language labels, status colours."""

from typing import Any

import streamlit as st
from api_client import ApiClient

STATUS_LABELS = {
    "uploaded": ("Waiting", "gray"),
    "processing": ("Reading…", "blue"),
    "failed": ("Failed", "red"),
    "needs_review": ("Needs review", "orange"),
    "auto_approved": ("Approved (automatic)", "green"),
    "approved": ("Approved", "green"),
    "rejected": ("Rejected", "gray"),
}

REASON_LABELS = {
    "required_fields": "Some required details are missing",
    "line_items_sum": "Line amounts don't add up to the subtotal",
    "line_math": "Quantity × price doesn't equal the line amount",
    "totals_math": "Subtotal + tax doesn't equal total",
    "positive_amounts": "Total is zero or negative",
    "date_valid": "Invoice date is missing, in the future, or over 2 years old",
    "due_after_invoice": "Due date is before the invoice date or too far after it",
    "vendor_known": "Vendor is not in our vendor list",
    "possible_duplicate": "Looks like a duplicate of another invoice",
    "already_recorded": "This vendor's invoice number is already in the system",
    "low_confidence": "Some values were hard to read — please check them",
    "low_image_quality": "The scan or photo is blurry",
    "credit_note": "This looks like a credit note, not an invoice",
    "multi_invoice": "This file seems to contain more than one invoice",
    "delivery_note": "This looks like a delivery note, not an invoice",
    "other": "This doesn't look like an invoice",
}

FIELD_LABELS = {
    "vendor_name": "Vendor",
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "currency": "Currency",
    "subtotal": "Subtotal",
    "tax": "Tax",
    "total": "Total",
}


def client() -> ApiClient:
    """The API client for this browser session (tests can put a fake in session_state)."""
    if "api" not in st.session_state:
        st.session_state.api = ApiClient()
    return st.session_state.api


def current_user() -> dict[str, Any] | None:
    return st.session_state.get("user")


def require_login(role: str | None = None) -> dict[str, Any]:
    user = current_user()
    if user is None:
        st.warning("Please log in first.")
        st.stop()
    if role and user["role"] != role:
        st.error("This page is for AP managers only.")
        st.stop()
    return user


def reason_text(reason: str) -> str:
    return REASON_LABELS.get(reason, reason.replace("_", " ").capitalize())


def status_badge(status: str) -> str:
    label, color = STATUS_LABELS.get(status, (status, "gray"))
    return f":{color}-badge[{label}]"


def confidence_badge(conf: float | None, threshold: float, has_value: bool = True) -> str:
    if not has_value:
        return ""
    if conf is None:
        return ":gray-badge[not scored]"
    if conf >= threshold:
        return f":green-badge[{conf:.0%} sure]"
    if conf >= threshold / 2:
        return f":orange-badge[{conf:.0%} sure]"
    return f":red-badge[{conf:.0%} sure]"


def human_age(seconds: int) -> str:
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} days"
