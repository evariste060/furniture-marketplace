"""Customer wishlist (module 21, scope change SC-01 approved by the project owner 2026-10-27)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import AUTHENTICATED, ERR, NOT_FOUND_404, VALIDATION_422, ResponseMap
from app.core.dependencies import get_current_user
from app.core.errors import Forbidden
from app.core.roles import Role, effective_roles
from app.db.session import get_db
from app.models.identity import User
from app.schemas.catalog import CatalogProduct
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.wishlist import (
    WishlistChangeResponse,
    WishlistIdsResponse,
    WishlistItemResponse,
)
from app.services.wishlist_service import WishlistService

router = APIRouter(prefix="/customers/me/wishlist", tags=["Wishlist"])

CUSTOMER_ONLY: ResponseMap = {
    403: {**ERR, "description": "customer_only: staff accounts have no wishlist; or inactive"}
}
FULL_409: ResponseMap = {
    409: {**ERR, "description": "wishlist_full: the wishlist already holds 200 products"}
}


def current_customer(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Customers only: any staff-flagged account is refused, even one without a role."""
    if user.is_staff or effective_roles(user) != {Role.CUSTOMER.value}:
        raise Forbidden("The wishlist is for customer accounts only.", code="customer_only")
    return user


Customer = Annotated[User, Depends(current_customer)]
Db = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=Page[WishlistItemResponse],
    summary="List saved products",
    description=(
        "Saved products, newest first. `available` is false for a product that is no longer "
        "sold: it keeps its name, slug and first image, `product` is null, and it can only be "
        "removed."
    ),
    responses={**AUTHENTICATED, **CUSTOMER_ONLY, **VALIDATION_422},
)
def list_wishlist(
    customer: Customer, db: Db, page: PageNumber = 1, size: PageSize = DEFAULT_PAGE_SIZE
) -> Page[WishlistItemResponse]:
    items, total = WishlistService.page(db, customer, page, size)
    return Page[WishlistItemResponse](
        items=[
            WishlistItemResponse.model_validate(
                {
                    **item,
                    "product": CatalogProduct.model_validate(item["product"])
                    if item["product"] is not None
                    else None,
                }
            )
            for item in items
        ],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/ids",
    response_model=WishlistIdsResponse,
    summary="IDs of every saved product",
    description="For the storefront's hearts and the header count. Never cached publicly.",
    responses={**AUTHENTICATED, **CUSTOMER_ONLY},
)
def wishlist_ids(customer: Customer, db: Db) -> WishlistIdsResponse:
    ids = WishlistService.ids(db, customer)
    return WishlistIdsResponse(product_ids=ids, count=len(ids))


@router.put(
    "/{product_id}",
    response_model=WishlistChangeResponse,
    status_code=status.HTTP_200_OK,
    summary="Save a product (idempotent)",
    description=(
        "Saves a product that is sold right now. Saving it again changes nothing. A product "
        "that is unknown or not sold returns 404 product_not_found."
    ),
    responses={**AUTHENTICATED, **CUSTOMER_ONLY, **NOT_FOUND_404, **FULL_409, **VALIDATION_422},
)
def add_to_wishlist(product_id: uuid.UUID, customer: Customer, db: Db) -> WishlistChangeResponse:
    count = WishlistService.add(db, customer, product_id)
    return WishlistChangeResponse(product_id=product_id, in_wishlist=True, count=count)


@router.delete(
    "/{product_id}",
    response_model=WishlistChangeResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a saved product (idempotent)",
    description="Removing a product that is not saved changes nothing.",
    responses={**AUTHENTICATED, **CUSTOMER_ONLY, **VALIDATION_422},
)
def remove_from_wishlist(
    product_id: uuid.UUID, customer: Customer, db: Db
) -> WishlistChangeResponse:
    count = WishlistService.remove(db, customer, product_id)
    return WishlistChangeResponse(product_id=product_id, in_wishlist=False, count=count)
