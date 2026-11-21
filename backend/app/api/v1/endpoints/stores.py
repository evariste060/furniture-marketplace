"""Public stores (ADR-014 decision 7): approved stores only, with their public product counts.

A store that is pending, rejected or suspended, or does not exist, is the same 404, and its
products are not public either (app.repositories.catalog). A store's products are listed with
GET /catalog/products?store=<slug>.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, VALIDATION_422
from app.db.session import get_db
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.stores import PublicStoreResponse
from app.services.store_service import StoreService, public_store_response

router = APIRouter(prefix="/stores", tags=["Stores"])

Db = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=Page[PublicStoreResponse],
    summary="Approved stores",
    description="Approved stores by name, each with the number of its public products.",
    responses=VALIDATION_422,
)
def list_stores(
    db: Db, page: PageNumber = 1, size: PageSize = DEFAULT_PAGE_SIZE
) -> Page[PublicStoreResponse]:
    rows, total = StoreService.public_page(db, page, size)
    return Page[PublicStoreResponse](
        items=[public_store_response(store, count) for store, count in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/{slug}",
    response_model=PublicStoreResponse,
    summary="One approved store",
    description="Any store that is not approved, or does not exist, is 404 store_not_found.",
    responses={404: {**ERR, "description": "store_not_found"}, **VALIDATION_422},
)
def read_store(slug: str, db: Db) -> PublicStoreResponse:
    store, count = StoreService.public_get(db, slug)
    return public_store_response(store, count)
