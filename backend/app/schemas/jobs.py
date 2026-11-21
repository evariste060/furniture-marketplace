"""Job queue schemas (approved 2026-10-26, checkpoint 1b topic 4)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.jobs import JobItemState, JobState, JobType


class JobItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_index: int = Field(description="Position in the request, from 0")
    input: dict[str, Any] = Field(
        description="What the item is about, e.g. for a bulk image upload the file name, the "
        "matched product slug and name, and the position"
    )
    state: JobItemState
    attempts: int
    error: str | None = Field(description="'<code>: <message>' when the item failed")
    result: dict[str, Any] | None = Field(description="What the item did, once known")


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: JobType
    state: JobState = Field(description="queued, processing, or finished (no item left to run)")
    total_items: int
    succeeded_items: int
    failed_items: int
    created_at: datetime
    finished_at: datetime | None
    items: list[JobItemResponse]

    @classmethod
    def from_job(cls, job: Any) -> "JobResponse":
        return cls.model_validate(
            {
                **{f: getattr(job, f) for f in cls.model_fields if f != "items"},
                "items": [
                    JobItemResponse.model_validate(
                        {
                            **{
                                f: getattr(item, f)
                                for f in JobItemResponse.model_fields
                                if f != "input"
                            },
                            "input": (item.payload or {}).get("public", {}),
                        }
                    )
                    for item in job.items
                ],
            }
        )
