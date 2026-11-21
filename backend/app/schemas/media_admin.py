"""Media cleanup problems for staff (ADR-009; checkpoint 1b topic 1, 2026-10-26)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaCleanupProblem(BaseModel):
    """A stored file the cleanup worker failed to delete; it is retried with backoff."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    storage_key: str
    visibility: str
    kind: str
    owner_type: str
    owner_id: uuid.UUID
    attempts: int
    last_error: str | None
    delete_after: datetime | None
    updated_at: datetime
