"""Seed demo users, vendors and the settings row. Safe to run more than once.

Run: python -m app.seed
Demo passwords can be overridden with SEED_CLERK_PASSWORD / SEED_MANAGER_PASSWORD.
With APP_ENV=production those two variables are required (the demo passwords are public),
and changing one and re-running the seed resets that user's password.
"""

import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.db import SessionLocal
from app.models import AppSettings, User, Vendor
from app.pipeline.normalize import normalize_vendor_name
from app.seed_data import KNOWN_VENDORS

logger = logging.getLogger(__name__)


MIN_PASSWORD_LENGTH = 10


class SeedConfigError(RuntimeError):
    pass


def _password(env_var: str, demo: str) -> tuple[str, bool]:
    """Return (password, explicitly_set)."""
    value = os.environ.get(env_var, "")
    if value:
        if len(value) < MIN_PASSWORD_LENGTH:
            raise SeedConfigError(f"{env_var} must be at least {MIN_PASSWORD_LENGTH} characters")
        return value, True
    if os.environ.get("APP_ENV") == "production":
        raise SeedConfigError(f"{env_var} must be set in production (demo passwords are public)")
    return demo, False


def _demo_users() -> list[dict[str, Any]]:
    users = []
    for email, role, name, env_var, demo in (
        (
            "clerk@meridian.test",
            "clerk",
            "Asha (AP Clerk)",
            "SEED_CLERK_PASSWORD",
            "clerk-demo-123",
        ),
        (
            "manager@meridian.test",
            "manager",
            "Ravi (AP Manager)",
            "SEED_MANAGER_PASSWORD",
            "manager-demo-123",
        ),
    ):
        password, explicit = _password(env_var, demo)
        users.append(
            {
                "email": email,
                "role": role,
                "display_name": name,
                "password": password,
                "explicit": explicit,
            }
        )
    return users


def seed(session: Session) -> dict[str, int]:
    """Insert anything missing; never duplicates rows. An explicitly set password that no
    longer matches is reset (the only way to change a password on hosts without a shell)."""
    added = {"users": 0, "vendors": 0, "settings": 0}

    for u in _demo_users():
        user = session.scalar(select(User).where(User.email == u["email"]))
        if user is None:
            session.add(
                User(
                    email=u["email"],
                    role=u["role"],
                    display_name=u["display_name"],
                    password_hash=hash_password(u["password"]),
                )
            )
            added["users"] += 1
        elif u["explicit"] and not verify_password(u["password"], user.password_hash):
            user.password_hash = hash_password(u["password"])
            logger.info("Password reset from environment for %s", u["email"])

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
