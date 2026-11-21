"""Customer support messages (approved 2026-11-11): Contact page questions, My messages and the
staff inbox.

Disposable per-test PostgreSQL schema (tests/conftest.py)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operations import AuditRecord
from app.models.support import SupportThread
from app.services.support_access import access_key
from tests.integration.test_transactional_emails import emails, rows  # noqa: F401

SEND = "/api/v1/support-messages"
MINE = "/api/v1/customers/me/support-threads"
STAFF = "/api/v1/staff/support-threads"
MESSAGE = {
    "topic": "order",
    "name": "  Aline Uwase ",
    "phone": "0788123456",
    "email": "Aline@Example.rw",
    "subject": "Delivery to Musanze",
    "order_number": " 3s-260101-0001 ",
    "body": "Hello,\r\n\r\n\r\nwhen will my order reach Musanze?\x07",
    "locale": "rw",
}


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def send(client, headers=None, **changes):
    return client.post(SEND, json={**MESSAGE, **changes}, headers=headers or {})


def test_a_guest_message_is_stored_cleaned(client, db):
    res = send(client)
    assert res.status_code == 201, res.text
    reference = res.json()["reference"]
    assert reference.startswith("M-") and len(reference) == 15
    thread = db.scalar(select(SupportThread).where(SupportThread.reference == reference))
    assert (thread.name, thread.phone, thread.email) == (
        "Aline Uwase",
        "+250788123456",
        "aline@example.rw",
    )
    assert (thread.order_number, thread.status, thread.customer_user_id) == (
        "3S-260101-0001",
        "open",
        None,
    )
    [message] = thread.messages
    assert (message.author, message.body) == (
        "customer",
        "Hello,\n\nwhen will my order reach Musanze?",
    )


def test_a_message_needs_a_way_to_reply(client):
    res = send(client, phone="", email=None)
    assert res.status_code == 422
    assert send(client, phone=None).status_code == 201  # email alone is enough
    assert send(client, email="", phone="0788555111").status_code == 201  # phone alone too


def test_messages_are_validated(client):
    for change in (
        {"body": " "},
        {"subject": "Hi"},
        {"phone": "0123"},
        {"email": "not-an-email"},
        {"body": "x" * 2001},
        {"locale": "fr"},
        {"topic": "bulk"},
        {"topic": None},
        {"extra": 1},
    ):
        assert send(client, **change).status_code == 422, change


def test_messages_are_rate_limited_per_sender(client):
    for _ in range(5):
        assert send(client).status_code == 201
    limited = send(client)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    assert send(client, phone="0788555111", email=None).status_code == 201


def test_a_customer_follows_the_conversation(client, db, customer_auth, second_customer_auth):
    mine = customer_auth["headers"]
    reference = send(client, headers=mine).json()["reference"]
    page = client.get(MINE, headers=mine).json()
    assert page["total"] == 1
    [item] = page["items"]
    assert (item["reference"], item["status"], item["message_count"]) == (reference, "open", 1)
    assert item["last_author"] == "customer"

    reply = client.post(f"{MINE}/{reference}/messages", json={"body": "Any news?"}, headers=mine)
    assert reply.status_code == 201, reply.text
    assert [m["author"] for m in reply.json()["messages"]] == ["customer", "customer"]
    detail = client.get(f"{MINE}/{reference.lower()}", headers=mine).json()
    assert detail["messages"][-1]["body"] == "Any news?"
    assert "staff_name" not in detail["messages"][0]

    other = second_customer_auth["headers"]
    assert client.get(MINE, headers=other).json()["total"] == 0
    hidden = client.get(f"{MINE}/{reference}", headers=other)
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "support_thread_not_found"
    assert (
        client.post(
            f"{MINE}/{reference}/messages", json={"body": "Mine now"}, headers=other
        ).status_code
        == 404
    )


def test_a_staff_message_from_the_contact_page_is_a_guest_message(client, db, sales_auth):
    reference = send(client, headers=sales_auth["headers"]).json()["reference"]
    thread = db.scalar(select(SupportThread).where(SupportThread.reference == reference))
    assert thread.customer_user_id is None
    assert client.get(MINE, headers=sales_auth["headers"]).status_code == 403


def test_staff_reply_and_close(client, db, sales_auth, customer_auth):
    h = sales_auth["headers"]
    first = send(client).json()["reference"]
    second = send(client, headers=customer_auth["headers"], phone="0788555111").json()["reference"]
    page = client.get(STAFF, headers=h).json()
    assert [t["reference"] for t in page["items"]] == [second, first]  # latest activity first
    assert [t["has_account"] for t in page["items"]] == [True, False]
    thread_id = page["items"][1]["id"]

    res = client.post(f"{STAFF}/{thread_id}/messages", json={"body": "Tomorrow."}, headers=h)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "answered"
    assert [m["author"] for m in body["messages"]] == ["customer", "staff"]
    assert body["messages"][1]["staff_name"] == sales_auth["user"].full_name
    assert client.get(STAFF, headers=h).json()["items"][0]["reference"] == first

    assert client.get(f"{STAFF}?status=open", headers=h).json()["total"] == 1
    assert client.get(f"{STAFF}?q=musanze", headers=h).json()["total"] == 2
    assert client.get(f"{STAFF}?q={first[-6:]}", headers=h).json()["total"] == 1

    closed = client.patch(f"{STAFF}/{thread_id}", json={"status": "closed"}, headers=h)
    assert closed.json()["status"] == "closed"
    assert client.patch(f"{STAFF}/{thread_id}", json={"status": "closed"}, headers=h).is_success
    assert [r.change_summary["to"] for r in audits(db, "support.status_change")] == ["closed"]
    [audit] = audits(db, "support.reply")
    summary = audit.change_summary
    assert (summary["reference"], summary["from"], summary["to"]) == (first, "open", "answered")
    assert "Tomorrow" not in str(audit.change_summary)

    missing = client.post(f"{STAFF}/{uuid.uuid4()}/messages", json={"body": "Hi"}, headers=h)
    assert missing.status_code == 404


def test_a_customer_reply_reopens_the_conversation(client, sales_auth, customer_auth):
    mine = customer_auth["headers"]
    reference = send(client, headers=mine).json()["reference"]
    thread_id = client.get(STAFF, headers=sales_auth["headers"]).json()["items"][0]["id"]
    client.patch(f"{STAFF}/{thread_id}", json={"status": "closed"}, headers=sales_auth["headers"])
    res = client.post(f"{MINE}/{reference}/messages", json={"body": "One more thing"}, headers=mine)
    assert res.json()["status"] == "open"


def test_a_staff_reply_is_emailed(client, db, sales_auth, emails):  # noqa: F811
    reference = send(client).json()["reference"]
    thread_id = client.get(STAFF, headers=sales_auth["headers"]).json()["items"][0]["id"]
    res = client.post(
        f"{STAFF}/{thread_id}/messages",
        json={"body": "It leaves today.\n\nIt arrives tomorrow."},
        headers=sales_auth["headers"],
    )
    assert res.status_code == 201, res.text
    [row] = rows(db, "support_reply")
    assert (row.subject_type, row.recipient) == ("support", "aline@example.rw")
    [mail] = emails.messages
    assert "has been answered" in mail.subject and reference in mail.subject
    assert "Delivery to Musanze" in mail.text
    assert "It leaves today." in mail.text and "It arrives tomorrow." in mail.text
    key = access_key(uuid.UUID(thread_id))
    assert f"/rw/support/{reference}/{key}" in mail.html  # a guest: the private link


def test_a_reply_to_a_phone_only_sender_sends_no_email(client, db, sales_auth, emails):  # noqa: F811
    send(client, email=None)
    thread_id = client.get(STAFF, headers=sales_auth["headers"]).json()["items"][0]["id"]
    client.post(
        f"{STAFF}/{thread_id}/messages", json={"body": "Called you"}, headers=sales_auth["headers"]
    )
    assert rows(db, "support_reply") == [] and emails.messages == []


def test_support_permissions(
    client, admin_auth, management_auth, operations_auth, finance_auth, customer_auth
):
    send(client)
    assert client.get(STAFF, headers=admin_auth["headers"]).status_code == 200
    thread_id = client.get(STAFF, headers=admin_auth["headers"]).json()["items"][0]["id"]
    # Management reads but cannot reply or close.
    assert client.get(STAFF, headers=management_auth["headers"]).status_code == 200
    assert client.get(f"{STAFF}/{thread_id}", headers=management_auth["headers"]).status_code == 200
    for auth in (management_auth, operations_auth, finance_auth, customer_auth):
        h = auth["headers"]
        assert (
            client.post(f"{STAFF}/{thread_id}/messages", json={"body": "Hi"}, headers=h).status_code
            == 403
        )
        assert (
            client.patch(f"{STAFF}/{thread_id}", json={"status": "closed"}, headers=h).status_code
            == 403
        )
    for auth in (operations_auth, finance_auth, customer_auth):
        assert client.get(STAFF, headers=auth["headers"]).status_code == 403
    assert client.get(STAFF).status_code == 401
    assert client.get(MINE).status_code == 401


def test_a_guest_follows_the_conversation_by_its_private_link(client, db, sales_auth):
    sent = send(client).json()
    reference, key = sent["reference"], sent["access_key"]
    link = f"{SEND}/{reference}/{key}"
    thread = client.get(link)
    assert thread.status_code == 200, thread.text
    assert (thread.json()["topic"], thread.json()["status"]) == ("order", "open")

    h = sales_auth["headers"]
    thread_id = client.get(STAFF, headers=h).json()["items"][0]["id"]
    client.post(f"{STAFF}/{thread_id}/messages", json={"body": "Tomorrow."}, headers=h)
    seen = client.get(link).json()
    assert [m["author"] for m in seen["messages"]] == ["customer", "staff"]
    assert "staff_name" not in seen["messages"][1]

    reply = client.post(f"{link}/messages", json={"body": "Thank you"})
    assert reply.status_code == 201, reply.text
    assert reply.json()["status"] == "open"

    other = send(client, phone="0788555111", email=None).json()
    wrong = (
        f"{SEND}/{reference}/{other['access_key']}",  # another conversation's key
        f"{SEND}/{reference}/{'A' * 32}",
        f"{SEND}/M-000000-AAAAAA/{key}",
    )
    for url in wrong:
        res = client.get(url)
        assert res.status_code == 404, url
        assert res.json()["error"]["code"] == "support_thread_not_found"
    assert client.post(f"{wrong[1]}/messages", json={"body": "Hi"}).status_code == 404
    assert client.get(f"{SEND}/{reference}/short").status_code == 422
