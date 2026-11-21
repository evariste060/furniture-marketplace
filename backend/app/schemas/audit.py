import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditRecordResponse(BaseModel):
    """One row of audit_records. change_summary carries status, ip_address, user_agent and
    bounded details; failed logins carry identifier_ref (keyed HMAC), never raw identifiers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_identifier_snapshot: str | None = None
    action: str
    entity_type: str
    entity_id: str
    request_id: str | None = None
    change_summary: dict[str, Any]
    note: str | None = None
    created_at: datetime
