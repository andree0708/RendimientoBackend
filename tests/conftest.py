"""Pytest configuration and shared fixtures."""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import Role, User

# In-memory SQLite shared across the test session via StaticPool
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_database():
    """Create fresh tables before each test, drop after."""
    import app.models  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """Provide a database session for tests."""
    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client(db):
    """HTTP test client with database override."""
    app.dependency_overrides[get_db] = override_get_db

    # Also patch the WebSocket session factory to use the test DB
    from app.api.routes import ws as ws_module
    original_get_session = ws_module.get_ws_session
    ws_module.get_ws_session = lambda: TestingSessionLocal()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    ws_module.get_ws_session = original_get_session


@pytest.fixture
def test_user(db):
    """Create a test user and return (user, token)."""
    role = db.query(Role).filter(Role.name == "worker").first()
    if not role:
        role = Role(name="worker", description="Test worker role")
        db.add(role)
        db.flush()

    user = User(
        email="testuser@worksense.ai",
        full_name="Test User",
        hashed_password=hash_password("testpass123"),
        is_active=True,
        is_superuser=False,
    )
    user.roles.append(role)
    db.add(user)
    db.flush()

    from app.models.compliance import ConsentRecord
    consent = ConsentRecord(user_id=user.id, granted=True, scope="all", version="1.0")
    db.add(consent)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, extra_claims={"email": user.email})
    return user, token


@pytest.fixture
def admin_user(db):
    """Create a superuser and return (user, token)."""
    role = db.query(Role).filter(Role.name == "worker").first()
    if not role:
        role = Role(name="worker", description="Test worker role")
        db.add(role)
        db.flush()

    user = User(
        email="admin@worksense.ai",
        full_name="Admin User",
        hashed_password=hash_password("adminpass123"),
        is_active=True,
        is_superuser=True,
    )
    user.roles.append(role)
    db.add(user)
    db.flush()

    from app.models.compliance import ConsentRecord
    consent = ConsentRecord(user_id=user.id, granted=True, scope="all", version="1.0")
    db.add(consent)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, extra_claims={"email": user.email})
    return user, token


@pytest.fixture
def auth_headers(test_user):
    """Return Authorization headers for a test user."""
    _, token = test_user
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user):
    """Return Authorization headers for the admin user."""
    _, token = admin_user
    return {"Authorization": f"Bearer {token}"}
