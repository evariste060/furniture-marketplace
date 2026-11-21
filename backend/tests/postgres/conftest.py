"""PostgreSQL + Redis + real HTTP test harness.

Enabled only when TEST_DATABASE_URL is set. The database name must end in "_test"; it is
dropped and rebuilt (schema public) at session start, so never point it at real data.

    TEST_DATABASE_URL=postgresql+psycopg://owner:pw@127.0.0.1:55432/rwanda_ecommerce_test
    TEST_REDIS_URL=redis://127.0.0.1:6379/15        (database is flushed between tests)
    pytest tests/postgres

The API runs as two separate uvicorn processes (simulating multiple workers/instances) using a
least-privilege runtime role created by scripts/provision_runtime_role.py, while assertions
query PostgreSQL directly as the owner/migration role.

Only one tests/postgres session may use a database at a time: each session rebuilds schema
public and sets a new password on the cluster-wide runtime role, which breaks an overlapping
session's new connections. A session-level advisory lock (SUITE_LOCK_KEY) makes a second session
exit at startup. Advisory locks are per database, so sessions on two different *_test databases
in one cluster are not detected and still share the runtime role.
"""

import os
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest
import redis

from tests.support.client_ip import SECRET as CLIENT_IP_SECRET
from tests.support.credentials import random_password

TEST_DATABASE_URL: str | None = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    collect_ignore_glob = ["test_*.py"]

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
RUNTIME_ROLE = "rwanda_app_test"
LOGIN_WINDOW = 10  # short window so the reset test runs quickly; thresholds stay 5 / 20
HMAC_KEY = "pg-suite-only-audit-hmac-key-0123456789abcdef"
MOCK_PAYMENT_SECRET = "pg-suite-only-mock-payment-secret-0123456789"  # module 15
SUITE_LOCK_KEY = 7_316_402_119_865_120_001  # arbitrary constant bigint for pg_try_advisory_lock


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _with_credentials(url: str, user: str, password: str) -> str:
    parts = urlsplit(url)
    netloc = f"{user}:{password}@{parts.hostname}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Stack:
    servers: list[str]
    owner_url: str = field(repr=False)
    runtime_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    media_root: Path | None = None  # MEDIA_ROOT shared by the API processes (module 7)
    server_env: dict[str, str] = field(default_factory=dict, repr=False)
    logs: list[Path] = field(default_factory=list, repr=False)

    def verification_token(self, email: str, timeout: float = 10.0) -> str:
        """The newest verification link sent to `email`, read from the API processes' console
        mail output (NOTIFICATION_PROVIDER=console; the link is sent after the response)."""
        marker = f"email to {email}:"
        deadline = time.monotonic() + timeout
        while True:
            for log_path in self.logs:
                text = _read_log(log_path)
                at = text.rfind(marker)
                if at >= 0:
                    found = re.search(r"#token=([A-Za-z0-9_-]+)", text[at:])
                    if found:
                        return found.group(1)
            if time.monotonic() > deadline:
                raise AssertionError(f"no verification email for {email}")
            time.sleep(0.05)

    def owner(self) -> psycopg.Connection:
        return psycopg.connect(_plain(self.owner_url), autocommit=True)

    def runtime(self) -> psycopg.Connection:
        return psycopg.connect(_plain(self.runtime_url), autocommit=True)

    def run_worker_once(self) -> None:
        """One pass of the background worker (python -m app.worker --once), as the API's
        runtime role with the API's MEDIA_ROOT."""
        _run([sys.executable, "-m", "app.worker", "--once"], self.server_env)


def _run(cmd: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd} failed:\n{result.stdout}\n{result.stderr}")


def _redact_startup_output(output: str, sensitive_values: tuple[str, ...]) -> str:
    for value in sensitive_values:
        if value:
            output = output.replace(value, "<redacted>")
    return output[-4000:].strip()


