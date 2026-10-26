import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("SESSION_SECRET", "test-secret-not-for-production")

import random  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

from faker import Faker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.documents import get_pipeline_deps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.pipeline.orchestrator import PipelineDeps  # noqa: E402
from app.seed import seed  # noqa: E402
from app.storage import LocalStorage  # noqa: E402
from data.generator.generate import write_invoice  # noqa: E402
from data.generator.model import make_invoice  # noqa: E402
from tests.fakes import FakeLLMProvider  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """A throwaway Postgres database for one test, dropped afterwards. Skips if no Postgres."""
    base_url = make_url(os.environ.get("DATABASE_URL", get_settings().database_url))
    test_db = f"invoice_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:
        pytest.skip(f"Postgres not reachable: {type(exc).__name__}")
    engine = create_engine(base_url.set(database=test_db))
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{test_db}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def invoice(tmp_path: Path):
    rng = random.Random(8)
    faker = Faker("en_IN")
    faker.seed_instance(8)
    return write_invoice(
        make_invoice(rng, faker, date(2026, 10, 26)), tmp_path, "inv", "modern", False, rng
    )


@pytest.fixture
def api(session_factory, tmp_path):
    """TestClient wired to the test DB, temp storage and a swappable fake LLM."""
    with session_factory() as s:
        seed(s)
    state = {"fake": FakeLLMProvider({})}
    deps = PipelineDeps(session_factory, LocalStorage(tmp_path / "storage"), lambda: state["fake"])

    def session_override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_pipeline_deps] = lambda: deps
    with TestClient(app) as client:
        yield client, state
    app.dependency_overrides.clear()


def login(
    client: TestClient, email: str = "clerk@meridian.test", pw: str = "clerk-demo-123"
) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
