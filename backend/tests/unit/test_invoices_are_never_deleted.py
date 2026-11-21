"""Invoices are never deleted by the application (module 16; owner decision 2026-10-27).

The only code allowed to delete an invoice is the development seed cleanup
(scripts/seed_development_catalogue.py --cleanup), which runs on the owner account against a
local development database. The runtime role has no DELETE privilege on invoices (proved on a
real database in tests/postgres/test_pg_invoices.py); these checks keep the code that way.
"""

import importlib.util
import re
from pathlib import Path

from app.main import app

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ALLOWED = {REPO / "scripts" / "seed_development_catalogue.py"}

# delete(Invoice...), session.delete(invoice...), DELETE FROM invoices / invoice_counters.
PATTERNS = (
    re.compile(r"\bdelete\(\s*Invoice(Counter)?\b"),
    re.compile(r"\.delete\(\s*\w*invoice\w*\s*\)", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+\"?invoice", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b[^\n;]*\binvoice", re.IGNORECASE),
)


def _python_sources():
    for root in (BACKEND / "app", REPO / "scripts"):
        yield from (p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_application_code_deletes_an_invoice():
    offenders = [
        f"{path.relative_to(REPO)}: {match.group(0)}"
        for path in _python_sources()
        if path not in ALLOWED
        for pattern in PATTERNS
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_seed_cleanup_is_the_one_allowed_place():
    # Guards the allow-list itself: if the cleanup stops deleting invoices, drop it from ALLOWED.
    (script,) = ALLOWED
    text = script.read_text(encoding="utf-8")
    assert '("invoices", Invoice)' in text


def test_no_api_route_deletes_an_invoice():
    routes = [
        f"{method.upper()} {path}"
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method.lower() == "delete" and "invoice" in path.lower()
    ]
    assert routes == []


def test_the_runtime_role_is_not_granted_delete_on_invoices():
    spec = importlib.util.spec_from_file_location(
        "provision_runtime_role", REPO / "scripts" / "provision_runtime_role.py"
    )
    assert spec is not None and spec.loader is not None
    provision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provision)
    for table in ("invoices", "invoice_counters"):
        assert "DELETE" not in provision.TABLE_GRANTS[table], table
        assert "TRUNCATE" not in provision.TABLE_GRANTS[table], table
