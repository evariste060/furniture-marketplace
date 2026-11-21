"""Policy page schemas (module 19).

The body is Markdown. The API stores it as text and never renders it; the storefront renders it
without raw HTML. The title is plain text (control characters removed, ends trimmed); the body
keeps its line breaks, loses other control characters and has its ends trimmed.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.models.content import PAGE_BODY_MAX_LENGTH, PAGE_TITLE_MAX_LENGTH
from app.schemas.banners import plain_text

PageLocale = Literal["en", "rw"]
PageSlug = Literal[
    "about-us",
    "delivery-information",
    "returns-and-refunds",
    "warranty",
    "privacy-policy",
    "terms-and-conditions",
]


def _markdown(value: object) -> object:
    """Keep line breaks and tabs; drop other control characters; trim the ends."""
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or ch.isprintable()).strip()


class PageUpdateRequest(BaseModel):
    """One language version of a page, written whole (PUT)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "title": "Delivery information",
                    "body": "We deliver to every district in Rwanda.\n\n## Delivery zones\n...",
                    "is_published": True,
                }
            ]
        },
    )

    title: Annotated[
        str,
        BeforeValidator(plain_text),
        StringConstraints(min_length=1, max_length=PAGE_TITLE_MAX_LENGTH),
    ]
    body: Annotated[
        str,
        BeforeValidator(_markdown),
        StringConstraints(min_length=1, max_length=PAGE_BODY_MAX_LENGTH),
    ] = Field(description="Markdown: headings, lists, tables, links and quotes; no raw HTML")
    is_published: bool = Field(strict=True, description="Only published pages are public")


class PublicPage(BaseModel):
    slug: PageSlug
    locale: PageLocale
    title: str
    body: str = Field(description="Markdown; render without raw HTML")
    updated_at: datetime


class StaffPageVersion(BaseModel):
    title: str
    body: str
    is_published: bool
    updated_at: datetime
    updated_by_user_id: uuid.UUID | None


class StaffPage(BaseModel):
    """A page with both language versions; null when that language has not been written."""

    slug: PageSlug
    en: StaffPageVersion | None
    rw: StaffPageVersion | None


class StaffPagesResponse(BaseModel):
    items: list[StaffPage] = Field(description="Every policy page, in menu order")
