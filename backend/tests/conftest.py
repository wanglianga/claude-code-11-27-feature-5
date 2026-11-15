import os

os.environ["DATABASE_URL"] = (
    "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/ccdev_test"
)

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        for table in reversed(Base.metadata.sorted_tables):
            with engine.begin() as conn:
                conn.execute(table.delete())


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def buyer_headers(client, db):
    from app.models import User
    u = User(username="b1", password="p", display_name="采购", role="buyer")
    db.add(u)
    db.commit()
    return {"X-User-Id": str(u.id)}


@pytest.fixture()
def checker_headers(client, db):
    from app.models import User
    u = User(username="c1", password="p", display_name="验收", role="checker")
    db.add(u)
    db.commit()
    return {"X-User-Id": str(u.id)}
