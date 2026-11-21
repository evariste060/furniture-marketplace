from typing import Literal

from pydantic import BaseModel, Field


class RootLinks(BaseModel):
    """Paths on this API, relative to its origin."""

    health: str
    docs: str
    redoc: str
    openapi: str


class RootResponse(BaseModel):
    service: str
    status: Literal["ok"] = Field(
        default="ok",
        description="The process is answering; dependencies are reported by the health link",
    )
    message: str
    links: RootLinks
