"""audit action vendor_created (D19)

Revision ID: cdbaf8981f8b
Revises: f0178a3cf308
Create Date: 2026-10-26 18:38:49.249892
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'cdbaf8981f8b'
down_revision: str | None = 'f0178a3cf308'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD = "'field_corrected', 'approved', 'rejected', 'auto_approved', 'retry', 'settings_changed'"
NEW = OLD + ", 'vendor_created'"


def upgrade() -> None:
    # Autogenerate does not detect CHECK constraint changes, so this is written by hand.
    op.drop_constraint("ck_audit_log_action", "audit_log", type_="check")
    op.create_check_constraint("ck_audit_log_action", "audit_log", f"action IN ({NEW})")


def downgrade() -> None:
    op.drop_constraint("ck_audit_log_action", "audit_log", type_="check")
    op.create_check_constraint("ck_audit_log_action", "audit_log", f"action IN ({OLD})")
