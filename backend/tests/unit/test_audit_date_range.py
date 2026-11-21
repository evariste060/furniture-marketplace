"""The audit date-range rule is enforced in the service, before any query runs."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationFailed
from app.services.audit_service import AuditService


def test_from_after_to_is_rejected_before_touching_the_database():
    later = datetime(2026, 10, 23, 12, tzinfo=UTC)
    with pytest.raises(ValidationFailed) as excinfo:
        AuditService.list_events(db=None, created_from=later, created_to=later - timedelta(hours=1))  # type: ignore[arg-type]
    assert excinfo.value.details[0]["loc"] == ["query", "from"]
