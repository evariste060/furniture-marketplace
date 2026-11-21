"""Staff product and variant management (module 6), and the staff product list and detail.

Changes require 'catalog:manage' (administrator). The list and detail require
'catalog:read' (administrator) and show drafts too. Rules and
concurrency are in app.services.product_admin. The public, read-only views are
GET /catalog/products and GET /catalog/products/{slug}.

Stores (ADR-014 phase 2; SC-05): staff act on every store (CatalogScope.platform()) and moderate
products (view, edit, hide, archive); they do not create them, so POST /staff/products answers
409 staff_product_creation_disabled. Sellers manage their own products under /seller/products.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.image_admin import image_response
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import require_permission
from app.core.errors import field_error
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.integrations.media import MediaStorage, get_media_storage
from app.models import Product
from app.models.identity import User
from app.schemas.catalog import CatalogReference, StoreReference
from app.schemas.images import PublicImage
from app.schemas.jobs import JobResponse
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.product_admin import (
    BulkActivateRequest,
    BulkActivateResponse,
    BulkActivateResult,
    PhotoFileName,
    ProductCreateRequest,
    ProductResponse,
    ProductStatus,
    ProductUpdateRequest,
    StaffProductDetail,
    StaffProductListItem,
    VariantCreateRequest,
    VariantResponse,
    VariantUpdateRequest,
)
from app.services.bulk_images import (
    MAX_FILES,
    Upload,
    start_bulk_upload,
)
from app.services.catalog import product_image_data
from app.services.catalog_scope import CatalogScope
from app.services.product_admin import (
    ProductAdminService,
    ProductStock,
    bulk_activate,
    get_staff_product,
    list_staff_products,
    next_photo_file_name,
    photo_file_name,
    product_stock,
    sorted_variants,
)

router = APIRouter(prefix="/staff", tags=["Staff Catalogue"])

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
PRODUCT_404: ResponseMap = {404: {**ERR, "description": "No product with this ID"}}
VARIANT_404: ResponseMap = {
    404: {**ERR, "description": "No product with this ID, or no such variant on it"}
}
SLUG_409: ResponseMap = {
    409: {**ERR, "description": "slug_taken: the slug is used by another product"}
}
SKU_409: ResponseMap = {
    409: {**ERR, "description": "sku_taken: the SKU is used by another variant"}
}

CatalogManager = Annotated[User, Depends(require_permission(Permission.CATALOG_MANAGE))]
CatalogReader = Annotated[User, Depends(require_permission(Permission.CATALOG_READ))]
Storage = Annotated[MediaStorage, Depends(get_media_storage)]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]

PERMISSION_NOTE = "Requires 'catalog:manage' (administrator)."
PLATFORM = CatalogScope.platform()
STAFF_CREATE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "staff_product_creation_disabled: administrators moderate products but do "
        "not create them; sellers add products to their own store (SC-05)",
    }
}


def _stock_fields(stock: ProductStock | None) -> dict[str, Any]:
    if stock is None:  # no active variant
        return {}
    return {
        "sku": stock.sku,
        "price": stock.price,
        "available_quantity": stock.available_quantity,
        "has_low_stock": stock.has_low_stock,
    }


def product_response(product: Product) -> ProductResponse:
    return ProductResponse.model_validate(
        {
            **{f: getattr(product, f) for f in ProductResponse.model_fields if f != "variants"},
            "variants": [VariantResponse.model_validate(v) for v in sorted_variants(product)],
        }
    )


@router.get(
    "/products",
    response_model=Page[StaffProductListItem],
    summary="Staff product list, drafts included",
    description=(
        "Requires 'catalog:read' (administrator). Every product "
        "whatever its status, most recently updated first. Filters: `status`; `has_images` "
        "(product images only, variant images not counted), e.g. `status=active&has_images=false` "
        "for active products without a photo or `status=draft&has_images=true` for drafts ready "
        "to activate; `category_id`, `brand_id`, `featured`; `low_stock=true` for products with "
        "an active variant at or below its low-stock threshold; `q` matches a case-insensitive "
        "substring of the name, slug, model or any variant SKU. Each row has the lowest active "
        "price, the first active SKU and the units available across active variants. "
        "`store_id` lists one store's products; each row names its store (ADR-014)."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_products(
    current_user: CatalogReader,
    db: Db,
    storage: Storage,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    product_status: Annotated[ProductStatus | None, Query(alias="status")] = None,
    has_images: Annotated[bool | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    brand_id: Annotated[uuid.UUID | None, Query()] = None,
    featured: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    low_stock: Annotated[bool | None, Query()] = None,
    store_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[StaffProductListItem]:
    if q is not None:
        q = q.strip()
        if not q:
            raise field_error(("query", "q"), "q must contain non-whitespace characters")
    rows, total = list_staff_products(
        db,
        status=product_status,
        has_images=has_images,
        category_id=category_id,
        brand_id=brand_id,
        featured=featured,
        q=q,
        page=page,
        size=size,
        scope=PLATFORM,
        low_stock=low_stock,
        store_id=store_id,
    )
    return Page[StaffProductListItem](
        items=product_list_items(db, storage, rows), total=total, page=page, size=size
    )


def product_list_items(
    db: Session, storage: MediaStorage, rows: list[tuple[Product, int, int]]
) -> list[StaffProductListItem]:
    """The rows of the staff product list, also used by the seller's own list (ADR-014)."""
    stock = product_stock(db, [product.id for product, _, _ in rows])
    return [
        StaffProductListItem(
            id=product.id,
            name=product.name,
            slug=product.slug,
            status=product.status,  # type: ignore[arg-type]
            is_featured=product.is_featured,
            category=CatalogReference.model_validate(product.category),
            brand=CatalogReference.model_validate(product.brand) if product.brand else None,
            store=StoreReference.model_validate(product.store),
            variant_count=variants,
            image_count=images,
            image=(
                PublicImage.model_validate(product_image_data(storage, product.images[0], product))
                if product.images
                else None
            ),
            next_photo_file_name=next_photo_file_name(product),
            **_stock_fields(stock.get(product.id)),
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
        for product, variants, images in rows
    ]


@router.get(
    "/products/{product_id}",
    response_model=StaffProductDetail,
    summary="Staff product detail, drafts included",
    description=(
        "Requires 'catalog:read' (administrator). The product "
        "whatever its status, every variant, and every image (variant images included) in "
        "display order."
    ),
    responses={**GUARDED, **PRODUCT_404, **VALIDATION_422},
)
def get_product(
    product_id: uuid.UUID, current_user: CatalogReader, db: Db, storage: Storage
) -> StaffProductDetail:
    return product_detail(get_staff_product(db, product_id, PLATFORM), storage)


def product_detail(product: Product, storage: MediaStorage) -> StaffProductDetail:
    """The staff product detail, also used by the seller's own detail (ADR-014)."""
    images = sorted(product.images, key=lambda image: (image.sort_order, str(image.id)))
    return StaffProductDetail.model_validate(
        {
            **product_response(product).model_dump(),
            "images": [image_response(image, storage) for image in images],
            "photo_file_names": [
                PhotoFileName(
                    image_id=image.id,
                    position=image.sort_order + 1,
                    file_name=photo_file_name(product.slug, image.sort_order),
                )
                for image in images
                if image.variant_id is None
            ],
            "next_photo_file_name": next_photo_file_name(product),
        }
    )


BULK_UPLOAD_NOTE = (
    "Up to 20 files and 100 MB per request (send more as further batches). Name each file "
    "`<product-slug>.jpg` for position 1 or `<product-slug>__<n>.jpg` for position n (1–99); "
    "jpg, jpeg, png or webp, matched case-insensitively. The staff product list and detail show "
    "the expected names. A file over 5 MB, or more than 20 files, rejects the whole request "
    "before anything is stored (413, 422); 507 when the upload area or disk is full. Names "
    "that match no product (`unknown_slug`), are malformed (`invalid_filename`) or name the "
    "same position twice in one request (`duplicate_position`, neither applied) fail at once. "
    "The rest are stored and processed by the worker (python -m app.worker): each file replaces "
    "the image at its position (or adds one there), or is `unchanged` when it is the same "
    "file. Poll GET /staff/jobs/{id}. Audited per image as 'catalog.image_bulk_add' or "
    "'catalog.image_bulk_replace' and per job as 'catalog.image_bulk_complete'."
)


@router.post(
    "/products/bulk-images",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk upload product images (processed in the background)",
    description=f"{PERMISSION_NOTE} {BULK_UPLOAD_NOTE}",
    responses={
        **GUARDED,
        413: {
            **ERR,
            "description": "file_too_large: a file is over 5 MB, or the request over 100 MB",
        },
        507: {**ERR, "description": "insufficient_storage: the upload area or disk is full"},
        **VALIDATION_422,
    },
)
def bulk_upload_images(
    files: Annotated[
        list[UploadFile], File(description=f"1–{MAX_FILES} image files named by product slug")
    ],
    current_user: CatalogManager,
    db: Db,
    storage: Storage,
) -> JobResponse:
    uploads = [Upload(file.filename or "", file.file, file.size) for file in files]
    return JobResponse.from_job(start_bulk_upload(db, storage, current_user, uploads))


@router.post(
    "/products/bulk-activate",
    response_model=BulkActivateResponse,
    summary="Activate several products at once",
    description=(
        f"{PERMISSION_NOTE} Up to 200 product IDs. Each product goes through the publication "
        "guard: `activated`, `skipped_no_images` (no product image yet), `already_active` or "
        "`not_found`. One 'catalog.product_update' audit record per activated product."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def bulk_activate_products(
    req: BulkActivateRequest, current_user: CatalogManager, db: Db, ctx: Ctx
) -> BulkActivateResponse:
    outcomes = bulk_activate(db, current_user, req.product_ids, ctx, scope=PLATFORM)
    counts = {name: 0 for name in ("activated", "skipped_no_images", "already_active", "not_found")}
    for _, outcome in outcomes:
        counts[outcome] += 1
    return BulkActivateResponse(
        results=[
            BulkActivateResult(product_id=product_id, outcome=outcome)  # type: ignore[arg-type]
            for product_id, outcome in outcomes
        ],
        **counts,
    )


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product (disabled for staff: 409)",
    description=(
        f"{PERMISSION_NOTE} Always 409 staff_product_creation_disabled (SC-05, ADR-014): every "
        "product belongs to a seller's store and sellers create their own products "
        "(POST /seller/products). Administrators view, edit, hide and archive products of every "
        "store through the other routes. Nothing is created or audited."
    ),
    responses={**GUARDED, **STAFF_CREATE_409, **VALIDATION_422},
)
def create_product(
    req: ProductCreateRequest, current_user: CatalogManager, db: Db, ctx: Ctx
) -> ProductResponse:
    product = ProductAdminService.create_product(db, current_user, req, ctx, scope=PLATFORM)
    return product_response(product)  # pragma: no cover - the platform scope always raises


@router.patch(
    "/products/{product_id}",
    response_model=ProductResponse,
    summary="Update a product",
    description=(
        f"{PERMISSION_NOTE} Partial update of the product fields and status (draft, active, "
        "hidden, archived). Activating needs at least one product image (409 "
        "product_has_no_images). Only active products in an active category, with an active "
        "brand or none, are public. A rename keeps the slug. Audited as "
        "'catalog.product_update' with the old and new values; a request that changes nothing "
        "is not audited."
    ),
    responses={**GUARDED, **PRODUCT_404, **SLUG_409, **VALIDATION_422},
)
def update_product(
    product_id: uuid.UUID,
    req: ProductUpdateRequest,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
) -> ProductResponse:
    product = ProductAdminService.update_product(
        db, current_user, product_id, req, ctx, scope=PLATFORM
    )
    return product_response(product)


@router.post(
    "/products/{product_id}/variants",
    response_model=VariantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a variant (SKU) to a product",
    description=(
        f"{PERMISSION_NOTE} price and compare_at_price are whole RWF (compare_at_price is display "
        "only). Stock is managed through the inventory endpoints. "
        "Audited as 'catalog.variant_create'."
    ),
    responses={**GUARDED, **PRODUCT_404, **SKU_409, **VALIDATION_422},
)
def create_variant(
    product_id: uuid.UUID,
    req: VariantCreateRequest,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
) -> VariantResponse:
    variant = ProductAdminService.create_variant(
        db, current_user, product_id, req, ctx, scope=PLATFORM
    )
    return VariantResponse.model_validate(variant)


@router.patch(
    "/products/{product_id}/variants/{variant_id}",
    response_model=VariantResponse,
    summary="Update a variant",
    description=(
        f"{PERMISSION_NOTE} Partial update; is_active=true reactivates a deactivated variant. "
        "Audited as 'catalog.variant_update' with the old and new values, including price."
    ),
    responses={**GUARDED, **VARIANT_404, **SKU_409, **VALIDATION_422},
)
def update_variant(
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
    req: VariantUpdateRequest,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
) -> VariantResponse:
    variant = ProductAdminService.update_variant(
        db, current_user, product_id, variant_id, req, ctx, scope=PLATFORM
    )
    return VariantResponse.model_validate(variant)


@router.delete(
    "/products/{product_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Deactivate a variant",
    description=(
        f"{PERMISSION_NOTE} The variant is not removed: stock and orders reference it. It is "
        "set to is_active=false and hidden from the public catalogue. Repeating it is a no-op. "
        "Audited as 'catalog.variant_deactivate'."
    ),
    responses={**GUARDED, **VARIANT_404, **VALIDATION_422},
)
def delete_variant(
    product_id: uuid.UUID, variant_id: uuid.UUID, current_user: CatalogManager, db: Db, ctx: Ctx
):
    ProductAdminService.deactivate_variant(
        db, current_user, product_id, variant_id, ctx, scope=PLATFORM
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
