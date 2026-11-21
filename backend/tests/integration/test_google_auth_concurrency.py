"""Continue with Google under real concurrency (ADR-006 amendment 2026-11-11).

Requests run in parallel threads through the API, each with its own database session and
connection (like separate API workers), against PostgreSQL. The gated tests prove the overlap:
the first callback holds the flow's row lock and does not commit until PostgreSQL reports a
second transaction waiting for that lock.
"""

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.rate_limit import LoginRateLimiter, get_google_auth_rate_limiter
from app.db.session import get_db
from app.integrations.oauth import get_google_oauth_client
from app.main import app
from app.models.identity import OAuthIdentity, User
from app.models.session import OAuthLoginFlow, UserSession
from app.repositories.oauth_repository import OAuthRepository
from tests.support.fake_google import FakeGoogle
from tests.support.memory_rate_limit import FakeClock, MemoryRateLimitStore

START = "/api/v1/auth/google/start"
CALLBACK = "/api/v1/auth/google/callback"


@pytest.fixture
def google(client: TestClient, pg_engine: Engine, clock: FakeClock) -> FakeGoogle:
    """The shared client, but every request gets its own session and connection."""
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)

    def own_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    fake = FakeGoogle()
    google_client = fake.client()
    settings = get_settings()
    limiter = LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="google_auth",
        max_identifier=1000,
        max_ip=1000,
        window_seconds=settings.google_auth_window_seconds,
    )
    app.dependency_overrides[get_db] = own_session
    app.dependency_overrides[get_google_oauth_client] = lambda: google_client
    app.dependency_overrides[get_google_auth_rate_limiter] = lambda: limiter
    return fake


