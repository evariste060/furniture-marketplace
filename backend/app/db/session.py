import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

engine = create_engine(
    get_settings().database_url.get_secret_value(),
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"connect_timeout": 5},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def database_is_reachable(db: Session) -> bool:
    """Health probe: one bounded round trip. Never raises; failures are logged without the URL."""
    try:
        db.execute(text("SET LOCAL statement_timeout = '2s'"))
        db.execute(text("SELECT 1"))
        db.rollback()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", type(exc).__name__)
        db.rollback()
        return False
