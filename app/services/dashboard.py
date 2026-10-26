"""Dashboard numbers for the AP manager (spec §12.5)."""

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Document, Extraction

MONTHLY_VOLUME = 2000  # Meridian's expected invoices per month (spec §1)
PROCESSED = ("needs_review", "auto_approved", "approved", "rejected", "failed")


def _period_starts(now: datetime) -> dict[str, datetime]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": today,
        "this_week": today - timedelta(days=today.weekday()),
        "this_month": today.replace(day=1),
    }


def field_group(field_name: str | None) -> str:
    """'line_items.3.amount' -> 'line item: amount'; a deleted line -> 'line item: deleted'."""
    if not field_name:
        return "unknown"
    m = re.fullmatch(r"line_items\.\d+(?:\.(\w+))?", field_name)
    if m:
        return f"line item: {m.group(1) or 'deleted'}"
    return field_name


def metrics(session: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    starts = _period_starts(now)
    month = starts["this_month"]

    processed = {
        name: session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.created_at >= start, Document.status.in_(PROCESSED))
        )
        or 0
        for name, start in starts.items()
    }
    month_docs = session.execute(
        select(Document.status, Document.processing_ms).where(
            Document.created_at >= month, Document.status.in_(PROCESSED)
        )
    ).all()
    finished = [s for s, _ in month_docs if s != "failed"]
    times = [ms for _, ms in month_docs if ms is not None]

    oldest = session.scalar(
        select(func.min(Document.created_at)).where(Document.status == "needs_review")
    )
    queue_size = session.scalar(
        select(func.count()).select_from(Document).where(Document.status == "needs_review")
    )

    corrections = Counter(
        field_group(name)
        for name in session.scalars(
            select(AuditLog.field_name).where(AuditLog.action == "field_corrected")
        )
    )

    costs = [
        c
        for c in session.scalars(
            select(Extraction.cost_usd).where(
                Extraction.created_at >= month, Extraction.cost_usd.is_not(None)
            )
        )
    ]
    cost_per_invoice = sum(costs, Decimal(0)) / len(costs) if costs else None
    days_elapsed = max((now - month).total_seconds() / 86400, 1.0)
    pace = processed["this_month"] / days_elapsed * 30

    return {
        "processed": processed,
        "auto_approval_rate": (
            round(sum(s == "auto_approved" for s in finished) / len(finished), 4)
            if finished
            else None
        ),
        "queue_size": queue_size or 0,
        "oldest_in_queue_hours": (
            round((now - oldest).total_seconds() / 3600, 1) if oldest else None
        ),
        "failed": session.scalar(
            select(func.count()).select_from(Document).where(Document.status == "failed")
        )
        or 0,
        "avg_processing_seconds": round(sum(times) / len(times) / 1000, 1) if times else None,
        "corrections_by_field": dict(corrections.most_common()),
        "llm_cost_per_invoice_usd": float(round(cost_per_invoice, 5)) if cost_per_invoice else None,
        "projected_monthly_cost_usd": (
            float(round(cost_per_invoice * MONTHLY_VOLUME, 2)) if cost_per_invoice else None
        ),
        "projected_monthly_volume_at_current_pace": round(pace),
        "monthly_volume_assumed": MONTHLY_VOLUME,
    }
