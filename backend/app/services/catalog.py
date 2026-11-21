from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.integrations.media import MediaStorage, get_media_storage
from app.models import Brand, Category, Product, ProductImage
from app.repositories import catalog as catalog_repository
from app.repositories.catalog import CatalogSortDirection, CatalogSortField, ProductFilters
from app.schemas.catalog import CatalogBrand, CatalogCategory, CatalogReference
from app.schemas.images import PublicImage
from app.services.media_registry import public_image

StockStatus = Literal["in_stock", "low_stock", "out_of_stock"]


def stock_status(available: int, low_stock_threshold: int) -> StockStatus:
    """Public stock band for a variant; the exact available quantity is never exposed."""
    if available <= 0:
        return "out_of_stock"
    if low_stock_threshold > 0 and available <= low_stock_threshold:
        return "low_stock"
    return "in_stock"


def category_tree(session: Session) -> list[CatalogCategory]:
    """Active categories nested under their parents, each level in merchandising order.

    spotlight_product_slug is the staff pick for the home page spotlight, shown only while that
    product is public and still in the category's subtree.

    A category is shown only when it and every ancestor are active: deactivating a category
    hides its whole subtree from this tree.
    """
    categories = catalog_repository.list_active_categories(session)  # already ordered
    storage = get_media_storage()
    nodes = {
        c.id: CatalogCategory(
            id=c.id,
            name=c.name,
            slug=c.slug,
            sort_order=c.sort_order,
            parent_id=c.parent_id,
            description=c.description,
            image=category_image(storage, c),
        )
        for c in categories
    }
    for category_id, brands in catalog_repository.active_menu_brands(session).items():
        if category_id in nodes:
            nodes[category_id].menu_brands = [CatalogReference.model_validate(b) for b in brands]
    parents = {c.id: c.parent_id for c in categories}
    picks = {c.id: c.spotlight_product_id for c in categories if c.spotlight_product_id}
    for category_id, slug in catalog_repository.public_spotlight_slugs(
        session, picks, parents
    ).items():
        nodes[category_id].spotlight_product_slug = slug
    roots: list[CatalogCategory] = []
    for category in categories:
        node = nodes[category.id]
        if category.parent_id is None:
            roots.append(node)
        elif category.parent_id in nodes:
            nodes[category.parent_id].children.append(node)
    return roots


def category_image(storage: MediaStorage, category: Category) -> PublicImage | None:
    if category.image_media is None:
        return None
    return PublicImage.model_validate(public_image(storage, category.image_media, category.name, 0))


def brand_logo(storage: MediaStorage, brand: Brand) -> PublicImage | None:
    if brand.logo_media is None:
        return None
    return PublicImage.model_validate(public_image(storage, brand.logo_media, brand.name, 0))


def brands_with_product_counts(session: Session) -> list[CatalogBrand]:
    storage = get_media_storage()
    return [
        CatalogBrand(
            id=brand.id,
            name=brand.name,
            slug=brand.slug,
            product_count=count,
            logo=brand_logo(storage, brand),
        )
        for brand, count in catalog_repository.list_active_brands_with_product_counts(session)
    ]


def list_products(
    session: Session,
    *,
    filters: ProductFilters,
    page: int,
    size: int,
    sort_by: CatalogSortField | None,
    sort_direction: CatalogSortDirection | None,
) -> tuple[list[Product], int]:
    return catalog_repository.list_public_products(
        session,
        filters=filters,
        page=page,
        size=size,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def facets(session: Session, filters: ProductFilters) -> dict[str, Any]:
    return catalog_repository.catalogue_facets(session, filters)


def get_product(session: Session, slug: str) -> Product | None:
    return catalog_repository.get_public_product_by_slug(session, slug)


def product_response_data(session: Session, products: list[Product]) -> list[dict[str, Any]]:
    variants = [variant for product in products for variant in product.variants]
    available = catalog_repository.get_available_quantities(
        session, [variant.id for variant in variants]
    )
    return [product_to_data(product, available) for product in products]


def single_product_response_data(session: Session, product: Product) -> dict[str, Any]:
    available = catalog_repository.get_available_quantities(
        session, [variant.id for variant in product.variants]
    )
    data = product_to_data(product, available)
    data["rating"]["distribution"] = [
        {"stars": stars, "count": getattr(product, f"rating_{stars}_count")}
        for stars in (5, 4, 3, 2, 1)
    ]
    return data


def rating_data(product: Product) -> dict[str, Any]:
    """Approved-review totals (module 20); average null while there are none."""
    average = product.rating_average
    return {
        "average": float(average) if average is not None and product.rating_count else None,
        "count": product.rating_count,
    }


def product_to_data(product: Product, available: dict[UUID, int]) -> dict[str, Any]:
    storage = get_media_storage()
    return {
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "is_featured": product.is_featured,
        "created_at": product.created_at,
        "model": product.model,
        "description": product.description,
        "specifications": product.specifications,
        "warranty_text": product.warranty_text,
        "category": product.category,
        "brand": product.brand,
        "images": [
            product_image_data(storage, image, product) for image in _ordered(product.images)
        ],
        "variants": [
            {
                "id": variant.id,
                "sku": variant.sku,
                "name": variant.name,
                "attributes": variant.attributes,
                "price": variant.price,
                "compare_at_price": variant.compare_at_price,
                "currency_code": variant.currency_code,
                "stock_status": stock_status(
                    available.get(variant.id, 0), variant.low_stock_threshold
                ),
                "in_stock": available.get(variant.id, 0) > 0,
                "images": [
                    product_image_data(storage, image, product)
                    for image in _ordered(variant.images)
                ],
            }
            for variant in sorted(product.variants, key=lambda item: (item.name, str(item.id)))
        ],
        "rating": rating_data(product),
    }


def _ordered(images: list[ProductImage]) -> list[ProductImage]:
    return sorted(images, key=lambda image: (image.sort_order, str(image.id)))


def product_image_data(
    storage: MediaStorage, image: ProductImage, product: Product
) -> dict[str, Any]:
    """The public image object of a product image; alt falls back to the product name."""
    return public_image(
        storage, image.public_media, image.alt_text or product.name, image.sort_order
    )
