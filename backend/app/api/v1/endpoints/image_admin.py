"""Staff product image management (module 7).

Every route requires 'catalog:edit', held by no role in V1 (SC-06). Rules, file handling and
concurrency are in app.services.image_admin; validation and the public source in
app.services.image_processing (ADR-009). Public image URLs appear in the catalogue product
responses.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.responses import (
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.integrations.media import MediaStorage, get_media_storage
from app.models import ProductImage
from app.models.identity import User
from app.schemas.image_admin import (
    UPDATE_EXAMPLES,
    AltText,
    ImageOrderRequest,
    ImageResponse,
    ImageUpdateRequest,
)
from app.services.catalog_scope import CatalogScope
from app.services.image_admin import ImageAdminService, read_upload

router = APIRouter(prefix="/staff", tags=["Staff Catalogue"])
PLATFORM = CatalogScope.platform()  # staff act on every store (ADR-014 phase 2)


def _examples(**cases: tuple[str, str, Any]) -> dict[str, Any]:
    """OpenAPI error examples: name -> (code, message, details)."""
    return {
        "content": {
            "application/json": {
                "examples": {
                    name: {"value": {"error": {"code": c, "message": m, "details": d}}}
                    for name, (c, m, d) in cases.items()
                }
            }
        }
    }


def _field(field: str, msg: str) -> list[dict[str, Any]]:
    return [{"type": "value_error", "loc": ["body", field], "msg": msg}]


GUARDED: ResponseMap = {
    401: {
        **UNAUTHORIZED_401[401],
        **_examples(missing=("token_missing", "Authentication token is missing.", None)),
    },
    403: {
        **FORBIDDEN_403[403],
        **_examples(
            role=(
                "permission_denied",
                "Access forbidden: requires 'catalog:edit' permission.",
                None,
            )
        ),
    },
}
PRODUCT_404: ResponseMap = {
    404: {
        **ERR,
        "description": "No product with this ID",
        **_examples(unknown=("product_not_found", "Product not found.", None)),
    }
}
IMAGE_404: ResponseMap = {
    404: {
        **ERR,
        "description": "No image with this ID",
        **_examples(unknown=("image_not_found", "Image not found.", None)),
    }
}
SORT_ORDER_409: ResponseMap = {
    409: {
        **ERR,
        "description": "sort_order_full: the product's highest sort_order is already the maximum",
        **_examples(full=("sort_order_full", "No higher sort_order is available.", None)),
    }
}
TOO_LARGE_413: ResponseMap = {
    413: {
        **ERR,
        "description": "file_too_large: the upload is larger than 5 MB. Checked while the body "
        "is received, before authentication, so it can also answer an unauthenticated request",
        **_examples(
            request_too_large=("file_too_large", "The upload is larger than 5 MB.", None),
            file_too_large=("file_too_large", "The image is larger than 5 MB.", None),
        ),
    }
}
UPLOAD_422: ResponseMap = {
    422: {
        **ERR,
        "description": "Invalid request, a file that is not a valid JPEG/PNG/WebP image, or a "
        "variant_id that does not belong to the product",
        **_examples(
            not_an_image=(
                "validation_error",
                "Request validation failed.",
                _field("file", "The file is not a valid JPEG, PNG or WebP image."),
            ),
            wrong_variant=(
                "validation_error",
                "Request validation failed.",
                _field("variant_id", "The variant does not belong to this product."),
            ),
        ),
    }
}
MALFORMED_ID = (
    "validation_error",
    "Request validation failed.",
    [
        {
            "type": "uuid_parsing",
            "loc": ["path", "image_id"],
            "msg": "Input should be a valid UUID, invalid character: found `n` at 0",
        }
    ],
)
DELETE_422: ResponseMap = {422: {**VALIDATION_422[422], **_examples(malformed_id=MALFORMED_ID)}}
UPDATE_422: ResponseMap = {
    422: {
        **VALIDATION_422[422],
        **_examples(
            empty=(
                "validation_error",
                "Request validation failed.",
                [
                    {
                        "type": "value_error",
                        "loc": ["body"],
                        "msg": "Value error, Provide at least one field to change.",
                    }
                ],
            ),
            wrong_variant=(
                "validation_error",
                "Request validation failed.",
                _field("variant_id", "The variant does not belong to this product."),
            ),
        ),
    }
}

CatalogEditor = Annotated[User, Depends(require_permission(Permission.CATALOG_EDIT))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Storage = Annotated[MediaStorage, Depends(get_media_storage)]

PERMISSION_NOTE = "Requires 'catalog:edit' (held by no role in V1, SC-06)."


def image_response(image: ProductImage, storage: MediaStorage) -> ImageResponse:
    url = storage.public_url(image.storage_key)
    return ImageResponse(
        id=image.id,
        product_id=image.product_id,
        variant_id=image.variant_id,
        image_ref=image.storage_key,
        url=url,
        thumbnail_url=url,  # ADR-009: no stored thumbnails; resizing happens at delivery
        width=image.width,
        height=image.height,
        alt_text=image.alt_text,
        sort_order=image.sort_order,
        created_at=image.created_at,
        updated_at=image.updated_at,
    )


@router.post(
    "/products/{product_id}/images",
    response_model=ImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a product image",
    description=(
        f"{PERMISSION_NOTE} multipart/form-data with `file` (JPEG, PNG or WebP, at most 5 MB) and "
        "optional `variant_id` and `alt_text`. The file is identified by decoding it, not by its "
        "name or declared type. The exact upload is kept privately; the public source keeps its "
        "format and is turned upright, stripped of metadata and scaled down only if its longest "
        "side is above 2400 px. It is appended after the product's other images. Audited as "
        "'catalog.image_upload'."
    ),
    responses={**GUARDED, **PRODUCT_404, **SORT_ORDER_409, **TOO_LARGE_413, **UPLOAD_422},
)
def upload_image(
    product_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")],
    current_user: CatalogEditor,
    db: Db,
    ctx: Ctx,
    storage: Storage,
    variant_id: Annotated[
        uuid.UUID | None,
        Form(description="A variant of the same product; omit for a product-level image"),
    ] = None,
    alt_text: Annotated[
        AltText | None, Form(description="1-300 characters", examples=["Front view"])
    ] = None,
) -> ImageResponse:
    raw = read_upload(file.file)
    image = ImageAdminService.upload(
        db, storage, current_user, product_id, raw, variant_id, alt_text, ctx, scope=PLATFORM
    )
    return image_response(image, storage)


ORDER_422: ResponseMap = {
    422: {
        **VALIDATION_422[422],
        **_examples(
            mismatch=(
                "validation_error",
                "Request validation failed.",
                _field("image_ids", "List every product image of this product exactly once."),
            ),
        ),
    }
}


@router.put(
    "/products/{product_id}/images/order",
    response_model=list[ImageResponse],
    summary="Reorder a product's images",
    description=(
        f"{PERMISSION_NOTE} `image_ids` lists every product-level image of the product (not "
        "variant images) exactly once, in the new display order. They get positions 1..n "
        "(sort_order 0..n-1) in one transaction, so the bulk upload file names follow the new "
        "order. Returns those images in that order. Audited as 'catalog.image_reorder'; the "
        "order they already have is not audited."
    ),
    responses={**GUARDED, **PRODUCT_404, **SORT_ORDER_409, **ORDER_422},
)
def reorder_images(
    product_id: uuid.UUID,
    req: ImageOrderRequest,
    current_user: CatalogEditor,
    db: Db,
    storage: Storage,
    ctx: Ctx,
) -> list[ImageResponse]:
    images = ImageAdminService.reorder(db, current_user, product_id, req, ctx, scope=PLATFORM)
    return [image_response(image, storage) for image in images]


@router.patch(
    "/images/{image_id}",
    response_model=ImageResponse,
    summary="Update an image's order, alt text or variant",
    description=(
        f"{PERMISSION_NOTE} Partial update of sort_order (>= 0), alt_text (null clears it) and "
        "variant_id (a variant of the same product; null makes it a product-level image). "
        "Audited as 'catalog.image_update'; a request that changes nothing is not audited."
    ),
    responses={**GUARDED, **IMAGE_404, **UPDATE_422},
)
def update_image(
    image_id: uuid.UUID,
    req: Annotated[ImageUpdateRequest, Body(openapi_examples=UPDATE_EXAMPLES)],
    current_user: CatalogEditor,
    db: Db,
    storage: Storage,
    ctx: Ctx,
) -> ImageResponse:
    image = ImageAdminService.update(db, current_user, image_id, req, ctx, scope=PLATFORM)
    return image_response(image, storage)


@router.delete(
    "/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an image",
    description=(
        f"{PERMISSION_NOTE} Removes the image from the catalogue and retires its stored files "
        "(public source and private original) in the same transaction; the cleanup worker "
        "deletes them afterwards. Audited as 'catalog.image_delete'."
    ),
    responses={**GUARDED, **IMAGE_404, **DELETE_422},
)
def delete_image(image_id: uuid.UUID, current_user: CatalogEditor, db: Db, ctx: Ctx):
    ImageAdminService.delete(db, current_user, image_id, ctx, scope=PLATFORM)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
