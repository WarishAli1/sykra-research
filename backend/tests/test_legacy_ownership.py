"""Ownership tests for the persistent legacy-session boundary.

Run with:
  TEST_DATABASE_URL=... PYTHONPATH=backend pytest backend/tests
"""

import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, UploadedFile, User
from app.services.ownership import require_research_session


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required",
)


@pytest.fixture()
def db():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_legacy_session_is_owned_and_cross_user_access_is_404(db):
    first = User(email=f"{uuid4()}@example.com", password_hash="not-used")
    second = User(email=f"{uuid4()}@example.com", password_hash="not-used")
    db.add_all([first, second])
    db.commit()

    owned = require_research_session(db, first, "session-a", create=True)
    assert owned.user_id == first.id
    assert require_research_session(db, first, "session-a").id == owned.id

    with pytest.raises(HTTPException) as error:
        require_research_session(db, second, "session-a")
    assert error.value.status_code == 404


def test_unknown_session_and_file_are_not_resolvable(db):
    user = User(email=f"{uuid4()}@example.com", password_hash="not-used")
    db.add(user)
    db.commit()

    with pytest.raises(HTTPException) as error:
        require_research_session(db, user, "missing-session")
    assert error.value.status_code == 404

    session = require_research_session(db, user, "session-b", create=True)
    uploaded = UploadedFile(
        session_id=session.id,
        user_id=user.id,
        original_filename="paper.pdf",
        stored_filename="random-paper.pdf",
        size_bytes=12,
    )
    db.add(uploaded)
    db.commit()
    assert uploaded.user_id == user.id
