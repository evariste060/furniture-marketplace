"""The approved seller's own catalogue: products, variants, images, stock, and the store's logo
and cover (ADR-014 phase 2).

Every route requires require_approved_seller. The store is always the caller's own, read from
the database on every request; no route takes a store id, and request bodies refuse store_id,
is_featured and other merchandising fields (422). A product, variant, image or SKU of another
store answers 404, exactly like one that does not exist. The rules (publication guard, slugs,
SKUs, stock) are those of the staff routes, applied by the same services with the seller's
CatalogScope.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, Header, Query, Response, UploadFile
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.image_admin import (
    IMAGE_404,
    ORDER_422,
    PRODUCT_404,
    SORT_ORDER_409,
    TOO_LARGE_413,
    UPDATE_422,
    UPDATE_EXAMPLES,
    UPLOAD_422,
    image_response,
)
from app.api.v1.endpoints.inventory import ADJUST_409, SKU_404, Sku
from app.api.v1.endpoints.product_admin import (
    SKU_409,
    SLUG_409,
    VARIANT_404,
    product_detail,
    product_list_items,
    product_response,
)
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import SellerContext, require_approved_seller
from app.core.errors import field_error
from app.core.request_context import RequestContext, get_request_context
from app.db.session import get_db
from app.integrations.media import MediaStorage, get_media_storage
from app.schemas.image_admin import AltText, ImageOrderRequest, ImageResponse, ImageUpdateRequest
from app.schemas.inventory import (
    IDEMPOTENCY_KEY_PATTERN,
    InventoryListItem,
    InventoryResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
)
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.product_admin import (
    ProductCreateRequest,
    ProductResponse,
    ProductStatus,
    ProductUpdateRequest,
    SellerProductCreateRequest,
    SellerProductUpdateRequest,
    StaffProductDetail,
    StaffProductListItem,
    VariantCreateRequest,
    VariantResponse,
    VariantUpdateRequest,
)
from app.schemas.stores import SellerStoreResponse
from app.services.catalog_scope import CatalogScope
from app.services.image_admin import ImageAdminService, processed_upload, read_upload
from app.services.inventory_admin import InventoryAdminService
from app.services.product_admin import ProductAdminService, get_staff_product, list_staff_products
from app.services.store_service import StoreImageField, StoreService, seller_response

router = APIRouter(prefix="/seller", tags=["Seller Catalogue"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Storage = Annotated[MediaStorage, Depends(get_media_storage)]
Seller = Annotated[SellerContext, Depends(require_approved_seller)]

GUARDED: ResponseMap = {
    **UNAUTHORIZED_401,
    403: {**ERR, "description": "account_inactive, or seller_not_approved (no approved store)"},
}
OWN_PRODUCT_404: ResponseMap = {
    404: {**ERR, "description": "product_not_found: no such product in your store"}
}
NOTE = "Approved sellers only; your own store's products."


def _scope(seller: SellerContext) -> CatalogScope:
    return CatalogScope.store(seller.store.id)


# ---- products --------------------------------------------------------------------------------
@router.get(
    "/products",
    response_model=Page[StaffProductListItem],
    summary="My products, drafts included",
    description=(
        f"{NOTE} Every status, most recently updated first, with the filters of the staff list: "
        "`status`, `has_images`, `category_id`, `brand_id`, `low_stock` and `q` (name, slug, "
        "model or SKU)."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_my_products(
    seller: Seller,
    db: Db,
    storage: Storage,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    product_status: Annotated[ProductStatus | None, Query(alias="status")] = None,
    has_images: Annotated[bool | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    brand_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    low_stock: Annotated[bool | None, Query()] = None,
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
        featured=None,
        q=q,
        page=page,
        size=size,
        scope=_scope(seller),
        low_stock=low_stock,
    )
    return Page[StaffProductListItem](
        items=product_list_items(db, storage, rows), total=total, page=page, size=size
    )


@router.get(
    "/products/{product_id}",
    response_model=StaffProductDetail,
    summary="One of my products",
    description=f"{NOTE} Every variant and image.",
    responses={**GUARDED, **OWN_PRODUCT_404, **VALIDATION_422},
)
def read_my_product(
    product_id: uuid.UUID, seller: Seller, db: Db, storage: Storage
) -> StaffProductDetail:
    return product_detail(get_staff_product(db, product_id, _scope(seller)), storage)


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Add a product to my store",
    description=(
        f"{NOTE} The product belongs to your store; store_id and is_featured are refused (422). "
        "status defaults to draft; a new product cannot be created active, because it has no "
        "images yet (409 product_has_no_images). The slug is generated from the name unless one "
        "is sent; slugs and SKUs are unique across the marketplace. category_id and brand_id "
        "must exist and be visible. Audited as 'catalog.product_create'."
    ),
    responses={**GUARDED, **SLUG_409, **VALIDATION_422},
)
def create_my_product(
    req: SellerProductCreateRequest, seller: Seller, db: Db, ctx: Ctx
) -> ProductResponse:
    product = ProductAdminService.create_product(
        db,
        seller.user,
        ProductCreateRequest.model_validate(req.model_dump()),
        ctx,
        scope=_scope(seller),
    )
    return product_response(product)


@router.patch(
    "/products/{product_id}",
    response_model=ProductResponse,
    summary="Update one of my products",
    description=(
        f"{NOTE} Partial update with the staff rules (activating needs a product image, 409 "
        "product_has_no_images); store_id and is_featured are refused (422). Audited as "
        "'catalog.product_update'."
    ),
    responses={**GUARDED, **OWN_PRODUCT_404, **SLUG_409, **VALIDATION_422},
)
def update_my_product(
    product_id: uuid.UUID, req: SellerProductUpdateRequest, seller: Seller, db: Db, ctx: Ctx
) -> ProductResponse:
    product = ProductAdminService.update_product(
        db,
        seller.user,
        product_id,
        ProductUpdateRequest.model_validate(req.model_dump(exclude_unset=True)),
        ctx,
        scope=_scope(seller),
    )
    return product_response(product)


@router.post(
    "/products/{product_id}/variants",
    response_model=VariantResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Add a variant (SKU) to one of my products",
    description=(
        f"{NOTE} Whole RWF prices. Stock is managed through /seller/inventory. Audited as "
        "'catalog.variant_create'."
    ),
    responses={**GUARDED, **OWN_PRODUCT_404, **SKU_409, **VALIDATION_422},
)
def create_my_variant(
    product_id: uuid.UUID, req: VariantCreateRequest, seller: Seller, db: Db, ctx: Ctx
) -> VariantResponse:
    variant = ProductAdminService.create_variant(
        db, seller.user, product_id, req, ctx, scope=_scope(seller)
    )
    return VariantResponse.model_validate(variant)


@router.patch(
    "/products/{product_id}/variants/{variant_id}",
    response_model=VariantResponse,
    summary="Update a variant of one of my products",
    description=f"{NOTE} Audited as 'catalog.variant_update', price changes included.",
    responses={**GUARDED, **VARIANT_404, **SKU_409, **VALIDATION_422},
)
def update_my_variant(
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
    req: VariantUpdateRequest,
    seller: Seller,
    db: Db,
    ctx: Ctx,
) -> VariantResponse:
    variant = ProductAdminService.update_variant(
        db, seller.user, product_id, variant_id, req, ctx, scope=_scope(seller)
    )
    return VariantResponse.model_validate(variant)


@router.delete(
    "/products/{product_id}/variants/{variant_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Deactivate a variant of one of my products",
    description=(
        f"{NOTE} The variant is kept (stock and orders reference it) and hidden. Audited as "
        "'catalog.variant_deactivate'."
    ),
    responses={**GUARDED, **VARIANT_404, **VALIDATION_422},
)
def deactivate_my_variant(
    product_id: uuid.UUID, variant_id: uuid.UUID, seller: Seller, db: Db, ctx: Ctx
):
    ProductAdminService.deactivate_variant(
        db, seller.user, product_id, variant_id, ctx, scope=_scope(seller)
    )
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


# ---- product images --------------------------------------------------------------------------
@router.post(
    "/products/{product_id}/images",
    response_model=ImageResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Upload an image of one of my products",
    description=(
        f"{NOTE} multipart/form-data with `file` (JPEG, PNG or WebP, at most 5 MB) and optional "
        "`variant_id` and `alt_text`, processed as staff uploads are. Audited as "
        "'catalog.image_upload'."
    ),
    responses={**GUARDED, **PRODUCT_404, **SORT_ORDER_409, **TOO_LARGE_413, **UPLOAD_422},
)
def upload_my_image(
    product_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")],
    seller: Seller,
    db: Db,
    ctx: Ctx,
    storage: Storage,
    variant_id: Annotated[
        uuid.UUID | None,
        Form(description="A variant of the same product; omit for a product-level image"),
    ] = None,
    alt_text: Annotated[AltText | None, Form(description="1-300 characters")] = None,
) -> ImageResponse:
    raw = read_upload(file.file)
    image = ImageAdminService.upload(
        db, storage, seller.user, product_id, raw, variant_id, alt_text, ctx, scope=_scope(seller)
    )
    return image_response(image, storage)


@router.put(
    "/products/{product_id}/images/order",
    response_model=list[ImageResponse],
    summary="Reorder the images of one of my products",
    description=(
        f"{NOTE} List every product image exactly once. Audited as 'catalog.image_reorder'."
    ),
    responses={**GUARDED, **PRODUCT_404, **SORT_ORDER_409, **ORDER_422},
)
def reorder_my_images(
    product_id: uuid.UUID,
    req: ImageOrderRequest,
    seller: Seller,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> list[ImageResponse]:
    images = ImageAdminService.reorder(db, seller.user, product_id, req, ctx, scope=_scope(seller))
    return [image_response(image, storage) for image in images]


@router.patch(
    "/images/{image_id}",
    response_model=ImageResponse,
    summary="Update an image of one of my products",
    description=f"{NOTE} alt_text, sort_order or variant_id. Audited as 'catalog.image_update'.",
    responses={**GUARDED, **IMAGE_404, **SORT_ORDER_409, **UPDATE_422},
)
def update_my_image(
    image_id: uuid.UUID,
    req: Annotated[ImageUpdateRequest, Body(openapi_examples=UPDATE_EXAMPLES)],
    seller: Seller,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> ImageResponse:
    image = ImageAdminService.update(db, seller.user, image_id, req, ctx, scope=_scope(seller))
    return image_response(image, storage)


@router.delete(
    "/images/{image_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an image of one of my products",
    description=(
        f"{NOTE} An active product keeps its last product image (409 last_product_image). "
        "Audited as 'catalog.image_delete'."
    ),
    responses={
        **GUARDED,
        **IMAGE_404,
        409: {**ERR, "description": "last_product_image"},
        **VALIDATION_422,
    },
)
def delete_my_image(image_id: uuid.UUID, seller: Seller, db: Db, ctx: Ctx):
    ImageAdminService.delete(db, seller.user, image_id, ctx, scope=_scope(seller))
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


# ---- stock -----------------------------------------------------------------------------------
@router.get(
    "/inventory",
    response_model=Page[InventoryListItem],
    summary="My stock list, with the low-stock filter",
    description=(
        f"{NOTE} One row per SKU of your store, ordered by SKU, with the staff figures. "
        "`low_stock` and `q` work as in GET /inventory."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_my_inventory(
    seller: Seller,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    low_stock: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
) -> Page[InventoryListItem]:
    if q is not None:
        q = q.strip()
        if not q:
            raise field_error(("query", "q"), "q must contain non-whitespace characters")
    items, total = InventoryAdminService.list_stock(
        db, low_stock=low_stock, q=q, page=page, size=size, scope=_scope(seller)
    )
    return Page[InventoryListItem](items=items, total=total, page=page, size=size)


@router.get(
    "/inventory/{sku}",
    response_model=InventoryResponse,
    summary="Stock figures for one of my SKUs",
    description=f"{NOTE} Another store's SKU is 404 like an unknown one.",
    responses={**GUARDED, **SKU_404, **VALIDATION_422},
)
def read_my_inventory(sku: Sku, seller: Seller, db: Db) -> InventoryResponse:
    return InventoryAdminService.get(db, sku, scope=_scope(seller))


@router.post(
    "/inventory/{sku}/adjustments",
    response_model=StockAdjustmentResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Record a physical stock change for one of my SKUs",
    description=(
        f"{NOTE} A receipt, adjustment or inspected return, with the rules, idempotency "
        "(`Idempotency-Key`, scoped to you) and audit of POST /inventory/{sku}/adjustments. "
        "Reservations and order commitments stay with the platform."
    ),
    responses={
        200: {"model": StockAdjustmentResponse, "description": "Replay of an applied key"},
        **GUARDED,
        **SKU_404,
        **ADJUST_409,
        **VALIDATION_422,
    },
)
def adjust_my_inventory(
    sku: Sku,
    req: StockAdjustmentRequest,
    response: Response,
    seller: Seller,
    db: Db,
    ctx: Ctx,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            pattern=IDEMPOTENCY_KEY_PATTERN,
            description="Unique key per intended change; reuse it only to retry that change",
        ),
    ],
) -> StockAdjustmentResponse:
    result = InventoryAdminService.adjust(
        db, seller.user, sku, req, idempotency_key, ctx, scope=_scope(seller)
    )
    if result.replayed:
        response.status_code = http_status.HTTP_200_OK
    return result


# ---- the store's logo and cover --------------------------------------------------------------
IMAGE_UPLOAD_RESPONSES: ResponseMap = {**GUARDED, **TOO_LARGE_413, **UPLOAD_422}


def _upload_store_image(
    field: StoreImageField, file: UploadFile, seller: SellerContext, db: Session, ctx, storage
) -> SellerStoreResponse:
    raw = read_upload(file.file)
    store = StoreService.set_image(
        db, storage, seller.user, seller.store.id, field, processed_upload(raw), len(raw), ctx
    )
    return seller_response(db, store)


@router.post(
    "/store/logo",
    response_model=SellerStoreResponse,
    summary="Upload or replace my store's logo",
    description=(
        "Approved sellers only. multipart/form-data with `file` (JPEG, PNG or WebP, at most "
        "5 MB). The replaced files are retired. Audited as 'store.logo_upload'."
    ),
    responses=IMAGE_UPLOAD_RESPONSES,
)
def upload_store_logo(
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")],
    seller: Seller,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> SellerStoreResponse:
    return _upload_store_image("logo", file, seller, db, ctx, storage)


@router.delete(
    "/store/logo",
    response_model=SellerStoreResponse,
    summary="Remove my store's logo",
    description=(
        "Approved sellers only. No logo: unchanged, not audited. Audited as 'store.logo_delete'."
    ),
    responses=GUARDED,
)
def delete_store_logo(seller: Seller, db: Db, ctx: Ctx) -> SellerStoreResponse:
    store = StoreService.remove_image(db, seller.user, seller.store.id, "logo", ctx)
    return seller_response(db, store)


@router.post(
    "/store/cover",
    response_model=SellerStoreResponse,
    summary="Upload or replace my store's cover image",
    description=(
        "Approved sellers only. multipart/form-data with `file` (JPEG, PNG or WebP, at most "
        "5 MB). The replaced files are retired. Audited as 'store.cover_upload'."
    ),
    responses=IMAGE_UPLOAD_RESPONSES,
)
def upload_store_cover(
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")],
    seller: Seller,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> SellerStoreResponse:
    return _upload_store_image("cover", file, seller, db, ctx, storage)


@router.delete(
    "/store/cover",
    response_model=SellerStoreResponse,
    summary="Remove my store's cover image",
    description=(
        "Approved sellers only. No cover: unchanged, not audited. Audited as 'store.cover_delete'."
    ),
    responses=GUARDED,
)
def delete_store_cover(seller: Seller, db: Db, ctx: Ctx) -> SellerStoreResponse:
    store = StoreService.remove_image(db, seller.user, seller.store.id, "cover", ctx)
    return seller_response(db, store)
