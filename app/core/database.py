"""Database engine, session factory, and declarative base."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.is_sqlite else {},
    pool_pre_ping=True,
    echo=settings.DEBUG and not settings.is_sqlite,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    The session is closed automatically after the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables.  Useful for tests and first-run bootstrapping.

    In production, Alembic migrations should be used instead.
    """
    # Import models so they register with the Base metadata
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
