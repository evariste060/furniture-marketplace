"""Store rules without a database (ADR-014 phase 1): every status transition pair, the event
of each decision, the request schemas, the commission rule and the store emails."""

import itertools
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.commerce import NOTIFICATION_EVENTS, STORE_STATUS_EVENTS
from app.models.marketplace import STORE_STATUSES
from app.schemas.stores import (
    StoreApplicationRequest,
    StoreCommissionRequest,
    StoreProfileUpdate,
    StoreStatusRequest,
)
from app.services import email_templates as tpl
from app.services import settings_service, store_service
from app.services.notification_service import EMAIL_SUBJECTS
from app.services.store_service import DECISION_EVENTS, STORE_TRANSITIONS, allowed_transition

ALLOWED = {
    ("pending", "approved"),
    ("pending", "rejected"),
    ("approved", "suspended"),
    ("suspended", "approved"),
}
VALID = {
    "name": "Oak House",
    "contact_email": "Sales@Example.RW",
    "contact_phone": "+250 788 123 456",
    "district": "Kicukiro",
}


@pytest.mark.parametrize(
    ("current", "requested"), list(itertools.product(STORE_STATUSES, STORE_STATUSES))
)
def test_every_administrator_transition_pair(current: str, requested: str):
    assert allowed_transition(current, requested) is ((current, requested) in ALLOWED)


def test_the_map_covers_every_status_and_each_decision_has_one_event():
    assert set(STORE_TRANSITIONS) == set(STORE_STATUSES)
    assert set(DECISION_EVENTS) == ALLOWED
    assert sorted(DECISION_EVENTS.values()) == sorted(
        set(STORE_STATUS_EVENTS) - {"store_application_received"}
    )
    assert not allowed_transition("unknown", "approved")


def test_store_events_are_outbox_events_about_a_store_status_subject():
    assert set(STORE_STATUS_EVENTS) <= set(NOTIFICATION_EVENTS)
    assert all(EMAIL_SUBJECTS[event] == "store_status" for event in STORE_STATUS_EVENTS)
    assert all(len(event) <= 32 for event in NOTIFICATION_EVENTS)  # notification_logs.event


def test_an_application_is_normalised():
    req = StoreApplicationRequest(**VALID)
    assert req.contact_email == "sales@example.rw"
    assert req.contact_phone == "+250788123456"
    assert req.description is None and req.sector is None


@pytest.mark.parametrize(
    "extra", ["owner_user_id", "status", "slug", "commission_rate_bps", "approved_at"]
)
def test_an_application_refuses_fields_the_seller_does_not_own(extra: str):
    with pytest.raises(ValidationError):
        StoreApplicationRequest(**VALID, **{extra: "x"})


def test_profile_updates_are_partial_and_required_fields_cannot_be_cleared():
    assert StoreProfileUpdate(description=None).model_fields_set == {"description"}
    with pytest.raises(ValidationError):
        StoreProfileUpdate()
    for field in ("name", "contact_email", "contact_phone", "district"):
        with pytest.raises(ValidationError):
            StoreProfileUpdate(**{field: None})


@pytest.mark.parametrize(
    ("body", "ok"),
    [
        ({"status": "approved"}, True),
        ({"status": "approved", "reason": "All documents checked."}, True),
        ({"status": "rejected", "reason": "Missing the shop address."}, True),
        ({"status": "rejected"}, False),
        ({"status": "suspended", "reason": "   "}, False),
        ({"status": "suspended", "reason": "short"}, False),
        ({"status": "suspended", "reason": "r" * 501}, False),
        ({"status": "pending"}, False),
    ],
)
def test_decisions_need_a_reason_to_reject_or_suspend(body: dict, ok: bool):
    if ok:
        StoreStatusRequest(**body)
    else:
        with pytest.raises(ValidationError):
            StoreStatusRequest(**body)


@pytest.mark.parametrize("value", [0, 1, 1000, 10_000, None])
def test_commission_accepts_whole_basis_points_or_null(value):
    assert StoreCommissionRequest(commission_rate_bps=value).commission_rate_bps == value


@pytest.mark.parametrize("value", [-1, 10_001, 10.5, "100", True])
def test_commission_refuses_anything_else(value):
    with pytest.raises(ValidationError):
        StoreCommissionRequest(commission_rate_bps=value)


def test_the_effective_commission_is_the_override_else_the_platform_default(monkeypatch):
    monkeypatch.setattr(store_service, "default_commission_bps", lambda db: 1250)
    assert (
        store_service.effective_commission_bps(None, SimpleNamespace(commission_rate_bps=None))
        == 1250
    )  # type: ignore[arg-type]
    assert store_service.effective_commission_bps(None, SimpleNamespace(commission_rate_bps=0)) == 0  # type: ignore[arg-type]
    assert (
        store_service.effective_commission_bps(None, SimpleNamespace(commission_rate_bps=700))
        == 700
    )  # type: ignore[arg-type]


def test_the_platform_default_is_10_percent_while_unset_or_invalid(monkeypatch):
    monkeypatch.setattr(settings_service, "get_value", lambda db, key: None)
    assert settings_service.default_commission_bps(None) == 1000  # type: ignore[arg-type]
    monkeypatch.setattr(settings_service, "get_value", lambda db, key: 450)
    assert settings_service.default_commission_bps(None) == 450  # type: ignore[arg-type]
    rule = settings_service.SETTINGS["marketplace.default_commission_bps"]
    assert [rule.valid(v) for v in (0, 10_000, -1, 10_001, 12.5, True, "1000")] == [
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]


@pytest.mark.parametrize("event", STORE_STATUS_EVENTS)
def test_every_store_email_names_the_store_and_escapes_it(event: str):
    rendered = tpl.store_status(event, "Aline", "<Oak & Co>", "Reason <b>here</b>.", None)
    assert "<Oak & Co>" in rendered.subject
    assert "&lt;Oak &amp; Co&gt;" in rendered.html and "<b>here" not in rendered.html
    shows_reason = event in ("store_rejected", "store_suspended")
    assert ("Reason <b>here</b>." in rendered.text) is shows_reason


def test_a_store_email_without_a_site_url_has_no_link():
    rendered = tpl.store_status("store_approved", "Aline", "Oak", None, None)
    assert "http" not in rendered.text
