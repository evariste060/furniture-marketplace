"""Seller applications, store approval and seller access (ADR-014 phase 1).

Covers who may apply, one store per user and case-insensitive names (API and database), the
whole lifecycle with its history, audit trail and emails (rendered from each decision, never from
the store's later state), every invalid transition, require_approved_seller (including a
suspension applied to an existing session), the seller's own store, the administrator-only
permission matrix, commission inheritance, concurrency, and what each response exposes.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.request_context import RequestContext
from app.integrations.notifications import get_notification_provider
from app.main import app
from app.models import AuditRecord, NotificationLog, Store, StoreStatusHistory, User
from app.schemas.stores import StoreApplicationRequest, StoreStatusRequest
from app.services import notification_service
from app.services.store_service import StoreService
from tests.support.messages import ScriptedProvider
from tests.support.sellers import (
    APPLY,
    SELLER_STORE,
    STAFF_SELLERS,
    application,
    apply,
    approved_seller,
    decide,
)

CTX = RequestContext(ip_address="127.0.0.1", user_agent="seller-test")
STAFF_SETTINGS = "/api/v1/staff/settings"
SECRET_FIELDS = {"password", "password_hash", "token_hash", "session_token"}
REASON_A = "Please add the street address of your workshop."
REASON_B = "The phone number did not answer; please check it."
REASON_C = "Several customers reported undelivered orders."


@pytest.fixture
def notify(client, monkeypatch) -> ScriptedProvider:
    monkeypatch.setattr(get_settings(), "notification_provider", "mock")
    provider = ScriptedProvider()
    app.dependency_overrides[get_notification_provider] = lambda: provider
    return provider


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditRecord)
            .where(AuditRecord.action == action)
            .order_by(AuditRecord.created_at, AuditRecord.id)
        )
    )


def store_logs(db: Session) -> list[NotificationLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(NotificationLog)
            .where(NotificationLog.subject_type == "store_status")
            .order_by(NotificationLog.created_at, NotificationLog.id)
        )
    )


def history(db: Session, store_id: str) -> list[StoreStatusHistory]:
    db.expire_all()
    return list(
        db.scalars(
            select(StoreStatusHistory)
            .where(StoreStatusHistory.store_id == uuid.UUID(store_id))
            .order_by(StoreStatusHistory.created_at, StoreStatusHistory.id)
        )
    )


def error_code(res) -> str:
    return res.json()["error"]["code"]


# ---- who may apply -----------------------------------------------------------------------
def test_a_verified_customer_applies_and_gets_a_pending_store(
    client: TestClient, db: Session, customer_auth: dict, notify: ScriptedProvider
):
    res = apply(client, customer_auth)
    assert res.status_code == 201, res.text
    store = res.json()
    assert store["status"] == "pending"
    assert store["slug"] == "kigali-oak-works"
    assert store["contact_phone"] == "+250788765432"
    assert store["contact_email"] == "sales@oakworks.example.rw"
    assert store["description"] == "Hand-made solid wood tables.\n\nDelivered in Kigali."
    assert store["status_reason"] is None and store["approved_at"] is None
    assert store["effective_commission_rate_bps"] == 1000
    assert set(store) & {"owner", "owner_user_id", "commission_rate_bps", "history"} == set()

    row = db.get(Store, uuid.UUID(store["id"]))
    assert row is not None and str(row.owner_user_id) == customer_auth["user"]["id"]
    [entry] = history(db, store["id"])
    assert (entry.status, entry.reason, entry.store_name) == ("pending", None, "Kigali Oak Works")
    assert str(entry.actor_user_id) == customer_auth["user"]["id"]
    assert len(audits(db, "store.application_submit")) == 1
    # The acknowledgement goes to the verified account email, never the store's contact email.
    [log] = store_logs(db)
    assert log.event == "store_application_received" and log.subject_id == entry.id
    assert log.recipient == "customer.a@example.com"
    [message] = notify.messages
    assert message.recipient == "customer.a@example.com"
    assert "Kigali Oak Works" in message.subject

    read = client.get(APPLY, headers=customer_auth["headers"])
    assert read.status_code == 200 and read.json()["id"] == store["id"]


def test_applying_needs_a_session(client: TestClient):
    assert client.post(APPLY, json=application()).status_code == 401
    assert client.get(APPLY).status_code == 401
    assert client.put(APPLY, json=application()).status_code == 401


def test_staff_cannot_apply(client: TestClient, db: Session, admin_auth: dict):
    for auth in (admin_auth,):  # the only staff role since SC-05
        res = apply(client, auth)
        assert res.status_code == 403 and error_code(res) == "staff_cannot_sell"
    assert db.scalar(select(Store.id)) is None


def test_an_account_without_a_verified_email_cannot_apply(client: TestClient, db: Session):
    res = client.post(
        "/api/v1/auth/register",
        json={"phone": "0788 222 333", "full_name": "Phone Only", "password": "SecurePass123!"},
    )
    assert res.status_code == 201, res.text
    token = res.json()["session_token"]
    assert token  # a phone-only account signs in without an email
    refused = apply(client, {"headers": {"Authorization": f"Bearer {token}"}})
    assert refused.status_code == 403 and error_code(refused) == "email_verification_required"
    # An email that is not verified yet does not count either.
    user = db.get(User, uuid.UUID(res.json()["user"]["id"]))
    assert user is not None
    user.email = "unverified@example.com"
    db.commit()
    refused = apply(client, {"headers": {"Authorization": f"Bearer {token}"}})
    assert refused.status_code == 403 and error_code(refused) == "email_verification_required"
    assert db.scalar(select(Store.id)) is None


def test_no_applicant_has_a_store_until_they_apply(client: TestClient, customer_auth: dict):
    res = client.get(APPLY, headers=customer_auth["headers"])
    assert res.status_code == 404 and error_code(res) == "store_not_found"


@pytest.mark.parametrize(
    "field",
    ["owner_user_id", "status", "slug", "commission_rate_bps", "store_id", "approved_at", "id"],
)
def test_owner_status_slug_and_commission_cannot_be_sent(
    client: TestClient, db: Session, customer_auth: dict, field: str
):
    value = 0 if field == "commission_rate_bps" else str(uuid.uuid4())
    res = client.post(APPLY, json={**application(), field: value}, headers=customer_auth["headers"])
    assert res.status_code == 422, res.text
    assert db.scalar(select(Store.id)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"contact_phone": "+254712345678"},
        {"contact_phone": "12345"},
        {"contact_email": "not-an-email"},
        {"contact_email": "a@b"},
        {"name": "x"},
        {"name": "n" * 121},
        {"district": ""},
        {"description": "d" * 2001},
        {"street_address": "s" * 241},
    ],
)
def test_invalid_application_fields_are_422(
    client: TestClient, db: Session, customer_auth: dict, changes: dict
):
    res = apply(client, customer_auth, **changes)
    assert res.status_code == 422, res.text
    assert db.scalar(select(Store.id)) is None


def test_blank_optional_fields_become_null_and_control_characters_are_removed(
    client: TestClient, customer_auth: dict
):
    res = apply(client, customer_auth, name="  Oak\x00 House\t ", sector="   ", description="  ")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Oak House"
    assert body["sector"] is None and body["description"] is None


# ---- one store per user, unique names ----------------------------------------------------
def test_one_store_per_user(client: TestClient, db: Session, customer_auth: dict):
    assert apply(client, customer_auth).status_code == 201
    again = apply(client, customer_auth, name="Another Name")
    assert again.status_code == 409 and error_code(again) == "store_exists"
    # The database enforces it too.
    existing = db.scalar(select(Store))
    assert existing is not None
    db.add(
        Store(
            owner_user_id=existing.owner_user_id,
            name="Direct Insert",
            slug="direct-insert",
            contact_email="x@example.com",
            contact_phone="+250788000111",
            district="Gasabo",
            status="pending",
            submitted_at=existing.submitted_at,
        )
    )
    with pytest.raises(IntegrityError) as raised:
        db.flush()
    assert "uq_stores_owner_user_id" in str(raised.value)
    db.rollback()


def test_store_names_are_unique_regardless_of_letter_case(
    client: TestClient, db: Session, customer_auth: dict, second_customer_auth: dict
):
    assert apply(client, customer_auth).status_code == 201
    taken = apply(client, second_customer_auth, name="KIGALI oak WORKS")
    assert taken.status_code == 409 and error_code(taken) == "store_name_taken"
    first = db.scalar(select(Store))
    assert first is not None
    other = db.get(User, uuid.UUID(second_customer_auth["user"]["id"]))
    assert other is not None
    db.add(
        Store(
            owner_user_id=other.id,
            name="kigali OAK works",
            slug="other-slug",
            contact_email="x@example.com",
            contact_phone="+250788000111",
            district="Gasabo",
            status="pending",
            submitted_at=first.submitted_at,
        )
    )
    with pytest.raises(IntegrityError) as raised:
        db.flush()
    assert "uq_stores_name_lower" in str(raised.value)
    db.rollback()


def test_similar_names_get_distinct_slugs(
    client: TestClient, customer_auth: dict, second_customer_auth: dict
):
    assert apply(client, customer_auth, name="Oak & Co").json()["slug"] == "oak-co"
    assert apply(client, second_customer_auth, name="Oak Co").json()["slug"] == "oak-co-2"


def test_concurrent_applications_by_one_user_create_one_store(
    client: TestClient, db: Session, customer_auth: dict
):
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    user_id = uuid.UUID(customer_auth["user"]["id"])
    barrier = threading.Barrier(4)

    def attempt(n: int) -> str:
        session = factory()
        try:
            user = session.get(User, user_id)
            assert user is not None
            barrier.wait()
            StoreService.apply(
                session, user, StoreApplicationRequest(**application(name=f"Shop {n}")), CTX
            )
            return "created"
        except AppError as exc:
            return exc.code
        finally:
            session.close()

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("created") == 1
    assert set(results) - {"created"} == {"store_exists"}
    assert db.scalar(text("SELECT count(*) FROM stores")) == 1


# ---- the lifecycle -----------------------------------------------------------------------
def test_pending_applications_can_be_edited_without_a_new_submission(
    client: TestClient, db: Session, customer_auth: dict, notify: ScriptedProvider
):
    store = apply(client, customer_auth).json()
    edited = client.put(
        APPLY, json=application(name="Kigali Teak Works"), headers=customer_auth["headers"]
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["status"] == "pending" and body["name"] == "Kigali Teak Works"
    assert body["slug"] == "kigali-teak-works"  # never public yet: the address follows the name
    assert body["submitted_at"] == store["submitted_at"]
    assert len(history(db, store["id"])) == 1
    assert len(audits(db, "store.application_update")) == 1
    assert len(store_logs(db)) == 1  # no second acknowledgement
    # Sending the same values again changes nothing and is not audited.
    same = client.put(
        APPLY, json=application(name="Kigali Teak Works"), headers=customer_auth["headers"]
    )
    assert same.status_code == 200
    assert len(audits(db, "store.application_update")) == 1


def test_full_lifecycle_keeps_history_audit_and_one_email_per_decision(
    client: TestClient,
    db: Session,
    customer_auth: dict,
    admin_auth: dict,
    notify: ScriptedProvider,
):
    store_id = apply(client, customer_auth).json()["id"]

    rejected = decide(client, admin_auth, store_id, "rejected", REASON_A)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status_reason"] == REASON_A
    assert client.get(APPLY, headers=customer_auth["headers"]).json()["status_reason"] == REASON_A

    resubmitted = client.put(
        APPLY, json=application(name="Oak Works Kigali"), headers=customer_auth["headers"]
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["status"] == "pending"
    assert resubmitted.json()["status_reason"] is None  # cleared; the history keeps it

    assert decide(client, admin_auth, store_id, "rejected", REASON_B).status_code == 200
    assert (
        client.put(APPLY, json=application(), headers=customer_auth["headers"]).status_code == 200
    )

    approved = decide(client, admin_auth, store_id, "approved")
    assert approved.status_code == 200, approved.text
    first_approval = approved.json()["approved_at"]
    assert first_approval is not None and approved.json()["status_reason"] is None

    suspended = decide(client, admin_auth, store_id, "suspended", REASON_C)
    assert suspended.status_code == 200 and suspended.json()["status_reason"] == REASON_C
    reinstated = decide(client, admin_auth, store_id, "approved")
    assert reinstated.status_code == 200
    assert reinstated.json()["approved_at"] == first_approval  # the first approval is kept
    assert reinstated.json()["status_reason"] is None

    entries = history(db, store_id)
    assert [(e.status, e.reason) for e in entries] == [
        ("pending", None),
        ("rejected", REASON_A),
        ("pending", None),
        ("rejected", REASON_B),
        ("pending", None),
        ("approved", None),
        ("suspended", REASON_C),
        ("approved", None),
    ]
    assert [e.store_name for e in entries][:3] == [
        "Kigali Oak Works",
        "Kigali Oak Works",
        "Oak Works Kigali",
    ]
    admin_id = admin_auth["user"].id
    assert all(e.actor_user_id == admin_id for e in entries if e.status != "pending")

    changes = [a.change_summary for a in audits(db, "store.status_change")]
    assert [(c["from"], c["to"]) for c in changes] == [
        ("pending", "rejected"),
        ("pending", "rejected"),
        ("pending", "approved"),
        ("approved", "suspended"),
        ("suspended", "approved"),
    ]
    assert len(audits(db, "store.application_resubmit")) == 2

    logs = store_logs(db)
    assert [log.event for log in logs] == [
        "store_application_received",
        "store_rejected",
        "store_application_received",
        "store_rejected",
        "store_application_received",
        "store_approved",
        "store_suspended",
        "store_reinstated",
    ]
    assert len({log.dedupe_key for log in logs}) == len(logs)  # nothing deduplicated away
    assert [log.subject_id for log in logs] == [e.id for e in entries]
    assert {log.recipient for log in logs} == {"customer.a@example.com"}
    assert len(notify.messages) == len(logs)
    rejection_texts = [m.text for m in notify.messages if "not approved" in m.subject]
    assert len(rejection_texts) == 2
    assert REASON_A in rejection_texts[0] and REASON_B not in rejection_texts[0]
    assert REASON_B in rejection_texts[1]


def test_a_retried_email_shows_its_own_decision_not_the_stores_current_state(
    client: TestClient, db: Session, customer_auth: dict, admin_auth: dict, notify
):
    store_id = apply(client, customer_auth).json()["id"]
    decide(client, admin_auth, store_id, "rejected", REASON_A)
    client.put(APPLY, json=application(name="Renamed Store"), headers=customer_auth["headers"])
    decide(client, admin_auth, store_id, "approved")
    decide(client, admin_auth, store_id, "suspended", REASON_C)
    rejection = next(log for log in store_logs(db) if log.event == "store_rejected")
    # Rendering it again now (as a retry would) still gives the first decision.
    rendered = notification_service._render(db, rejection)
    assert rendered is not None
    assert "Kigali Oak Works" in rendered.subject and "Renamed Store" not in rendered.text
    assert REASON_A in rendered.text and REASON_C not in rendered.text
    assert "not approved" in rendered.subject


@pytest.mark.parametrize(
    ("path", "requested"),
    [
        ([], "suspended"),  # pending -> suspended
        (["approved"], "approved"),
        (["approved"], "rejected"),
        (["rejected"], "approved"),
        (["rejected"], "rejected"),
        (["rejected"], "suspended"),
        (["approved", "suspended"], "suspended"),
        (["approved", "suspended"], "rejected"),
    ],
)
def test_invalid_transitions_are_409(
    client: TestClient,
    db: Session,
    customer_auth: dict,
    admin_auth: dict,
    path: list[str],
    requested: str,
):
    store_id = apply(client, customer_auth).json()["id"]
    for step in path:
        reason = REASON_A if step in ("rejected", "suspended") else None
        assert decide(client, admin_auth, store_id, step, reason).status_code == 200
    before = db.get(Store, uuid.UUID(store_id))
    assert before is not None
    status_before, rows_before = before.status, len(history(db, store_id))
    reason = REASON_B if requested in ("rejected", "suspended") else None
    res = decide(client, admin_auth, store_id, requested, reason)
    assert res.status_code == 409, res.text
    assert error_code(res) == "invalid_store_transition"
    assert res.json()["error"]["details"]["current_status"] == status_before
    db.expire_all()
    assert db.get(Store, uuid.UUID(store_id)).status == status_before  # type: ignore[union-attr]
    assert len(history(db, store_id)) == rows_before


@pytest.mark.parametrize("status", ["rejected", "suspended"])
def test_rejecting_or_suspending_needs_a_reason(
    client: TestClient, customer_auth: dict, admin_auth: dict, status: str
):
    store_id = apply(client, customer_auth).json()["id"]
    if status == "suspended":
        decide(client, admin_auth, store_id, "approved")
    for reason in (None, "", "too short"):
        res = decide(client, admin_auth, store_id, status, reason)
        assert res.status_code == 422, res.text
    assert decide(client, admin_auth, store_id, "pending").status_code == 422  # not a decision


@pytest.mark.parametrize("decision", ["approved", "suspended"])
def test_decided_applications_cannot_be_resubmitted(
    client: TestClient, customer_auth: dict, admin_auth: dict, decision: str
):
    store_id = apply(client, customer_auth).json()["id"]
    decide(client, admin_auth, store_id, "approved")
    if decision == "suspended":
        decide(client, admin_auth, store_id, "suspended", REASON_C)
    res = client.put(APPLY, json=application(), headers=customer_auth["headers"])
    assert res.status_code == 409 and error_code(res) == "store_application_closed"


def test_unknown_store_is_404(client: TestClient, admin_auth: dict):
    missing = str(uuid.uuid4())
    assert (
        client.get(f"{STAFF_SELLERS}/{missing}", headers=admin_auth["headers"]).status_code == 404
    )
    assert decide(client, admin_auth, missing, "approved").status_code == 404
    res = client.patch(
        f"{STAFF_SELLERS}/{missing}/commission",
        json={"commission_rate_bps": 5},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 404 and error_code(res) == "store_not_found"


def test_concurrent_administrator_decisions_have_one_winner(
    client: TestClient, db: Session, customer_auth: dict, admin_auth: dict
):
    store_id = uuid.UUID(apply(client, customer_auth).json()["id"])
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(2)
    requests = [
        StoreStatusRequest(status="approved"),
        StoreStatusRequest(status="rejected", reason=REASON_A),
    ]

    def attempt(req: StoreStatusRequest) -> str:
        session = factory()
        try:
            actor = session.get(User, admin_auth["user"].id)
            assert actor is not None
            barrier.wait()
            StoreService.change_status(session, actor, store_id, req, CTX)
            return "ok"
        except AppError as exc:
            return exc.code
        finally:
            session.close()

    with ThreadPoolExecutor(2) as pool:
        results = sorted(pool.map(attempt, requests))
    assert results == ["invalid_store_transition", "ok"]
    entries = history(db, str(store_id))
    assert [e.status for e in entries][0] == "pending" and len(entries) == 2


# ---- require_approved_seller -------------------------------------------------------------
def test_only_an_approved_store_reaches_seller_routes(
    client: TestClient, db: Session, customer_auth: dict, admin_auth: dict
):
    headers = customer_auth["headers"]

    def blocked() -> None:
        for res in (
            client.get(SELLER_STORE, headers=headers),
            client.patch(SELLER_STORE, json={"description": "New"}, headers=headers),
        ):
            assert res.status_code == 403, res.text
            assert error_code(res) == "seller_not_approved"

    blocked()  # no store at all
    store_id = apply(client, customer_auth).json()["id"]
    blocked()  # pending
    decide(client, admin_auth, store_id, "rejected", REASON_A)
    blocked()  # rejected
    client.put(APPLY, json=application(), headers=headers)
    decide(client, admin_auth, store_id, "approved")
    assert client.get(SELLER_STORE, headers=headers).status_code == 200

    # Suspension applies to the very next request made with the same session.
    decide(client, admin_auth, store_id, "suspended", REASON_C)
    blocked()
    denials = [a for a in audits(db, "auth.access_denied") if a.change_summary.get("store_status")]
    assert {a.change_summary["store_status"] for a in denials} >= {
        "pending",
        "rejected",
        "suspended",
    }
    # The suspended seller still reads their application and its reason.
    assert client.get(APPLY, headers=headers).json()["status_reason"] == REASON_C
    decide(client, admin_auth, store_id, "approved")
    assert client.get(SELLER_STORE, headers=headers).status_code == 200


def test_staff_never_pass_the_seller_check(client: TestClient, admin_auth: dict):
    res = client.get(SELLER_STORE, headers=admin_auth["headers"])
    assert res.status_code == 403 and error_code(res) == "seller_not_approved"


def test_a_seller_updates_only_their_own_store(client: TestClient, db: Session, admin_auth: dict):
    a = approved_seller(client, admin_auth, "seller.a@example.com", "+250788100001", "Store A")
    b = approved_seller(client, admin_auth, "seller.b@example.com", "+250788100002", "Store B")
    own = client.get(SELLER_STORE, headers=a["headers"]).json()
    assert own["id"] == a["store_id"] and own["name"] == "Store A"

    res = client.patch(
        SELLER_STORE,
        json={"name": "Store A Furniture", "description": "Beds and wardrobes", "sector": None},
        headers=a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Store A Furniture"
    assert res.json()["slug"] == a["store_slug"]  # a public store keeps its address
    assert res.json()["sector"] is None
    assert len(audits(db, "store.profile_update")) == 1

    # No request can point at another store: a store id, owner, status or commission is 422.
    for extra in (
        {"store_id": b["store_id"]},
        {"id": b["store_id"]},
        {"owner_user_id": b["user"]["id"]},
        {"status": "approved"},
        {"slug": "store-b"},
        {"commission_rate_bps": 0},
    ):
        refused = client.patch(
            SELLER_STORE, json={"name": "X Store", **extra}, headers=a["headers"]
        )
        assert refused.status_code == 422, extra
    query = client.patch(
        f"{SELLER_STORE}?store_id={b['store_id']}",
        json={"description": "Changed through a query"},
        headers=a["headers"],
    )
    assert query.status_code == 200 and query.json()["id"] == a["store_id"]  # ignored

    db.expire_all()
    other = db.get(Store, uuid.UUID(b["store_id"]))
    assert other is not None
    assert (other.name, other.description) == ("Store B", application()["description"])

    taken = client.patch(SELLER_STORE, json={"name": "store b"}, headers=a["headers"])
    assert taken.status_code == 409 and error_code(taken) == "store_name_taken"
    for field in ("name", "contact_email", "contact_phone", "district"):
        assert (
            client.patch(SELLER_STORE, json={field: None}, headers=a["headers"]).status_code == 422
        )
    assert client.patch(SELLER_STORE, json={}, headers=a["headers"]).status_code == 422


# ---- administrators only -----------------------------------------------------------------
@pytest.mark.parametrize("who", ["customer_auth"])
def test_only_administrators_reach_seller_management(
    client: TestClient, admin_auth: dict, request, who: str
):
    owner = approved_seller(client, admin_auth, "owner@example.com", "+250788100009", "Owned")
    auth = request.getfixturevalue(who)
    store = f"{STAFF_SELLERS}/{owner['store_id']}"
    for res in (
        client.get(STAFF_SELLERS, headers=auth["headers"]),
        client.get(store, headers=auth["headers"]),
        client.patch(f"{store}/status", json={"status": "approved"}, headers=auth["headers"]),
        client.patch(
            f"{store}/commission", json={"commission_rate_bps": 1}, headers=auth["headers"]
        ),
    ):
        assert res.status_code == 403, res.text
        assert error_code(res) == "permission_denied"


def test_an_approved_seller_cannot_reach_seller_management(client: TestClient, admin_auth: dict):
    seller = approved_seller(client, admin_auth, "s@example.com", "+250788100010", "Seller One")
    res = client.get(STAFF_SELLERS, headers=seller["headers"])
    assert res.status_code == 403 and error_code(res) == "permission_denied"
    res = decide(client, seller, seller["store_id"], "suspended", REASON_C)
    assert res.status_code == 403


def test_administrators_list_filter_and_read_stores(
    client: TestClient, customer_auth: dict, second_customer_auth: dict, admin_auth: dict
):
    first = apply(client, customer_auth, name="Alpha Beds").json()
    second = apply(client, second_customer_auth, name="Beta Chairs").json()
    decide(client, admin_auth, second["id"], "approved")
    headers = admin_auth["headers"]

    everything = client.get(STAFF_SELLERS, headers=headers).json()
    assert everything["total"] == 2 and [s["id"] for s in everything["items"]] == [
        second["id"],
        first["id"],
    ]
    pending = client.get(STAFF_SELLERS, params={"status": "pending"}, headers=headers).json()
    assert [s["id"] for s in pending["items"]] == [first["id"]]
    by_owner = client.get(STAFF_SELLERS, params={"q": "customer.b@"}, headers=headers).json()
    assert [s["id"] for s in by_owner["items"]] == [second["id"]]
    by_name = client.get(STAFF_SELLERS, params={"q": "ALPHA"}, headers=headers).json()
    assert [s["id"] for s in by_name["items"]] == [first["id"]]
    wildcard = client.get(STAFF_SELLERS, params={"q": "%"}, headers=headers).json()
    assert wildcard["total"] == 0  # LIKE wildcards are matched literally
    paged = client.get(STAFF_SELLERS, params={"size": 1, "page": 2}, headers=headers).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1 and paged["page"] == 2
    assert client.get(STAFF_SELLERS, params={"status": "open"}, headers=headers).status_code == 422

    summary = everything["items"][1]
    assert summary["owner"] == {
        "id": customer_auth["user"]["id"],
        "full_name": "Customer Alice",
        "email": "customer.a@example.com",
        "phone": "+250788111222",
    }
    detail = client.get(f"{STAFF_SELLERS}/{second['id']}", headers=headers).json()
    assert [h["status"] for h in detail["history"]] == ["pending", "approved"]
    assert detail["history"][1]["actor"]["id"] == str(admin_auth["user"].id)
    assert detail["reviewed_by"]["id"] == str(admin_auth["user"].id)
    assert detail["commission_rate_bps"] is None
    assert detail["effective_commission_rate_bps"] == 1000
    text_body = str(everything) + str(detail)
    assert not any(secret in text_body for secret in SECRET_FIELDS)


# ---- commission --------------------------------------------------------------------------
def test_commission_inherits_the_platform_default_unless_overridden(
    client: TestClient, db: Session, admin_auth: dict
):
    seller = approved_seller(client, admin_auth, "c@example.com", "+250788100011", "Commission")
    headers = admin_auth["headers"]
    store = f"{STAFF_SELLERS}/{seller['store_id']}"

    def effective() -> int:
        return client.get(SELLER_STORE, headers=seller["headers"]).json()[
            "effective_commission_rate_bps"
        ]

    assert effective() == 1000  # the setting is unset: 10%
    changed = client.patch(
        STAFF_SETTINGS, json={"marketplace.default_commission_bps": 1250}, headers=headers
    )
    assert changed.status_code == 200, changed.text
    assert effective() == 1250
    assert len(audits(db, "settings.update")) == 1

    override = client.patch(
        f"{store}/commission", json={"commission_rate_bps": 700}, headers=headers
    )
    assert override.status_code == 200, override.text
    assert override.json()["commission_rate_bps"] == 700
    assert override.json()["effective_commission_rate_bps"] == 700
    assert effective() == 700
    client.patch(f"{store}/commission", json={"commission_rate_bps": 700}, headers=headers)
    inherit = client.patch(
        f"{store}/commission", json={"commission_rate_bps": None}, headers=headers
    )
    assert inherit.json()["commission_rate_bps"] is None
    assert effective() == 1250
    assert [
        (a.change_summary["from_bps"], a.change_summary["to_bps"])
        for a in audits(db, "store.commission_change")
    ] == [(None, 700), (700, None)]  # the repeated 700 changed nothing


@pytest.mark.parametrize("value", [-1, 10_001, 12.5, "1000", True])
def test_commission_must_be_whole_basis_points(client: TestClient, admin_auth: dict, value):
    seller = approved_seller(client, admin_auth, "d@example.com", "+250788100012", "Strict Bps")
    headers = admin_auth["headers"]
    res = client.patch(
        f"{STAFF_SELLERS}/{seller['store_id']}/commission",
        json={"commission_rate_bps": value},
        headers=headers,
    )
    assert res.status_code == 422, res.text
    setting = client.patch(
        STAFF_SETTINGS, json={"marketplace.default_commission_bps": value}, headers=headers
    )
    assert setting.status_code == 422, setting.text
    assert (
        client.patch(
            f"{STAFF_SELLERS}/{seller['store_id']}/commission", json={}, headers=headers
        ).status_code
        == 422
    )  # the field is required (null to inherit)


def test_only_settings_managers_change_the_default_commission(
    client: TestClient, customer_auth: dict
):
    res = client.patch(
        STAFF_SETTINGS,
        json={"marketplace.default_commission_bps": 900},
        headers=customer_auth["headers"],  # SC-05: no staff account lacks settings:manage
    )
    assert res.status_code == 403 and error_code(res) == "permission_denied"
