"""Manager-only: business settings and the vendor list. Every change is audited."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_manager
from app.db import get_session
from app.models import AppSettings, Vendor
from app.pipeline.normalize import normalize_vendor_name
from app.services import audit

router = APIRouter(tags=["settings"])
SessionDep = Annotated[Session, Depends(get_session)]
ManagerDep = Annotated[CurrentUser, Depends(require_manager)]


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    confidence_threshold: float
    require_review_for_new_vendor: bool
    amount_tolerance: Decimal
    max_due_days: int


class SettingsUpdate(BaseModel):
    confidence_threshold: float | None = Field(None, ge=0, le=1)
    require_review_for_new_vendor: bool | None = None
    amount_tolerance: Decimal | None = Field(None, ge=0, le=1000, decimal_places=2)
    max_due_days: int | None = Field(None, ge=1, le=3650)


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    normalized_name: str
    aliases: list[str]
    tax_id: str | None
    is_active: bool


class VendorIn(BaseModel):
    name: str = Field(min_length=2)
    aliases: list[str] = []
    tax_id: str | None = None
    is_active: bool = True


def _settings_row(session: Session) -> AppSettings:
    row = session.scalar(select(AppSettings))
    if row is None:
        row = AppSettings()
        session.add(row)
        session.flush()
    return row


@router.get("/settings")
def get_app_settings(session: SessionDep, _: ManagerDep) -> SettingsOut:
    return SettingsOut.model_validate(_settings_row(session))


@router.put("/settings")
def update_app_settings(body: SettingsUpdate, session: SessionDep, user: ManagerDep) -> SettingsOut:
    row = _settings_row(session)
    for name, value in body.model_dump(exclude_none=True).items():
        old = getattr(row, name)
        if old == value:
            continue
        setattr(row, name, value)
        audit.record(
            session,
            entity_type="settings",
            entity_id=row.id,
            action="settings_changed",
            user_id=user.id,
            field_name=name,
            old_value=str(old),
            new_value=str(value),
        )
    session.commit()
    return SettingsOut.model_validate(row)


@router.get("/vendors")
def list_vendors(session: SessionDep, _: ManagerDep) -> list[VendorOut]:
    return [
        VendorOut.model_validate(v) for v in session.scalars(select(Vendor).order_by(Vendor.name))
    ]


def _clean(body: VendorIn) -> dict:
    aliases = sorted({a.strip() for a in body.aliases if a.strip()})
    return {
        "name": body.name.strip(),
        "normalized_name": normalize_vendor_name(body.name),
        "aliases": aliases,
        "tax_id": (body.tax_id or "").strip() or None,
        "is_active": body.is_active,
    }


@router.post("/vendors", status_code=status.HTTP_201_CREATED)
def create_vendor(body: VendorIn, session: SessionDep, user: ManagerDep) -> VendorOut:
    vendor = Vendor(**_clean(body))
    session.add(vendor)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A vendor with this name already exists"
        ) from exc
    audit.record(
        session,
        entity_type="vendor",
        entity_id=vendor.id,
        action="vendor_created",
        user_id=user.id,
        new_value=vendor.name,
    )
    session.commit()
    return VendorOut.model_validate(vendor)


@router.put("/vendors/{vendor_id}")
def update_vendor(
    vendor_id: uuid.UUID, body: VendorIn, session: SessionDep, user: ManagerDep
) -> VendorOut:
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    for name, value in _clean(body).items():
        old = getattr(vendor, name)
        if old == value:
            continue
        setattr(vendor, name, value)
        if name != "normalized_name":
            audit.record(
                session,
                entity_type="vendor",
                entity_id=vendor.id,
                action="settings_changed",
                user_id=user.id,
                field_name=name,
                old_value=str(old),
                new_value=str(value),
            )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A vendor with this name already exists"
        ) from exc
    return VendorOut.model_validate(vendor)
