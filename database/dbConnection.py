"""Database connection, pooling, and session management.
Follows the EduJunction database pattern.
"""
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session, Session
from utils.config import config
from utils.logger import logger

# SQLAlchemy Base for all models
Base = declarative_base()

# Engine creation with connection pooling and pre-ping
engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    future=True
)

SessionFactory = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False
)

SessionLocal = scoped_session(SessionFactory)


def register_db_teardown(app):
    """Ensures the scoped SQLAlchemy session is removed at the end of every request."""
    @app.teardown_appcontext
    def remove_session(_exception=None):
        SessionLocal.remove()


@contextmanager
def get_session():
    """Context-managed session: commits on success, rolls back on error."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        session.close()


def db_health_check() -> bool:
    """Verifies MySQL database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False


def init_db():
    """Creates all registered database tables if they do not exist."""
    from model import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")

