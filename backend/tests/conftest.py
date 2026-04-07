import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings


@pytest.fixture(autouse=True)
def test_settings(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    podcasts_dir = tmp_path / "podcasts"
    podcasts_dir.mkdir()

    test_settings = Settings(
        database_path=str(db_path),
        podcasts_dir=str(podcasts_dir),
        redis_url="redis://localhost:6379/15",
        debug=True,
    )

    monkeypatch.setattr("app.config.settings", test_settings)
    monkeypatch.setattr(
        "app.database.engine",
        create_engine(
            test_settings.database_url,
            connect_args={"check_same_thread": False},
        ),
    )

    # Set Celery to eager mode so tasks run synchronously without Redis
    from app.worker import celery_app

    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=False,
    )

    from app.database import engine, init_db

    SQLModel.metadata.create_all(engine)
    init_db()

    return test_settings


@pytest.fixture
def session(test_settings):
    from app.database import engine

    with Session(engine) as session:
        yield session


@pytest.fixture
def client(test_settings):
    from app.database import engine, get_session
    from app.main import app

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
