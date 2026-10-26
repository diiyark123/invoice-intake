"""Write rows to audit_log (rule 2: every human action is recorded)."""

import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    session: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    user_id: uuid.UUID | None = None,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    note: str | None = None,
) -> AuditLog:
    """Add an audit row to the session; the caller commits it with the change it describes."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        note=note,
    )
    session.add(entry)
    return entry
