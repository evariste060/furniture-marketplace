"""The public image object (ADR-009; checkpoint 1b, 2026-10-26)."""

from pydantic import BaseModel, ConfigDict, Field


class PublicImage(BaseModel):
    """The one public image object (ADR-009), shared by products (images), categories (image),
    brands (logo) and banners (image), so generated clients have a single type. url is the
    public source in its original format; resizing for display happens at delivery (the Next.js
    image loader requests the width it needs). A single image has position 0."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "url": "https://media.example.rw/products/1a2b3c4d-5e6f-4a8b-9c0d-"
                    "1e2f3a4b5c6d/3f2a9c4e8b7d4f1a9e6c5b4a3d2e1f0a-9b1c2d3e4f5a.jpg",
                    "width": 2400,
                    "height": 1800,
                    "alt": "Front view",
                    "position": 0,
                }
            ]
        }
    )

    url: str = Field(description="Public URL of the image (IMAGE_PUBLIC_BASE_URL + key)")
    width: int = Field(gt=0, description="Width in pixels")
    height: int = Field(gt=0, description="Height in pixels")
    alt: str = Field(
        description="Alternative text: the image's alt text, else the product, category or "
        "brand name"
    )
    position: int = Field(ge=0, description="Display order; lower comes first")
