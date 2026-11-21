from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR
from app.core.errors import NotFound, field_error
from app.db.session import get_db
from app.models.common import MAX_MONEY_RWF
from app.repositories.catalog import ProductFilters
from app.schemas.catalog import (
    CatalogBrand,
    CatalogCategory,
    CatalogFacets,
    CatalogProduct,
    CatalogProductDetail,
)
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.services import catalog as catalog_service

router = APIRouter(prefix="/catalog", tags=["catalog"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/categories", response_model=list[CatalogCategory])
def get_categories(session: DbSession) -> list[CatalogCategory]:
    """Active categories as a tree: top-level categories with nested `children`, each level
    in merchandising order. A category whose parent (or any ancestor) is inactive is hidden."""
    return catalog_service.category_tree(session)


@router.get("/brands", response_model=list[CatalogBrand])
def get_brands(session: DbSession) -> list[CatalogBrand]:
    """Active brands with `product_count`: the number of their public products (active
    products in an active category, as in the product listing)."""
    return catalog_service.brands_with_product_counts(session)


BrandSlug = Annotated[str, StringConstraints(min_length=1, max_length=180)]


def product_filters(
    category: Annotated[str | None, Query(min_length=1, max_length=180)] = None,
    brand: Annotated[
        list[BrandSlug] | None,
        Query(
            max_length=20,
            description="Brand slug; repeat it for several brands (any of them matches, at "
            "most 20)",
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=160,
            description="Full-text search in product name, model and brand name. Every word "
            "matches as a prefix ('iph' finds 'iPhone'; 'gx-1' finds 'GX-10'); web-search "
            'syntax is supported: "quoted phrase", or, -excluded. Input with no letters or '
            "digits matches nothing.",
        ),
    ] = None,
    min_price: Annotated[int | None, Query(ge=0, le=MAX_MONEY_RWF, description="Whole RWF")] = None,
    max_price: Annotated[int | None, Query(ge=0, le=MAX_MONEY_RWF, description="Whole RWF")] = None,
    in_stock: bool | None = None,
    featured: Annotated[
        bool | None,
        Query(
            description="true: only products picked for the Featured section; false: only "
            "the others"
        ),
    ] = None,
    on_sale: Annotated[
        bool | None,
        Query(
            description="true: only products with at least one active variant whose "
            "compare_at_price is above its price (the storefront's Deals); false: only the "
            "others"
        ),
    ] = None,
    min_rating: Annotated[
        int | None,
        Query(
            ge=1,
            le=5,
            description="Only products whose average approved-review rating is at least this "
            "many stars; products without reviews are left out",
        ),
    ] = None,
) -> ProductFilters:
    """The product list's filters, shared with /facets."""
    if min_price is not None and max_price is not None and min_price > max_price:
        raise field_error(
            ("query", "min_price"), "min_price must be less than or equal to max_price"
        )
    if q is not None:
        q = q.strip()
        if not q:
            raise field_error(("query", "q"), "q must contain non-whitespace characters")
    return ProductFilters(
        category_slug=category,
        brand_slugs=tuple(dict.fromkeys(brand or ())),
        search=q,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        featured=featured,
        on_sale=on_sale,
        min_rating=min_rating,
    )


Filters = Annotated[ProductFilters, Depends(product_filters)]


@router.get("/products", response_model=Page[CatalogProduct])
def get_products(
    session: DbSession,
    filters: Filters,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    sort_by: Annotated[
        Literal["name", "price", "newest", "bestselling", "top_rated"] | None,
        Query(
            description="name: product name; price: lowest active variant price (products "
            "without an active variant last); newest: creation time; bestselling: units in "
            "orders delivered in the last 90 days, then featured first, then newest; top_rated: "
            "average rating, then number of reviews, products without reviews last. Omitted: "
            "best match first when q is given, otherwise name."
        ),
    ] = None,
    sort_direction: Annotated[
        Literal["asc", "desc"] | None,
        Query(
            description="Direction of sort_by. Default: asc for name and price, desc for newest "
            "(newest first), bestselling (most sold first) and top_rated (best first). Ignored "
            "for best-match order. Product ID breaks ties ascending."
        ),
    ] = None,
) -> Page[CatalogProduct]:
    """Filter, search and sort public products; empty matches return an empty page with total
    zero."""
    products, total = catalog_service.list_products(
        session,
        filters=filters,
        page=page,
        size=size,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    return Page[CatalogProduct](
        items=[
            CatalogProduct.model_validate(product)
            for product in catalog_service.product_response_data(session, products)
        ],
        total=total,
        page=page,
        size=size,
    )


@router.get("/facets", response_model=CatalogFacets)
def get_facets(session: DbSession, filters: Filters) -> CatalogFacets:
    """Option counts for the listing's filter panel, for the same filters as /products: brands,
    price bands, availability and minimum rating. Each group ignores its own filter and applies
    the others, so a count is what /products would return with that option picked."""
    return CatalogFacets.model_validate(catalog_service.facets(session, filters))


@router.get(
    "/products/{slug}",
    response_model=CatalogProductDetail,
    responses={404: {**ERR, "description": "No public product with this slug"}},
)
def get_product(slug: str, session: DbSession) -> CatalogProductDetail:
    """Return a public product by slug; hidden and otherwise unavailable slugs return 404."""
    product = catalog_service.get_product(session, slug)
    if product is None:
        raise NotFound("Product not found", code="product_not_found")
    return CatalogProductDetail.model_validate(
        catalog_service.single_product_response_data(session, product)
    )