def in_parallel(*calls: Callable[[], Any]) -> list[Any]:
    """Run the calls in threads released together; return their results in order."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)
    errors: list[BaseException] = []

    def run(i: int, call: Callable[[], Any]) -> None:
        try:
            barrier.wait(timeout=10)
            results[i] = call()
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors
    assert not any(t.is_alive() for t in threads), "a request hung"
    return results


def lock_waiters(engine: Engine) -> int:
    """Other transactions currently blocked on a lock while touching oauth_login_flows."""
    with engine.connect() as conn:
        return conn.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() AND wait_event_type = 'Lock' "
                "AND query ILIKE '%oauth_login_flows%'"
            )
        )


def gate_first_consumer(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> dict[str, bool]:
    """The first callback to lock the flow keeps its transaction open until PostgreSQL shows
    another transaction waiting for the same lock (or 10 seconds pass)."""
    original = OAuthRepository.consume_flow
    state = {"gated": False, "overlapped": False}
    guard = threading.Lock()

    def gated(db: Session, **kwargs: Any) -> OAuthLoginFlow | None:
        flow = original(db, **kwargs)
        with guard:
            first = flow is not None and not state["gated"]
            if first:
                state["gated"] = True
        if first:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if lock_waiters(engine) > 0:
                    state["overlapped"] = True
                    break
                time.sleep(0.02)
        return flow

    monkeypatch.setattr(OAuthRepository, "consume_flow", staticmethod(gated))
    return state


def counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as db:
        return {
            "users": db.scalar(select(func.count()).select_from(User)) or 0,
            "identities": db.scalar(select(func.count()).select_from(OAuthIdentity)) or 0,
            "sessions": db.scalar(select(func.count()).select_from(UserSession)) or 0,
            "consumed": db.scalar(
                select(func.count())
                .select_from(OAuthLoginFlow)
                .where(OAuthLoginFlow.consumed_at.is_not(None))
            )
            or 0,
        }


def new_flow(client: TestClient, google: FakeGoogle, code: str = "good-code") -> dict:
    flow = client.post(START).json()
    return {
        **google.authorize(flow["authorization_url"], code=code),
        "flow_token": flow["flow_token"],
    }


def test_two_overlapping_callbacks_of_one_flow_sign_in_exactly_once(
    client: TestClient, pg_engine: Engine, google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = new_flow(client, google)
    gate = gate_first_consumer(monkeypatch, pg_engine)

    first, second = in_parallel(
        lambda: client.post(CALLBACK, json=body), lambda: client.post(CALLBACK, json=body)
    )

    assert gate["overlapped"], "the second callback never waited on the first one's lock"
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 422], (first.text, second.text)
    loser = first if first.status_code == 422 else second
    assert loser.json()["error"]["code"] == "google_state_invalid"
    assert len(google.token_requests) == 1  # the loser never reached Google
    assert counts(pg_engine) == {"users": 1, "identities": 1, "sessions": 1, "consumed": 1}
    with Session(pg_engine) as db:
        reasons = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT change_summary->>'reason' FROM audit_records "
                    "WHERE action = 'auth.google'"
                )
            )
        ]
    assert reasons == ["replayed"]


def test_many_simultaneous_callbacks_of_one_flow_sign_in_exactly_once(
    client: TestClient, pg_engine: Engine, google: FakeGoogle
) -> None:
    body = new_flow(client, google)
    results = in_parallel(*[lambda: client.post(CALLBACK, json=body) for _ in range(8)])
    codes = sorted(r.status_code for r in results)
    assert codes == [200] + [422] * 7, [r.text for r in results]
    assert all(
        r.json()["error"]["code"] == "google_state_invalid" for r in results if r.status_code == 422
    )
    assert len(google.token_requests) == 1
    assert counts(pg_engine) == {"users": 1, "identities": 1, "sessions": 1, "consumed": 1}


def test_a_concurrent_wrong_flow_token_does_not_consume_the_browsers_flow(
    client: TestClient, pg_engine: Engine, google: FakeGoogle
) -> None:
    body = new_flow(client, google)
    forged = {**body, "flow_token": "attacker-has-no-cookie"}
    results = in_parallel(
        *[lambda: client.post(CALLBACK, json=forged) for _ in range(4)],
        lambda: client.post(CALLBACK, json=body),
    )
    *refused, legit = results
    assert legit.status_code == 200, legit.text
    assert all(r.status_code == 422 for r in refused)
    assert all(r.json()["error"]["code"] == "google_state_invalid" for r in refused)
    assert len(google.token_requests) == 1
    assert counts(pg_engine) == {"users": 1, "identities": 1, "sessions": 1, "consumed": 1}


def test_a_wrong_flow_token_first_still_leaves_the_flow_usable(
    client: TestClient, pg_engine: Engine, google: FakeGoogle
) -> None:
    body = new_flow(client, google)
    refused = client.post(CALLBACK, json={**body, "flow_token": "attacker-has-no-cookie"})
    assert refused.status_code == 422
    assert counts(pg_engine)["consumed"] == 0
    assert client.post(CALLBACK, json=body).status_code == 200
    assert counts(pg_engine)["consumed"] == 1


def test_simultaneous_first_sign_ins_of_one_google_account_create_one_customer(
    client: TestClient, pg_engine: Engine, google: FakeGoogle
) -> None:
    """Two browsers, two valid flows, the same new Google account, both callbacks at once: the
    unique constraints settle it. Google answers both exchanges only when both have arrived, so
    the two account creations genuinely overlap."""
    one = new_flow(client, google, code="code-1")
    two = new_flow(client, google, code="code-2")
    both_at_google = threading.Barrier(2)
    real_handler = google.handler

    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/token":
            both_at_google.wait(timeout=10)
        return real_handler(request)

    google.handler = handler  # type: ignore[method-assign]
    gated_client = google.client()  # its transport calls the gated handler
    app.dependency_overrides[get_google_oauth_client] = lambda: gated_client

    first, second = in_parallel(
        lambda: client.post(CALLBACK, json=one), lambda: client.post(CALLBACK, json=two)
    )
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert sorted([first.json()["account_created"], second.json()["account_created"]]) == [
        False,
        True,
    ]
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert counts(pg_engine) == {"users": 1, "identities": 1, "sessions": 2, "consumed": 2}
