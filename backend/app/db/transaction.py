from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def atomic(db: Session) -> Iterator[Session]:
    """Commit everything done inside the block (business change + audit record) together.

    Repositories only flush; this is the single commit point. Any exception, including a failed
    audit insert, rolls the whole unit back, so a protected change never persists unaudited.
    """
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
