"""Invalid-session audit throttling (QA D-11, implementation plan step A1).

Unknown bearer tokens must not write audit rows; tokens of expired or revoked sessions are
audited at most once per session per window.
"""

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_session_token
from app.models.operations import AuditRecord
from app.models.session import UserSession
from app.services import audit_service

ACTION = "auth.session_invalid"


def _invalid_session_records(db: Session) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == ACTION)).all())


def _session_for(db: Session, token: str) -> UserSession:
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    assert session is not None
    return session


def test_unknown_tokens_are_rejected_without_audit_rows(client: TestClient, db: Session):
    for _ in range(25):
        headers = {"Authorization": f"Bearer {secrets.token_urlsafe(32)}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    assert _invalid_session_records(db) == []


def test_revoked_session_is_audited_once_per_window(
    client: TestClient, db: Session, customer_auth: dict
):
    session_id = str(_session_for(db, customer_auth["token"]).id)
    assert client.post("/api/v1/auth/logout", headers=customer_auth["headers"]).status_code == 200

    for _ in range(5):
        res = client.get("/api/v1/auth/me", headers=customer_auth["headers"])
        assert res.status_code == 401

    records = _invalid_session_records(db)
    assert len(records) == 1
    record = records[0]
    assert (record.entity_type, record.entity_id) == ("session", session_id)
    assert record.change_summary["reason"] == "session_revoked"
    assert record.change_summary["status"] == "failure"
    assert record.actor_user_id is None
    assert customer_auth["token"] not in str(record.change_summary)


def test_expired_session_reason_is_recorded(client: TestClient, db: Session, customer_auth: dict):
    session = _session_for(db, customer_auth["token"])
    session.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    assert client.get("/api/v1/auth/me", headers=customer_auth["headers"]).status_code == 401

    [record] = _invalid_session_records(db)
    assert record.change_summary["reason"] == "session_expired"


def test_each_stale_session_is_throttled_separately(
    client: TestClient, db: Session, customer_auth: dict, second_customer_auth: dict
):
    for auth in (customer_auth, second_customer_auth):
        assert client.post("/api/v1/auth/logout", headers=auth["headers"]).status_code == 200
    for _ in range(3):
        for auth in (customer_auth, second_customer_auth):
            assert client.get("/api/v1/auth/me", headers=auth["headers"]).status_code == 401

    assert len({r.entity_id for r in _invalid_session_records(db)}) == 2
    assert len(_invalid_session_records(db)) == 2


def test_a_new_record_is_written_after_the_window(
    client: TestClient, db: Session, customer_auth: dict, monkeypatch: pytest.MonkeyPatch
):
    # audit_records is append-only (no backdating), so shrink the window instead of waiting.
    monkeypatch.setattr(audit_service, "SESSION_INVALID_AUDIT_WINDOW_SECONDS", 0)
    assert client.post("/api/v1/auth/logout", headers=customer_auth["headers"]).status_code == 200

    for _ in range(3):
        assert client.get("/api/v1/auth/me", headers=customer_auth["headers"]).status_code == 401

    assert len(_invalid_session_records(db)) == 3
