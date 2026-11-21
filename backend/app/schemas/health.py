from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "degraded"]


class HealthChecks(BaseModel):
    """Each dependency the API needs. A degraded check keeps the API up (200) but is reported."""

    database: Literal["ok"] = "ok"
    storage: CheckStatus = Field(
        default="ok", description="Image storage: degraded when it cannot be reached or written"
    )
    catalogue: CheckStatus = Field(
        default="ok",
        description="Production only: degraded while development seed SKUs (DEV-) exist",
    )


class HealthResponse(BaseModel):
    status: CheckStatus = Field(default="ok", description="degraded when any check is degraded")
    database: Literal["ok"] = "ok"  # kept for existing monitors; same as checks.database
    checks: HealthChecks = Field(default_factory=HealthChecks)
