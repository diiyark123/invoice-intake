from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_manager
from app.db import get_session
from app.services.dashboard import metrics

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics")
def dashboard_metrics(
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[CurrentUser, Depends(require_manager)],
) -> dict[str, Any]:
    return metrics(session)
