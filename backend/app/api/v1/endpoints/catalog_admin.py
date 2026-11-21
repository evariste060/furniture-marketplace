"""Staff category and brand management (module 5, RE-018).

Every route requires 'catalog:manage' (administrator). Rules and concurrency are in
app.services.catalog_admin. The public, read-only views are GET /catalog/categories and
GET /catalog/brands. Category images and brand logos (B1) are uploaded like product images
(ADR-009): validated with Pillow, the exact original kept privately, a sanitised public source
served at IMAGE_PUBLIC_BASE_URL.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.image_admin import TOO_LARGE_413, UPLOAD_422
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
from app.models import Brand, BrandCategory, Category, CategoryMenuBrand, Product
from app.models.identity import User
from app.schemas.catalog_admin import (
    BrandCreateRequest,
    BrandResponse,
    BrandUpdateRequest,
    CategoryCreateRequest,
    CategoryMenuBrandsRequest,
    CategoryOrderRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    StaffBrandItem,
    StaffBrandsResponse,
    StaffCategoriesResponse,
    StaffCategoryItem,
)
from app.services.catalog import brand_logo, category_image
from app.services.catalog_admin import CatalogAdminService
from app.services.image_admin import processed_upload, read_upload

router = APIRouter(prefix="/staff", tags=["Staff Catalogue"])

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
CATEGORY_404: ResponseMap = {404: {**ERR, "description": "No category with this ID"}}
BRAND_404: ResponseMap = {404: {**ERR, "description": "No brand with this ID"}}
CATEGORY_SAVE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "slug_taken: the slug is used by another category; category_cycle: "
        "the parent is the category itself or one of its subcategories",
    }
}
BRAND_SAVE_409: ResponseMap = {
    409: {**ERR, "description": "slug_taken: the slug is used by another brand"}
}
CATEGORY_ORDER_409: ResponseMap = {
    409: {
        **ERR,
        "description": "category_order_mismatch: category_ids is not exactly the categories "
        "under parent_id (one is missing, extra or under another parent); reload and retry",
    }
}
CATEGORY_DELETE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "category_in_use: products or subcategories still reference it "
        "(details has the counts); deactivate it instead",
    }
}
BRAND_DELETE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "brand_in_use: products still reference it (details has the count); "
        "deactivate it instead",
    }
}

CatalogManager = Annotated[User, Depends(require_permission(Permission.CATALOG_MANAGE))]
CatalogReader = Annotated[User, Depends(require_permission(Permission.CATALOG_READ))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Storage = Annotated[MediaStorage, Depends(get_media_storage)]
ImageFile = Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")]

PERMISSION_NOTE = "Requires 'catalog:manage' (administrator)."
UPLOAD_NOTE = (
    "multipart/form-data with `file` (JPEG, PNG or WebP, at most 5 MB), identified by decoding "
    "it, not by its name or declared type. The exact upload is kept privately; the public source "
    "keeps its format and is turned upright, stripped of metadata and scaled down only if its "
    "longest side is above 2400 px. Replaces the current one, whose files the worker deletes "
    "once the replacement is committed."
)


def _category_response(category: Category, storage: MediaStorage) -> CategoryResponse:
    response = CategoryResponse.model_validate(category)
    response.image = category_image(storage, category)
    return response


def _brand_response(brand: Brand, storage: MediaStorage) -> BrandResponse:
    response = BrandResponse.model_validate(brand)
    response.logo = brand_logo(storage, brand)
    return response


def _product_counts(db: Session, column: Any) -> dict[uuid.UUID, int]:
    rows = db.execute(select(column, func.count(Product.id)).group_by(column)).tuples()
    return {key: int(count) for key, count in rows if key is not None}


READ_NOTE = "Requires 'catalog:read' (administrator)."


@router.get(
    "/categories",
    response_model=StaffCategoriesResponse,
    summary="Every category, hidden ones included",
    description=(
        f"{READ_NOTE} Every category, active or not, with its image and the number of products "
        "directly in it (any status). Ordered by sort_order, then name; build the tree from "
        "parent_id. The public tree (GET /catalog/categories) shows active ones only."
    ),
    responses={**GUARDED},
)
def list_categories(_: CatalogReader, db: Db, storage: Storage) -> StaffCategoriesResponse:
    counts = _product_counts(db, Product.category_id)
    menu_brands: dict[uuid.UUID, list[uuid.UUID]] = {}
    for category_id, brand_id in db.execute(
        select(CategoryMenuBrand.category_id, CategoryMenuBrand.brand_id).order_by(
            CategoryMenuBrand.category_id, CategoryMenuBrand.position
        )
    ):
        menu_brands.setdefault(category_id, []).append(brand_id)
    categories = db.scalars(select(Category).order_by(Category.sort_order, Category.name))
    return StaffCategoriesResponse(
        items=[
            StaffCategoryItem(
                **_category_response(category, storage).model_dump(),
                product_count=counts.get(category.id, 0),
                menu_brand_ids=menu_brands.get(category.id, []),
            )
            for category in categories
        ]
    )


@router.put(
    "/categories/{category_id}/menu-brands",
    response_model=list[uuid.UUID],
    summary="Set the brands a main category's menu lists",
    description=(
        f"{PERMISSION_NOTE} Replaces the ordered list of brands the storefront's \"All "
        'Categories" menu shows for this main category (an empty list clears it; the menu then '
        "lists the brands of its products). Every brand must exist, and a brand not already "
        "listed must be active (422). A subcategory has no list (422). Returns the list. "
        "Audited as 'catalog.category_menu_brands' with the old and new lists; a request that "
        "changes nothing is not audited."
    ),
    responses={**GUARDED, **CATEGORY_404, **VALIDATION_422},
)
def set_category_menu_brands(
    category_id: uuid.UUID,
    req: CategoryMenuBrandsRequest,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
) -> list[uuid.UUID]:
    return CatalogAdminService.set_menu_brands(db, current_user, category_id, req, ctx)


@router.get(
    "/brands",
    response_model=StaffBrandsResponse,
    summary="Every brand, hidden ones included",
    description=(
        f"{READ_NOTE} Every brand, active or not, with its logo and number of products (any "
        "status), by name. The public list (GET /catalog/brands) shows active ones only."
    ),
    responses={**GUARDED},
)
def list_brands(_: CatalogReader, db: Db, storage: Storage) -> StaffBrandsResponse:
    counts = _product_counts(db, Product.brand_id)
    brands = db.scalars(select(Brand).order_by(Brand.name)).all()
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for brand_id, category_id in db.execute(
        select(BrandCategory.brand_id, BrandCategory.category_id)
        .join(Category, Category.id == BrandCategory.category_id)
        .order_by(Category.sort_order, Category.name)
    ):
        links.setdefault(brand_id, []).append(category_id)
    return StaffBrandsResponse(
        items=[
            StaffBrandItem(
                **_brand_response(brand, storage).model_dump(),
                product_count=counts.get(brand.id, 0),
                category_ids=links.get(brand.id, []),
            )
            for brand in brands
        ]
    )


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    description=(
        f"{PERMISSION_NOTE} The slug is generated from the name unless one is sent. "
        "parent_id must be an existing main category: the tree has two levels, main category "
        "and subcategory (422 otherwise). Audited as 'catalog.category_create'."
    ),
    responses={**GUARDED, **CATEGORY_SAVE_409, **VALIDATION_422},
)
def create_category(
    req: CategoryCreateRequest, current_user: CatalogManager, db: Db, ctx: Ctx, storage: Storage
) -> CategoryResponse:
    category = CatalogAdminService.create_category(db, current_user, req, ctx)
    return _category_response(category, storage)


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    summary="Update a category",
    description=(
        f"{PERMISSION_NOTE} Partial update of name, slug, parent_id (null = top level; a "
        "parent must be a main category, and a category with subcategories cannot get one: "
        "422), "
        "sort_order, description (null clears it), is_active (false deactivates it and hides "
        "its subcategories from the public tree) and spotlight_product_id (a product in this "
        "category or a subcategory, 422 otherwise; null clears it). A rename keeps the slug. "
        "Audited as 'catalog.category_update' with the old and new values; a request that "
        "changes nothing is not audited."
    ),
    responses={**GUARDED, **CATEGORY_404, **CATEGORY_SAVE_409, **VALIDATION_422},
)
def update_category(
    category_id: uuid.UUID,
    req: CategoryUpdateRequest,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> CategoryResponse:
    category = CatalogAdminService.update_category(db, current_user, category_id, req, ctx)
    return _category_response(category, storage)


@router.put(
    "/categories/order",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Reorder the categories under one parent",
    description=(
        f"{PERMISSION_NOTE} Sets sort_order to 1, 2, 3, ... for the categories directly under "
        "parent_id (null: the main categories), in the order of category_ids, which must list "
        "every one of them, hidden ones included, exactly once (409 otherwise). Audited once as "
        "'catalog.category_reorder' with the positions that changed; an order that changes "
        "nothing is not audited."
    ),
    responses={**GUARDED, **CATEGORY_ORDER_409, **VALIDATION_422},
)
def reorder_categories(req: CategoryOrderRequest, current_user: CatalogManager, db: Db, ctx: Ctx):
    CatalogAdminService.reorder_categories(db, current_user, req, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an unused category",
    description=(
        f"{PERMISSION_NOTE} Only a category with no products and no subcategories can be "
        "deleted; otherwise 409 (deactivate it with is_active=false). Its image files are then "
        "retired (the worker deletes them). Audited as 'catalog.category_delete'."
    ),
    responses={**GUARDED, **CATEGORY_404, **CATEGORY_DELETE_409, **VALIDATION_422},
)
def delete_category(category_id: uuid.UUID, current_user: CatalogManager, db: Db, ctx: Ctx):
    CatalogAdminService.delete_category(db, current_user, category_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/categories/{category_id}/image",
    response_model=CategoryResponse,
    summary="Upload or replace a category image",
    description=f"{PERMISSION_NOTE} {UPLOAD_NOTE} Audited as 'catalog.category_image_upload'.",
    responses={**GUARDED, **CATEGORY_404, **TOO_LARGE_413, **UPLOAD_422},
)
def upload_category_image(
    category_id: uuid.UUID,
    file: ImageFile,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> CategoryResponse:
    raw = read_upload(file.file)
    category = CatalogAdminService.set_category_image(
        db, storage, current_user, category_id, processed_upload(raw), len(raw), ctx
    )
    return _category_response(category, storage)


@router.delete(
    "/categories/{category_id}/image",
    response_model=CategoryResponse,
    summary="Remove a category image",
    description=(
        f"{PERMISSION_NOTE} Clears the image and retires its files (the worker deletes them). "
        "A category without an image is returned unchanged and not audited. Audited as "
        "'catalog.category_image_delete'."
    ),
    responses={**GUARDED, **CATEGORY_404, **VALIDATION_422},
)
def delete_category_image(
    category_id: uuid.UUID, current_user: CatalogManager, db: Db, ctx: Ctx, storage: Storage
) -> CategoryResponse:
    category = CatalogAdminService.remove_category_image(db, current_user, category_id, ctx)
    return _category_response(category, storage)


@router.post(
    "/brands",
    response_model=BrandResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a brand",
    description=(
        f"{PERMISSION_NOTE} The slug is generated from the name unless one is sent. "
        "Audited as 'catalog.brand_create'."
    ),
    responses={**GUARDED, **BRAND_SAVE_409, **VALIDATION_422},
)
def create_brand(
    req: BrandCreateRequest, current_user: CatalogManager, db: Db, ctx: Ctx, storage: Storage
) -> BrandResponse:
    return _brand_response(CatalogAdminService.create_brand(db, current_user, req, ctx), storage)


@router.patch(
    "/brands/{brand_id}",
    response_model=BrandResponse,
    summary="Update a brand",
    description=(
        f"{PERMISSION_NOTE} Partial update of name, slug and is_active (false deactivates it "
        "and hides its products). A rename keeps the slug. Audited as 'catalog.brand_update' "
        "with the old and new values; a request that changes nothing is not audited."
    ),
    responses={**GUARDED, **BRAND_404, **BRAND_SAVE_409, **VALIDATION_422},
)
def update_brand(
    brand_id: uuid.UUID,
    req: BrandUpdateRequest,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> BrandResponse:
    brand = CatalogAdminService.update_brand(db, current_user, brand_id, req, ctx)
    return _brand_response(brand, storage)


@router.delete(
    "/brands/{brand_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an unused brand",
    description=(
        f"{PERMISSION_NOTE} Only a brand with no products can be deleted; otherwise 409 "
        "(deactivate it with is_active=false). Its logo files are then retired (the worker "
        "deletes them). Audited as 'catalog.brand_delete'."
    ),
    responses={**GUARDED, **BRAND_404, **BRAND_DELETE_409, **VALIDATION_422},
)
def delete_brand(brand_id: uuid.UUID, current_user: CatalogManager, db: Db, ctx: Ctx):
    CatalogAdminService.delete_brand(db, current_user, brand_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/brands/{brand_id}/logo",
    response_model=BrandResponse,
    summary="Upload or replace a brand logo",
    description=f"{PERMISSION_NOTE} {UPLOAD_NOTE} Audited as 'catalog.brand_logo_upload'.",
    responses={**GUARDED, **BRAND_404, **TOO_LARGE_413, **UPLOAD_422},
)
def upload_brand_logo(
    brand_id: uuid.UUID,
    file: ImageFile,
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> BrandResponse:
    raw = read_upload(file.file)
    brand = CatalogAdminService.set_brand_logo(
        db, storage, current_user, brand_id, processed_upload(raw), len(raw), ctx
    )
    return _brand_response(brand, storage)


@router.delete(
    "/brands/{brand_id}/logo",
    response_model=BrandResponse,
    summary="Remove a brand logo",
    description=(
        f"{PERMISSION_NOTE} Clears the logo and retires its files (the worker deletes them). "
        "A brand without a logo is returned unchanged and not audited. Audited as "
        "'catalog.brand_logo_delete'."
    ),
    responses={**GUARDED, **BRAND_404, **VALIDATION_422},
)
def delete_brand_logo(
    brand_id: uuid.UUID, current_user: CatalogManager, db: Db, ctx: Ctx, storage: Storage
) -> BrandResponse:
    brand = CatalogAdminService.remove_brand_logo(db, current_user, brand_id, ctx)
    return _brand_response(brand, storage)
