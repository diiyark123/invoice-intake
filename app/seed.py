"""Seed demo users, vendors and the settings row. Safe to run more than once.

Run: python -m app.seed
Demo passwords can be overridden with SEED_CLERK_PASSWORD / SEED_MANAGER_PASSWORD.
"""

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.db import SessionLocal
from app.models import AppSettings, User, Vendor
from app.pipeline.normalize import normalize_vendor_name
from app.seed_data import KNOWN_VENDORS

logger = logging.getLogger(__name__)


def _demo_users() -> list[dict[str, str]]:
    return [
        {
            "email": "clerk@meridian.test",
            "role": "clerk",
            "display_name": "Asha (AP Clerk)",
            "password": os.environ.get("SEED_CLERK_PASSWORD", "clerk-demo-123"),
        },
        {
            "email": "manager@meridian.test",
            "role": "manager",
            "display_name": "Ravi (AP Manager)",
            "password": os.environ.get("SEED_MANAGER_PASSWORD", "manager-demo-123"),
        },
    ]


def seed(session: Session) -> dict[str, int]:
    """Insert anything missing; never duplicates or overwrites existing rows."""
    added = {"users": 0, "vendors": 0, "settings": 0}

    for u in _demo_users():
        if session.scalar(select(User).where(User.email == u["email"])) is None:
            session.add(
                User(
                    email=u["email"],
                    role=u["role"],
                    display_name=u["display_name"],
                    password_hash=hash_password(u["password"]),
                )
            )
            added["users"] += 1

    for v in KNOWN_VENDORS:
        normalized = normalize_vendor_name(v["name"])
        if session.scalar(select(Vendor).where(Vendor.normalized_name == normalized)) is None:
            session.add(
                Vendor(
                    name=v["name"],
                    normalized_name=normalized,
                    aliases=v["aliases"],
                    tax_id=v["tax_id"],
                )
            )
            added["vendors"] += 1

    if session.scalar(select(AppSettings)) is None:
        session.add(AppSettings())
        added["settings"] += 1

    session.commit()
    return added


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as session:
        added = seed(session)
    logger.info("Seed complete, rows added: %s", added)


if __name__ == "__main__":
    main()
