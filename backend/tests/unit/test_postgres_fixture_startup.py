import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import psycopg
import pytest

from tests.postgres.conftest import (
    SUITE_LOCK_KEY,
    Stack,
    _acquire_suite_lock,
    _start_server,
    _wait_for_server,
)


class LockConnection:
    """Records the advisory-lock query and answers it like PostgreSQL would."""

    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...]) -> "LockConnection":
        self.queries.append((query, params))
        return self

    def fetchone(self) -> tuple[bool]:
        return (self.acquired,)


def test_uvicorn_exit_is_reported_with_connection_credentials_redacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_url = "postgresql+psycopg://test_user:test_password@localhost/test_db"
    log_path = tmp_path / "server.log"
    log_path.write_text(f"ModuleNotFoundError: {database_url}", encoding="utf-8")

    class ExitedProcess:
        def poll(self) -> int:
            return 1

    process = cast(subprocess.Popen[bytes], ExitedProcess())

    def unexpected_request(*args: object, **kwargs: object) -> None:
        pytest.fail("readiness polling should stop when Uvicorn exits")

    monkeypatch.setattr("tests.postgres.conftest.httpx.get", unexpected_request)

    with pytest.raises(RuntimeError, match="exited before readiness") as error:
        _wait_for_server(process, "http://127.0.0.1:5000/api/v1", log_path, (database_url,))

    message = str(error.value)
    assert "ModuleNotFoundError" in message
    assert "test_password" not in message


def test_server_output_never_blocks_the_server(tmp_path: Path) -> None:
    # Far more than a pipe buffer: with stdout=PIPE and no reader this child would hang, as the
    # uvicorn servers did after a few logged 500 tracebacks.
    log_path = tmp_path / "server.log"
    chatty = "import sys; sys.stdout.write('x' * 2_000_000); sys.stdout.flush()"

    proc = _start_server([sys.executable, "-c", chatty], dict(os.environ), log_path)

    assert proc.wait(timeout=30) == 0
    assert log_path.stat().st_size >= 2_000_000


def test_stack_repr_does_not_render_connection_urls() -> None:
    stack = Stack(
        servers=["http://127.0.0.1:5000/api/v1"],
        owner_url="postgresql+psycopg://owner:owner_password@localhost/test_db",
        runtime_url="postgresql+psycopg://runtime:runtime_password@localhost/test_db",
        redis_url="redis://:redis_password@localhost:6379/15",
    )

    representation = repr(stack)

    assert "owner_password" not in representation
    assert "runtime_password" not in representation
    assert "redis_password" not in representation


def test_suite_lock_is_taken_without_waiting_for_a_holder() -> None:
    conn = LockConnection(acquired=True)

    _acquire_suite_lock(cast(psycopg.Connection, conn))

    assert conn.queries == [("SELECT pg_try_advisory_lock(%s)", (SUITE_LOCK_KEY,))]


def test_concurrent_session_exits_before_rebuilding_schema_or_role_password() -> None:
    conn = LockConnection(acquired=False)

    with pytest.raises(pytest.exit.Exception, match="another tests/postgres session"):
        _acquire_suite_lock(cast(psycopg.Connection, conn))
    assert len(conn.queries) == 1