def _start_server(cmd: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen[bytes]:
    """Start a server whose output goes to a file.

    Never a pipe: nothing reads it after startup, so once tracebacks fill the pipe buffer the
    server blocks on its next log write and every later request times out.
    """
    with log_path.open("wb") as log:
        return subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)


def _read_log(log_path: Path) -> str:
    return log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""


def _stop_server(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _wait_for_server(
    proc: subprocess.Popen[bytes], base: str, log_path: Path, sensitive_values: tuple[str, ...]
) -> None:
    for _ in range(60):
        exit_code = proc.poll()
        if exit_code is not None:
            diagnostic = _redact_startup_output(_read_log(log_path), sensitive_values)
            detail = f"server {base} exited before readiness (exit code {exit_code})"
            if diagnostic:
                detail += f"\n{diagnostic}"
            raise RuntimeError(detail)
        try:
            if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.25)

    _stop_server(proc)
    output = _redact_startup_output(_read_log(log_path), sensitive_values)
    detail = f"server {base} did not become ready after 60 attempts"
    if output:
        detail += f"\n{output}"
    raise RuntimeError(detail)


def _acquire_suite_lock(conn: psycopg.Connection) -> None:
    """Hold the suite lock until conn closes, or exit if another session already holds it."""
    row = conn.execute("SELECT pg_try_advisory_lock(%s)", (SUITE_LOCK_KEY,)).fetchone()
    if not (row and row[0]):
        pytest.exit(
            "Refusing to run: another tests/postgres session is using this database "
            "(it rebuilds schema public and resets the runtime role password)"
        )


@pytest.fixture(scope="session")
def suite_owner_url() -> Iterator[str]:
    """The validated owner URL, with the suite lock held for the whole session."""
    owner_url = TEST_DATABASE_URL
    if owner_url is None:
        pytest.exit("TEST_DATABASE_URL must point to a dedicated *_test database")
    dbname = urlsplit(owner_url).path.lstrip("/")
    if not dbname.endswith("_test"):
        pytest.exit(f"Refusing to run: TEST_DATABASE_URL database '{dbname}' must end in _test")
    with psycopg.connect(_plain(owner_url), autocommit=True) as lock_conn:
        _acquire_suite_lock(lock_conn)
        yield owner_url


