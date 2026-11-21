"""How module 5 reads the SQLSTATE of a database error (psycopg 3 driver)."""

from types import SimpleNamespace

import psycopg
from sqlalchemy.exc import IntegrityError

from app.services.catalog_admin import (
    FOREIGN_KEY_VIOLATION,
    REFERENCED_ROW_STATES,
    RESTRICT_VIOLATION,
    _sqlstate,
)


class DiagnosticsOnly(Exception):
    """A driver error that reports its SQLSTATE only through diagnostics."""

    diag = SimpleNamespace(sqlstate="23503")


class NoSqlstate(Exception):
    sqlstate = None
    diag = None


def wrapped(orig: BaseException) -> IntegrityError:
    return IntegrityError("DELETE ...", {}, orig)


def test_referenced_row_sqlstates_come_from_the_psycopg_exception():
    # ON DELETE RESTRICT keys raise restrict_violation; NO ACTION keys foreign_key_violation.
    assert (FOREIGN_KEY_VIOLATION, RESTRICT_VIOLATION) == ("23503", "23001")
    assert REFERENCED_ROW_STATES == {"23503", "23001"}
    assert _sqlstate(wrapped(psycopg.errors.ForeignKeyViolation("x"))) == "23503"
    assert _sqlstate(wrapped(psycopg.errors.RestrictViolation("x"))) == "23001"
    assert _sqlstate(wrapped(psycopg.errors.UniqueViolation("x"))) == "23505"
    assert _sqlstate(wrapped(psycopg.errors.NotNullViolation("x"))) not in REFERENCED_ROW_STATES


def test_sqlstate_falls_back_to_diagnostics_and_is_none_when_unknown():
    assert _sqlstate(wrapped(DiagnosticsOnly())) == "23503"
    assert _sqlstate(wrapped(RuntimeError("no sqlstate"))) is None
    assert _sqlstate(wrapped(NoSqlstate())) is None
