"""FastAPI app factory."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api import auth, dashboard, documents, review, settings
from app.db import SessionLocal, engine
from app.pipeline.orchestrator import recover_interrupted

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if os.environ.get("RECOVER_ON_STARTUP", "1") == "1":
        try:
            with SessionLocal() as session:
                recover_interrupted(session)
        except Exception:  # the API must still start if the DB is briefly unavailable
            logging.getLogger(__name__).exception("startup recovery failed")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Invoice Intake API", version="0.1.0", lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(review.router)
    app.include_router(dashboard.router)
    app.include_router(settings.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception as exc:  # report, don't crash the health check
            db_status = f"error: {type(exc).__name__}"
        return {"status": "ok", "database": db_status}

    return app


app = create_app()
