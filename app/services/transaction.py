"""One database transaction per business operation."""
from contextlib import contextmanager

from ..extensions import db


@contextmanager
def unit_of_work():
    """Commit once at the end, or roll back everything if anything fails.

    Row locks taken with SELECT ... FOR UPDATE are held until this commit/rollback,
    so helpers used inside a unit of work must never commit on their own.
    """
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
