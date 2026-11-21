"""The admin frontend keeps a copy of the role matrix to explain what each role can open
(frontend/src/features/admin/role-permissions.json). It must match ROLE_PERMISSIONS."""

import json
from pathlib import Path

from app.core.roles import ROLE_PERMISSIONS, Role

COPY = Path(__file__).resolve().parents[3] / "frontend/src/features/admin/role-permissions.json"


def test_the_admin_frontend_role_copy_matches_the_backend():
    copy = json.loads(COPY.read_text(encoding="utf-8"))
    copy.pop("_comment")
    expected = {
        role: sorted(perms)
        for role, perms in ROLE_PERMISSIONS.items()
        if role not in (Role.CUSTOMER.value, Role.ADMINISTRATOR.value)
    }
    assert copy == expected
