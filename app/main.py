"""FastAPI app factory."""

import logging

from fastapi import FastAPI
from sqlalchemy import text

from app.api import auth, dashboard, documents, review, settings
from app.db import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(title="Invoice Intake API", version="0.1.0")
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
