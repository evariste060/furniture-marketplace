"""Module 12 — delivery zones, fees, the free-delivery threshold and cart delivery quotes
(RE-026 B1, B5, B6; TC-17). Runs on the disposable per-test PostgreSQL schema (tests/conftest.py).

Values below are test data, not the development placeholders of scripts/seed_dev.py.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.request_context import RequestContext
from app.main import app
from app.models import DeliveryFeeRule, DeliveryZone, InventoryBalance, Setting
from app.models.identity import User
from app.models.operations import AuditRecord
from app.repositories import delivery_repository as repo
from app.repositories.audit_repository import AuditRepository
from app.schemas.delivery import DeliveryZoneUpdateRequest
from app.services import delivery_service
from app.services.delivery_service import (
    DeliveryQuoteUnavailable,
    DeliveryService,
    DeliveryZoneUnavailable,
    quote_for_district,
    quote_for_zone,
)
from tests.integration.test_cart_api import add, code, sku

PUBLIC = "/api/v1/delivery/zones"
ZONES = "/api/v1/staff/delivery/zones"
SETTINGS = "/api/v1/staff/settings"
CART = "/api/v1/cart"
THRESHOLD = "delivery.free_delivery_threshold"
REGISTERED = sorted(  # module 16 added the seller details, module 19 the store contact,
    # the owner the social links (2026-11-18)
    [
        "social.facebook",
        "social.instagram",
        "social.x",
        "social.youtube",
        "social.tiktok",
        "social.linkedin",
        THRESHOLD,
        "seller.address",
        "seller.legal_name",
        "seller.tin",
        "store.name",
        "contact.phone",
        "contact.whatsapp",
        "contact.email",
        "contact.address",
        "contact.hours",
        "announcement.enabled",
        "announcement.text_en",
        "announcement.text_rw",
    ]
)


def create_zone(client: TestClient, headers: dict, district: str, fee: int, **fields) -> dict:
    body = {"code": district.lower(), "name": district, "district": district, "fee": fee, **fields}
    res = client.post(ZONES, json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def set_threshold(client: TestClient, headers: dict, value: int) -> None:
    res = client.patch(SETTINGS, json={THRESHOLD: value}, headers=headers)
    assert res.status_code == 200, res.text


def rules(db: Session, zone_id) -> list[DeliveryFeeRule]:
    db.expire_all()
    return list(
        db.scalars(
            select(DeliveryFeeRule)
            .where(DeliveryFeeRule.zone_id == uuid.UUID(str(zone_id)))
            .order_by(DeliveryFeeRule.starts_at.nulls_first(), DeliveryFeeRule.created_at)
        )
    )


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


@pytest.fixture
def configured(client, admin_auth) -> dict:
    """Three zones and a 200 000 threshold, created through the staff API."""
    h = admin_auth["headers"]
    zones = {
        "Nyarugenge": create_zone(client, h, "Nyarugenge", 1500, sort_order=1),
        "Kicukiro": create_zone(client, h, "Kicukiro", 2000, sort_order=2),
        "Gasabo": create_zone(client, h, "Gasabo", 2000, sort_order=3),
    }
    set_threshold(client, h, 200_000)
    return zones


# ---- public list ---------------------------------------------------------------------------
def test_public_list_is_empty_and_threshold_null_until_configured(client):
    res = client.get(PUBLIC)
    assert res.status_code == 200
    assert res.json() == {"items": [], "free_delivery_threshold": None, "currency_code": "RWF"}


def test_public_list_shows_active_zones_in_order_with_fee_cod_and_threshold(
    client, admin_auth, configured
):
    client.patch(
        f"{ZONES}/{configured['Kicukiro']['id']}",
        json={"cod_available": False},
        headers=admin_auth["headers"],
    )
    body = client.get(PUBLIC).json()
    assert body["free_delivery_threshold"] == 200_000
    assert body["items"] == [
        {
            "code": "nyarugenge",
            "name": "Nyarugenge",
            "district": "Nyarugenge",
            "fee": 1500,
            "cod_available": True,
        },
        {
            "code": "kicukiro",
            "name": "Kicukiro",
            "district": "Kicukiro",
            "fee": 2000,
            "cod_available": False,
        },
        {
            "code": "gasabo",
            "name": "Gasabo",
            "district": "Gasabo",
            "fee": 2000,
            "cod_available": True,
        },
    ]
    assert "id" not in body["items"][0] and "fee_history" not in body["items"][0]


def test_public_list_excludes_inactive_zones_and_zones_without_a_current_fee(
    client, db, admin_auth, configured
):
    client.patch(
        f"{ZONES}/{configured['Gasabo']['id']}",
        json={"is_active": False},
        headers=admin_auth["headers"],
    )
    # A zone whose only rule has been closed has no current fee (inserted directly: the API
    # never leaves an active zone without one).
    rule = db.scalar(
        select(DeliveryFeeRule).where(
            DeliveryFeeRule.zone_id == uuid.UUID(configured["Kicukiro"]["id"])
        )
    )
    rule.is_active = False
    db.commit()
    assert [z["code"] for z in client.get(PUBLIC).json()["items"]] == ["nyarugenge"]


# ---- permissions (B6) ----------------------------------------------------------------------
def test_management_can_view_but_not_change_delivery_or_settings(
    client, admin_auth, management_auth, configured
):
    h = management_auth["headers"]
    zone_id = configured["Gasabo"]["id"]
    assert client.get(ZONES, headers=h).status_code == 200
    assert client.get(SETTINGS, headers=h).status_code == 200
    body = {"code": "x", "name": "X", "district": "Gasabo", "fee": 1}
    assert client.post(ZONES, json=body, headers=h).status_code == 403
    assert client.patch(f"{ZONES}/{zone_id}", json={"fee": 1}, headers=h).status_code == 403
    assert client.patch(SETTINGS, json={THRESHOLD: 1}, headers=h).status_code == 403
    assert client.get(PUBLIC).json()["items"][2]["fee"] == 2000  # unchanged
    assert client.get(PUBLIC).json()["free_delivery_threshold"] == 200_000


@pytest.mark.parametrize(
    ("who", "zones_read"),
    # Operations views delivery zones (delivery:read, final matrix 2026-10-26), nothing else.
    [("sales_auth", 403), ("operations_auth", 200), ("customer_auth", 403), (None, 401)],
)
def test_other_roles_and_anonymous_callers_are_refused(
    client, request, admin_auth, who, zones_read
):
    zone = create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    headers = request.getfixturevalue(who)["headers"] if who else {}
    expected = 403 if who else 401
    body = {"code": "x", "name": "X", "district": "Kicukiro", "fee": 1}
    calls = [
        client.get(ZONES, headers=headers),
        client.post(ZONES, json=body, headers=headers),
        client.patch(f"{ZONES}/{zone['id']}", json={"fee": 1}, headers=headers),
        client.get(SETTINGS, headers=headers),
        client.patch(SETTINGS, json={THRESHOLD: 1}, headers=headers),
    ]
    assert [r.status_code for r in calls] == [zones_read] + [expected] * 4
    assert client.get(PUBLIC, headers=headers).status_code == 200  # public for everyone


def test_administrator_has_every_delivery_and_settings_permission(client, admin_auth):
    res = client.get("/api/v1/staff/me", headers=admin_auth["headers"])
    assert res.status_code == 200, res.text
    assert {"delivery:read", "delivery:manage", "settings:read", "settings:manage"} <= set(
        res.json()["permissions"]
    )


# ---- zone creation and validation ----------------------------------------------------------
def test_create_returns_the_zone_with_its_first_fee_rule_and_is_audited(client, db, admin_auth):
    zone = create_zone(client, admin_auth["headers"], "Kicukiro", 2000, cod_available=False)
    assert zone["district"] == "Kicukiro" and zone["fee"] == 2000
    assert zone["cod_available"] is False and zone["is_active"] is True
    assert zone["sort_order"] == 0
    [rule] = zone["fee_history"]
    assert rule["fee"] == 2000 and rule["is_active"] is True and rule["ends_at"] is None
    assert rule["currency_code"] == "RWF" and rule["starts_at"] is not None
    [record] = audits(db, "delivery.zone_create")
    assert record.entity_id == zone["id"]
    assert record.change_summary["fee"] == 2000 and record.change_summary["district"] == "Kicukiro"


@pytest.mark.parametrize(
    "change",
    [
        {"district": "Musanze"},
        {"district": "gasabo"},
        {"district": None},
        {"code": "Has Spaces"},
        {"code": ""},
        {"code": "x" * 61},
        {"name": "   "},
        {"fee": -1},
        {"fee": 1_000_000_000_000},
        {"fee": "2000"},
        {"fee": 2000.5},
        {"fee": True},
        {"sort_order": 2**31},
        {"coverage": {"sectors": ["Remera"]}},
        {"fee_history": []},
        {"id": str(uuid.uuid4())},
    ],
)
def test_create_rejects_invalid_input(client, db, admin_auth, change):
    body = {"code": "gasabo", "name": "Gasabo", "district": "Gasabo", "fee": 2000, **change}
    res = client.post(ZONES, json=body, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text
    assert db.scalar(select(DeliveryZone.id)) is None


def test_create_requires_a_fee(client, admin_auth):
    body = {"code": "gasabo", "name": "Gasabo", "district": "Gasabo"}
    assert client.post(ZONES, json=body, headers=admin_auth["headers"]).status_code == 422


def test_duplicate_code_or_district_is_409(client, db, admin_auth):
    h = admin_auth["headers"]
    create_zone(client, h, "Gasabo", 2000)
    same_code = {"code": "gasabo", "name": "Other", "district": "Kicukiro", "fee": 1}
    res = client.post(ZONES, json=same_code, headers=h)
    assert res.status_code == 409 and code(res) == "zone_code_taken"
    same_district = {"code": "gasabo-2", "name": "Other", "district": "Gasabo", "fee": 1}
    res = client.post(ZONES, json=same_district, headers=h)
    assert res.status_code == 409 and code(res) == "zone_district_taken"
    assert len(list(db.scalars(select(DeliveryZone)))) == 1


def test_database_backstops_reject_bad_rows(db: Session):
    zone = DeliveryZone(code="z", name="Z", district="Gasabo")
    db.add(zone)
    db.commit()
    db.add(DeliveryZone(code="z2", name="Z2", district="Rubavu"))
    with pytest.raises(IntegrityError, match="supported_district"):
        db.commit()
    db.rollback()
    db.add(DeliveryZone(code="z3", name="Z3", district="Gasabo"))
    with pytest.raises(IntegrityError, match="delivery_zone_district"):
        db.commit()
    db.rollback()
    db.add(DeliveryFeeRule(zone_id=zone.id, fee=1))
    db.commit()
    db.add(DeliveryFeeRule(zone_id=zone.id, fee=2))  # a second active rule for the zone
    with pytest.raises(IntegrityError, match="uq_delivery_fee_rules_one_active_per_zone"):
        db.commit()
    db.rollback()
    db.add(DeliveryFeeRule(zone_id=zone.id, fee=2, is_active=False))  # closed rules are fine
    db.commit()
    db.add(Setting(key="NotDotted", value=1))
    with pytest.raises(IntegrityError, match="key_format"):
        db.commit()


# ---- zone updates and fee history ----------------------------------------------------------
def test_fee_changes_close_the_old_rule_and_keep_the_history(client, db, admin_auth):
    h = admin_auth["headers"]
    zone = create_zone(client, h, "Nyarugenge", 1500)
    url = f"{ZONES}/{zone['id']}"

    first = client.patch(url, json={"fee": 1800}, headers=h)
    assert first.status_code == 200, first.text
    same = client.patch(url, json={"fee": 1800}, headers=h)  # the current fee: no new rule
    assert same.status_code == 200
    last = client.patch(url, json={"fee": 1600}, headers=h).json()

    history = rules(db, zone["id"])
    assert [r.fee for r in history] == [1500, 1800, 1600]
    assert [r.is_active for r in history] == [False, False, True]
    assert all(r.ends_at is not None for r in history[:2]) and history[2].ends_at is None
    assert history[0].ends_at <= history[1].starts_at  # no gap or overlap between rules
    assert history[1].ends_at <= history[2].starts_at
    assert last["fee"] == 1600
    assert [r["fee"] for r in last["fee_history"]] == [1600, 1800, 1500]  # newest first
    records = audits(db, "delivery.zone_update")
    assert len(records) == 2  # the no-op was not audited
    assert records[0].change_summary["changes"]["fee"]["from"] in (1500, 1800)
    assert client.get(PUBLIC).json()["items"][0]["fee"] == 1600


def test_update_changes_only_the_fields_sent(client, db, admin_auth):
    h = admin_auth["headers"]
    zone = create_zone(client, h, "Gasabo", 2000)
    res = client.patch(
        f"{ZONES}/{zone['id']}",
        json={"name": "Gasabo district", "sort_order": 9, "cod_available": False},
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["name"], body["sort_order"], body["cod_available"]) == (
        "Gasabo district",
        9,
        False,
    )
    assert body["code"] == "gasabo" and body["district"] == "Gasabo" and body["fee"] == 2000
    assert len(rules(db, zone["id"])) == 1  # no fee sent: no new rule
    [record] = audits(db, "delivery.zone_update")
    assert set(record.change_summary["changes"]) == {"name", "sort_order", "cod_available"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"code": "new-code"},
        {"district": "Kicukiro"},
        {"fee": None},
        {"name": None},
        {"is_active": None},
        {"fee": -5},
        {"fee": "100"},
        {"currency_code": "USD"},
    ],
)
def test_update_rejects_invalid_or_immutable_fields(client, db, admin_auth, body):
    zone = create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    res = client.patch(f"{ZONES}/{zone['id']}", json=body, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text
    assert [r.fee for r in rules(db, zone["id"])] == [2000]


def test_update_of_an_unknown_or_malformed_zone_id(client, admin_auth):
    h = admin_auth["headers"]
    res = client.patch(f"{ZONES}/{uuid.uuid4()}", json={"fee": 1}, headers=h)
    assert res.status_code == 404 and code(res) == "delivery_zone_not_found"
    assert client.patch(f"{ZONES}/not-a-uuid", json={"fee": 1}, headers=h).status_code == 422


def test_an_active_zone_needs_a_fee(client, db, admin_auth):
    zone = DeliveryZone(code="legacy", name="Legacy", district="Gasabo", is_active=False)
    db.add(zone)
    db.commit()
    url = f"{ZONES}/{zone.id}"
    res = client.patch(url, json={"is_active": True}, headers=admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "zone_fee_missing"
    res = client.patch(url, json={"is_active": True, "fee": 900}, headers=admin_auth["headers"])
    assert res.status_code == 200 and res.json()["fee"] == 900


def test_a_failed_audit_rolls_back_the_whole_fee_change(client, db, admin_auth, monkeypatch):
    zone = create_zone(client, admin_auth["headers"], "Kicukiro", 2000)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    with pytest.raises(RuntimeError, match="simulated"):
        client.patch(f"{ZONES}/{zone['id']}", json={"fee": 2500}, headers=admin_auth["headers"])
    history = rules(db, zone["id"])
    assert [(r.fee, r.is_active, r.ends_at) for r in history] == [(2000, True, None)]


def test_a_failed_new_rule_rolls_back_the_closing_of_the_old_one(
    client, db, admin_auth, monkeypatch
):
    zone = create_zone(client, admin_auth["headers"], "Kicukiro", 2000)

    def fail(db, zone_id, fee, starts_at):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(delivery_service, "_new_rule", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        client.patch(f"{ZONES}/{zone['id']}", json={"fee": 2500}, headers=admin_auth["headers"])
    assert [(r.fee, r.is_active) for r in rules(db, zone["id"])] == [(2000, True)]


def _valid_history(history: list[DeliveryFeeRule]) -> None:
    """One active rule, the last; every closed rule ends where its successor starts."""
    assert [r.is_active for r in history] == [False] * (len(history) - 1) + [True]
    assert history[-1].ends_at is None
    for older, newer in zip(history, history[1:], strict=False):
        assert older.starts_at is not None and older.ends_at is not None
        assert older.starts_at < older.ends_at == newer.starts_at


def test_a_fee_change_whose_transaction_started_first_but_locked_last_keeps_valid_history(
    pg_engine, db, client, admin_auth
):
    """The review's interleaving, made deterministic with two sessions: A's transaction starts
    first (as after authentication), B then takes the zone lock and commits a new fee, and only
    then does A change the fee. With now() A would end B's rule before it began (500); the
    timestamp read after the lock keeps the history valid and both changes succeed."""
    assert pg_engine.url.database == "rwanda_ecommerce_test"
    zone = create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    ctx = RequestContext(ip_address="127.0.0.1", user_agent="test")
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    a, b = make(), make()
    try:
        actor_a = a.get(User, admin_auth["user"].id)  # opens A's transaction: now() is fixed
        a.execute(text("SELECT pg_sleep(0.01)"))  # B's transaction starts strictly later
        actor_b = b.get(User, admin_auth["user"].id)
        zone_id = uuid.UUID(zone["id"])
        DeliveryService.update_zone(b, actor_b, zone_id, DeliveryZoneUpdateRequest(fee=2100), ctx)
        result = DeliveryService.update_zone(
            a, actor_a, zone_id, DeliveryZoneUpdateRequest(fee=2200), ctx
        )
        assert result.fee == 2200
    finally:
        for session in (a, b):
            session.rollback()
            session.close()
    history = rules(db, zone["id"])
    assert [r.fee for r in history] == [2000, 2100, 2200]
    _valid_history(history)
    assert len(audits(db, "delivery.zone_update")) == 2
    staff = client.get(ZONES, headers=admin_auth["headers"]).json()["items"][0]
    assert [r["fee"] for r in staff["fee_history"]] == [2200, 2100, 2000]  # newest first
    assert staff["fee"] == 2200


def test_a_read_whose_transaction_began_before_a_fee_change_sees_the_new_fee(
    pg_engine, client, admin_auth
):
    """Current-fee reads (delivery_repository.current_fees) under READ COMMITTED: A's
    transaction begins, B changes the fee and commits, then A reads. A's statement sees B's rule,
    whose starts_at (taken after B's lock) is later than A's transaction-start now(), so a
    now()-based window would find no current fee at all; statement_timestamp() finds the new one."""
    assert pg_engine.url.database == "rwanda_ecommerce_test"
    zone = create_zone(client, admin_auth["headers"], "Nyarugenge", 1500)
    zone_id = uuid.UUID(zone["id"])
    ctx = RequestContext(ip_address="127.0.0.1", user_agent="test")
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    a, b = make(), make()
    try:
        a.execute(text("SELECT pg_sleep(0.01)"))  # 1. A's transaction begins: its now() is fixed
        actor_b = b.get(User, admin_auth["user"].id)
        # 2. B changes the active fee and commits (update_zone commits through atomic).
        DeliveryService.update_zone(b, actor_b, zone_id, DeliveryZoneUpdateRequest(fee=1700), ctx)
        # 3. A, still in its first transaction, reads after B's commit.
        assert repo.current_fees(a, [zone_id]) == {zone_id: 1700}
        # The interleaving really happened: a transaction-start window sees no current fee.
        now = func.now()
        by_transaction_start = a.execute(
            select(DeliveryFeeRule.fee).where(
                DeliveryFeeRule.zone_id == zone_id,
                DeliveryFeeRule.is_active.is_(True),
                or_(DeliveryFeeRule.starts_at.is_(None), DeliveryFeeRule.starts_at <= now),
                or_(DeliveryFeeRule.ends_at.is_(None), DeliveryFeeRule.ends_at > now),
            )
        ).all()
        assert by_transaction_start == []
        # The quote and the public list use the same read.
        set_threshold(client, admin_auth["headers"], 200_000)
        assert quote_for_zone(a, "nyarugenge", 1000).zone_fee == 1700
    finally:
        for session in (a, b):
            session.rollback()
            session.close()


def test_an_active_rule_that_has_not_started_yet_is_a_409_not_a_500(client, db, admin_auth):
    """A rule dated in the future (legacy data or clock skew) cannot be closed with a valid
    window: the change is refused with the documented conflict and nothing is written."""
    zone = create_zone(client, admin_auth["headers"], "Kicukiro", 2000)
    db.execute(
        text(
            "UPDATE delivery_fee_rules SET starts_at = clock_timestamp() + interval '1 hour' "
            "WHERE zone_id = :zone"
        ),
        {"zone": zone["id"]},
    )
    db.commit()
    res = client.patch(f"{ZONES}/{zone['id']}", json={"fee": 2500}, headers=admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "fee_change_conflict"
    assert [(r.fee, r.is_active, r.ends_at) for r in rules(db, zone["id"])] == [(2000, True, None)]
    assert audits(db, "delivery.zone_update") == []


def test_only_fee_rule_constraints_become_409_and_other_integrity_errors_propagate():
    def integrity_error(constraint: str) -> IntegrityError:
        class Diag:
            constraint_name = constraint

        class Orig(Exception):
            diag = Diag()

        return IntegrityError("statement", {}, Orig())

    for constraint in (
        "ck_delivery_fee_rules_valid_window",
        "uq_delivery_fee_rules_one_active_per_zone",
    ):
        mapped = delivery_service._integrity_conflict(integrity_error(constraint))
        assert (mapped.status_code, mapped.code) == (409, "fee_change_conflict")
    unrelated = integrity_error("fk_delivery_fee_rules_zone_id_delivery_zones")
    with pytest.raises(IntegrityError):
        delivery_service._integrity_conflict(unrelated)


def test_staff_list_includes_inactive_zones_with_history(client, admin_auth, management_auth):
    h = admin_auth["headers"]
    zone = create_zone(client, h, "Gasabo", 2000)
    client.patch(f"{ZONES}/{zone['id']}", json={"fee": 2200, "is_active": False}, headers=h)
    [item] = client.get(ZONES, headers=management_auth["headers"]).json()["items"]
    assert item["is_active"] is False and item["fee"] == 2200
    assert [r["fee"] for r in item["fee_history"]] == [2200, 2000]
    assert client.get(PUBLIC).json()["items"] == []


# ---- settings ------------------------------------------------------------------------------
def test_settings_read_and_write_with_audit(client, db, admin_auth, management_auth):
    empty = client.get(SETTINGS, headers=management_auth["headers"]).json()
    assert empty == {
        "items": [
            {"key": key, "value": None, "updated_at": None, "updated_by_user_id": None}
            for key in REGISTERED
        ]
    }
    res = client.patch(SETTINGS, json={THRESHOLD: 200_000}, headers=admin_auth["headers"])
    assert res.status_code == 200, res.text
    [item] = [i for i in res.json()["items"] if i["key"] == THRESHOLD]
    assert item["value"] == 200_000 and item["updated_at"] is not None
    assert item["updated_by_user_id"] == str(admin_auth["user"].id)
    set_threshold(client, admin_auth["headers"], 200_000)  # unchanged: not audited
    set_threshold(client, admin_auth["headers"], 150_000)
    records = audits(db, "settings.update")
    assert [r.change_summary["changes"][THRESHOLD] for r in records] == [
        {"from": None, "to": 200_000},
        {"from": 200_000, "to": 150_000},
    ]
    items = client.get(SETTINGS, headers=management_auth["headers"]).json()["items"]
    assert {i["key"]: i["value"] for i in items}[THRESHOLD] == 150_000
    db.expire_all()
    assert db.get(Setting, THRESHOLD).value == 150_000


@pytest.mark.parametrize(
    "body",
    [
        {},
        {THRESHOLD: None},
        {THRESHOLD: "200000"},
        {THRESHOLD: 200000.0},
        {THRESHOLD: True},
        {THRESHOLD: -1},
        {THRESHOLD: 1_000_000_000_000},
        {THRESHOLD: {"amount": 1}},
        {"free_delivery_threshold": 1},
        {"delivery.unknown": 1},
        {"contact.unknown": "+250788000000"},
        {THRESHOLD: 1, "payments.secret": "x"},
    ],
)
def test_settings_reject_unknown_keys_and_malformed_values(client, db, admin_auth, body):
    res = client.patch(SETTINGS, json=body, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text
    assert db.scalar(select(Setting.key)) is None


def test_settings_reject_a_non_object_body(client, admin_auth):
    h = {**admin_auth["headers"], "Content-Type": "application/json"}
    assert client.patch(SETTINGS, content=b"[1]", headers=h).status_code == 422
    assert client.patch(SETTINGS, content=b"{not json", headers=h).status_code == 422


def test_unregistered_stored_settings_are_never_exposed(client, db, admin_auth):
    db.add(Setting(key="internal.secret_flag", value="hidden"))
    db.commit()
    body = client.get(SETTINGS, headers=admin_auth["headers"]).json()
    assert [item["key"] for item in body["items"]] == REGISTERED
    assert "hidden" not in str(body)


# ---- quotes and the threshold boundary -----------------------------------------------------
@pytest.mark.parametrize(
    ("subtotal", "fee", "free"),
    [(0, 2000, False), (199_999, 2000, False), (200_000, 0, True), (200_001, 0, True)],
)
def test_threshold_boundary(db, client, configured, subtotal, fee, free):
    quote = quote_for_zone(db, "kicukiro", subtotal)
    assert (quote.delivery_fee, quote.free_delivery, quote.zone_fee) == (fee, free, 2000)
    assert quote.free_delivery_threshold == 200_000


def test_quote_from_an_address_district(db, client, admin_auth, configured):
    assert quote_for_district(db, " nyarugenge ", 1000).delivery_fee == 1500
    assert quote_for_district(db, "GASABO", 1000).zone_code == "gasabo"
    for district in ("Musanze", "Kigali", "", "Gasabo district"):
        with pytest.raises(DeliveryZoneUnavailable):
            quote_for_district(db, district, 1000)
    client.patch(
        f"{ZONES}/{configured['Gasabo']['id']}",
        json={"is_active": False},
        headers=admin_auth["headers"],
    )
    db.expire_all()
    with pytest.raises(DeliveryZoneUnavailable):
        quote_for_district(db, "Gasabo", 1000)


def test_quote_needs_the_threshold_and_a_current_fee(db, client, admin_auth):
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    with pytest.raises(DeliveryQuoteUnavailable):  # no threshold yet: never a default
        quote_for_zone(db, "gasabo", 1000)
    db.add(Setting(key=THRESHOLD, value="200000"))  # a corrupt stored value counts as unset
    db.commit()
    with pytest.raises(DeliveryQuoteUnavailable):
        quote_for_zone(db, "gasabo", 1000)
    with pytest.raises(ValueError):
        quote_for_zone(db, "gasabo", -1)


# ---- cart integration ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("price", "delivery_fee", "grand_total"),
    [(199_999, 2000, 201_999), (200_000, 0, 200_000), (100_000, 2000, 202_000)],
)
def test_cart_quote_at_the_threshold_boundary(
    client, db, customer_auth, configured, price, delivery_fee, grand_total
):
    h = customer_auth["headers"]
    quantity = 2 if price == 100_000 else 1  # 2 x 100 000 reaches the threshold exactly
    assert add(client, sku(db, price=price), quantity, h).status_code == 200
    body = client.get(CART, params={"zone": "kicukiro"}, headers=h).json()
    expected_fee = 0 if price * quantity >= 200_000 else 2000
    assert body["delivery"]["delivery_fee"] == expected_fee
    assert body["grand_total"] == price * quantity + expected_fee
    if quantity == 1:
        assert (body["delivery"]["delivery_fee"], body["grand_total"]) == (
            delivery_fee,
            grand_total,
        )
    assert body["delivery"]["zone_fee"] == 2000
    assert body["delivery"]["free_delivery"] is (expected_fee == 0)
    assert body["delivery"]["free_delivery_threshold"] == 200_000


def test_cart_quote_for_a_guest_ignores_client_amounts(client, db, configured):
    created = add(client, sku(db, price=5000), 3)
    token = created.json()["cart_token"]
    res = client.get(
        CART,
        params={"zone": "nyarugenge", "grand_total": 1, "delivery_fee": 0, "subtotal": 1},
        headers={"X-Cart-Token": token},
    )
    body = res.json()
    assert res.status_code == 200
    assert body["merchandise_subtotal"] == 15_000
    assert body["delivery"] == {
        "zone_code": "nyarugenge",
        "zone_name": "Nyarugenge",
        "district": "Nyarugenge",
        "cod_available": True,
        "zone_fee": 1500,
        "delivery_fee": 1500,
        "free_delivery": False,
        "free_delivery_threshold": 200_000,
    }
    assert body["grand_total"] == 16_500


def test_cart_quote_uses_only_available_lines(client, db, customer_auth, configured):
    h = customer_auth["headers"]
    add(client, sku(db, price=150_000, on_hand=1), 1, h)
    low = sku(db, price=60_000, on_hand=2)
    add(client, low, 2, h)
    # Stock falls below the line: it is flagged and leaves the subtotal, so delivery is charged.
    balance = db.scalar(
        select(InventoryBalance).where(InventoryBalance.variant_id == uuid.UUID(low))
    )
    balance.on_hand = 1
    db.commit()
    body = client.get(CART, params={"zone": "gasabo"}, headers=h).json()
    assert body["has_unavailable_lines"] is True
    assert body["merchandise_subtotal"] == 150_000
    assert (body["delivery"]["delivery_fee"], body["grand_total"]) == (2000, 152_000)


def test_cart_refuses_inactive_and_unknown_zones(client, db, admin_auth, customer_auth, configured):
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    client.patch(
        f"{ZONES}/{configured['Gasabo']['id']}",
        json={"is_active": False},
        headers=admin_auth["headers"],
    )
    for zone in ("gasabo", "musanze", "Kicukiro"):  # codes are exact
        res = client.get(CART, params={"zone": zone}, headers=h)
        assert res.status_code == 422 and code(res) == "delivery_zone_unavailable", zone


def test_cart_answers_503_while_delivery_is_not_configured(client, db, admin_auth, customer_auth):
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    res = client.get(CART, params={"zone": "gasabo"}, headers=h)  # no threshold set
    assert res.status_code == 503 and code(res) == "delivery_quote_unavailable"
    assert "grand_total" not in res.text
    set_threshold(client, admin_auth["headers"], 200_000)
    assert client.get(CART, params={"zone": "gasabo"}, headers=h).json()["grand_total"] == 3000


def test_an_empty_cart_is_quoted_with_the_zone_fee(client, configured):
    body = client.get(CART, params={"zone": "kicukiro"}).json()
    assert body["id"] is None and body["merchandise_subtotal"] == 0
    assert (body["delivery"]["delivery_fee"], body["grand_total"]) == (2000, 2000)


def test_openapi_documents_the_delivery_routes():
    app.openapi_schema = None
    paths = app.openapi()["paths"]
    assert set(paths[PUBLIC]) == {"get"}
    assert set(paths[ZONES]) == {"get", "post"}
    assert set(paths[f"{ZONES}/{{zone_id}}"]) == {"patch"}
    assert set(paths[SETTINGS]) == {"get", "patch"}
    for path, method in ((ZONES, "post"), (f"{ZONES}/{{zone_id}}", "patch"), (SETTINGS, "patch")):
        assert {"401", "403", "422"} <= set(paths[path][method]["responses"])
    cart = paths[CART]["get"]["responses"]
    assert {"422", "503"} <= set(cart)
