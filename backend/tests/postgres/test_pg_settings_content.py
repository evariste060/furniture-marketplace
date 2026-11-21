"""Module 19 settings and pages over real HTTP on the least-privilege runtime role, in two API
processes: what an administrator writes through one process is public through the other, and
the runtime role has exactly the privileges the feature uses (no DELETE on pages or quote
requests)."""

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP


def test_contact_details_and_pages_are_public_across_processes(
    stack: Stack, admin: dict, unique: str
):
    changed = HTTP.patch(
        f"{stack.servers[0]}/staff/settings",
        json={"contact.phone": "+250 788 765 432", "contact.email": f"Shop.{unique}@PG.test"},
        headers=admin,
    )
    assert changed.status_code == 200, changed.text
    public = HTTP.get(f"{stack.servers[1]}/settings")
    assert public.status_code == 200
    assert public.json()["phone"] == "+250 788 765 432"
    assert public.json()["email"] == f"shop.{unique}@pg.test"
    assert public.headers["cache-control"] == "public, max-age=60"

    body = f"## Warranty\n\nText {unique}."
    written = HTTP.put(
        f"{stack.servers[0]}/staff/pages/warranty",
        params={"lang": "en"},
        json={"title": "Warranty", "body": body, "is_published": True},
        headers=admin,
    )
    assert written.status_code == 200, written.text
    read = HTTP.get(f"{stack.servers[1]}/pages/warranty", params={"lang": "en"})
    assert read.status_code == 200 and read.json()["body"] == body
    missing = HTTP.get(f"{stack.servers[1]}/pages/warranty", params={"lang": "rw"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "page_not_found"
    replaced = HTTP.put(
        f"{stack.servers[1]}/staff/pages/warranty",
        params={"lang": "en"},
        json={"title": "Warranty", "body": "New text.", "is_published": True},
        headers=admin,
    )
    assert replaced.status_code == 200, replaced.text
    assert (
        HTTP.get(f"{stack.servers[0]}/pages/warranty", params={"lang": "en"}).json()["body"]
        == "New text."
    )
    listed = HTTP.get(f"{stack.servers[0]}/staff/pages", headers=admin).json()["items"]
    assert next(p for p in listed if p["slug"] == "warranty")["en"]["body"] == "New text."
    # Only the six policy pages exist.
    unknown = HTTP.put(
        f"{stack.servers[0]}/staff/pages/policy-{unique}".lower(),
        params={"lang": "en"},
        json={"title": "Policy", "body": "Text.", "is_published": True},
        headers=admin,
    )
    assert unknown.status_code == 422


@pytest.mark.parametrize("table", ["pages", "quote_requests"])
def test_runtime_role_cannot_delete_content(stack: Stack, table: str):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"DELETE FROM {table} WHERE false")
