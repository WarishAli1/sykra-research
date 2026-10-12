"""Integration coverage for the auth boundary.

Run against an isolated PostgreSQL database with TEST_DATABASE_URL set:
  TEST_DATABASE_URL=... pytest backend/tests/test_auth_and_idor.py
"""

import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import get_db
from app.db.models import Base, Chat
from fastapi import FastAPI
from app.api.routes import auth, chats

app = FastAPI()
app.include_router(auth.router, prefix="/api")
app.include_router(chats.router, prefix="/api")


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is required")


@pytest.fixture()
def client():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        test_client._test_factory = factory
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_signup_login_logout_sets_and_revokes_cookie(client):
    response = client.post("/api/auth/signup", json={"email": "a@example.com", "password": "Correct horse battery staple!7", "name": "A"})
    assert response.status_code == 201
    assert "sykra_session=" in response.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_short_password_is_rejected(client):
    response = client.post("/api/auth/signup", json={"email": "a@example.com", "password": "short"})
    assert response.status_code == 422


def test_other_users_chat_is_not_visible(client):
    first = client.post("/api/auth/signup", json={"email": "a@example.com", "password": "Correct horse battery staple!7"})
    assert first.status_code == 201
    chat_id = str(uuid4())
    with client._test_factory() as db:
        db.add(Chat(id=UUID(chat_id), user_id=UUID(first.json()["id"]), title="Private"))
        db.commit()
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/signup", json={"email": "b@example.com", "password": "Correct horse battery staple!7"}).status_code == 201
    assert client.get(f"/api/chats/{chat_id}").status_code == 404