@pytest.fixture(scope="session")
def stack(suite_owner_url: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    owner_url = suite_owner_url
    redis_url = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")

    base_env = {
        **os.environ,
        "DATABASE_URL": owner_url,
        "AUDIT_HMAC_KEY": HMAC_KEY,
        "REDIS_URL": redis_url,
    }
    # Empty = unset: Alembic must use owner_url, never a MIGRATION_DATABASE_URL from backend/.env.
    base_env["MIGRATION_DATABASE_URL"] = ""
    py = sys.executable
    # Rebuild public from scratch (independent of whatever revision a previous run left).
    with psycopg.connect(_plain(owner_url), autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
    _run([py, "-m", "alembic", "upgrade", "head"], base_env)

    runtime_password = secrets.token_urlsafe(24)
    _run(
        [py, str(REPO / "scripts" / "provision_runtime_role.py")],
        {
            **base_env,
            "MIGRATION_DATABASE_URL": owner_url,
            "RUNTIME_DB_ROLE": RUNTIME_ROLE,
            "RUNTIME_DB_PASSWORD": runtime_password,
        },
    )
    runtime_url = _with_credentials(owner_url, RUNTIME_ROLE, runtime_password)

    media_root = tmp_path_factory.mktemp("media")
    server_env = {
        **base_env,
        "DATABASE_URL": runtime_url,
        "MEDIA_ROOT": str(media_root),  # uploaded images stay out of backend/media
        "LOGIN_WINDOW_SECONDS": str(LOGIN_WINDOW),
        "APP_ENV": "development",
        "PAYMENT_MOCK_WEBHOOK_SECRET": MOCK_PAYMENT_SECRET,
        # Password reset and email verification need a sender; console output goes to the
        # server logs only (Stack.verification_token reads the links from there).
        "NOTIFICATION_PROVIDER": "console",
        "SITE_URL": "http://localhost:3000",
        # Client IP as in production (ADR-006, 2026-11-13): only a signed address is trusted.
        "CLIENT_IP_SOURCE": "signed",
        "CLIENT_IP_SIGNING_SECRET": CLIENT_IP_SECRET,
    }
    log_dir = tmp_path_factory.mktemp("uvicorn")
    procs, servers, logs = [], [], []
    for i in range(2):
        port = _free_port()
        logs.append(log_dir / f"server{i}.log")
        procs.append(
            _start_server(
                [
                    py,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                    # As in production: no X-Forwarded-For is trusted, from anywhere.
                    "--no-proxy-headers",
                ],
                server_env,
                logs[-1],
            )
        )
        servers.append(f"http://127.0.0.1:{port}/api/v1")
    try:
        sensitive_values = (owner_url, runtime_url, redis_url)
        for proc, base, log_path in zip(procs, servers, logs, strict=True):
            _wait_for_server(proc, base, log_path, sensitive_values)
        yield Stack(servers, owner_url, runtime_url, redis_url, media_root, server_env, logs)
    finally:
        for proc in procs:
            _stop_server(proc)


@pytest.fixture(autouse=True)
def clean_rate_limits(stack: Stack) -> None:
    redis.Redis.from_url(stack.redis_url).flushdb()


@pytest.fixture
def unique() -> str:
    return secrets.token_hex(4)


@pytest.fixture
def phone_factory():
    used: set[str] = set()

    def make() -> str:
        while True:
            number = f"+2507{secrets.randbelow(10**8):08d}"
            if number not in used:
                used.add(number)
                return number

    return make


@pytest.fixture
def failing_audit(stack: Stack):
    """Make audit inserts fail for one actor email, via a temporary owner-level trigger."""
    created: list[str] = []

    def arm(email: str) -> None:
        name = f"fail_audit_{uuid.uuid4().hex[:8]}"
        with stack.owner() as conn:
            conn.execute(
                f"""
                CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF NEW.actor_identifier_snapshot = '{email}' THEN
                    RAISE EXCEPTION 'simulated audit failure';
                  END IF;
                  RETURN NEW;
                END $$;
                CREATE TRIGGER {name} BEFORE INSERT ON audit_records
                FOR EACH ROW EXECUTE FUNCTION {name}();
                """
            )
        created.append(name)

    yield arm
    with stack.owner() as conn:
        for name in created:
            conn.execute(f"DROP TRIGGER IF EXISTS {name} ON audit_records")
            conn.execute(f"DROP FUNCTION IF EXISTS {name}()")


# ---- shared administrator (created once per run by the operator CLI) ----------------------
ADMIN_EMAIL = "bootstrap.admin@pg.test"
ADMIN_PASSWORD = random_password()  # per run; never a fixed credential


def bootstrap_cli(
    stack: Stack, password: str, *args: str, owner: str | None = None
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": stack.runtime_url,
        "MIGRATION_DATABASE_URL": stack.owner_url if owner is None else owner,
        "AUDIT_HMAC_KEY": HMAC_KEY,
        "REDIS_URL": stack.redis_url,
    }
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "bootstrap_admin.py"), "--password-stdin", *args],
        cwd=BACKEND,
        env=env,
        input=password + "\n",
        capture_output=True,
        text=True,
    )


def login(base: str, identifier: str, password: str) -> dict:
    res = httpx.post(f"{base}/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['session_token']}"}


@pytest.fixture(scope="session")
def admin(stack: Stack) -> dict:
    """The first administrator, created by the operator CLI exactly as in deployment."""
    result = bootstrap_cli(stack, ADMIN_PASSWORD, "--email", ADMIN_EMAIL, "--full-name", "Boot A")
    assert result.returncode == 0, result.stderr
    assert ADMIN_PASSWORD not in result.stdout + result.stderr
    return login(stack.servers[0], ADMIN_EMAIL, ADMIN_PASSWORD)
