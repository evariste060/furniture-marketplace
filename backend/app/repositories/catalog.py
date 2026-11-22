from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Integer, Text, cast, func, or_, select, type_coerce
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from app.core.furniture import ATTRIBUTES, FILTER_ATTRIBUTES
from app.models import (
    Brand,
    Category,
    CategoryMenuBrand,
    InventoryBalance,
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    ProductImage,
    ProductVariant,
    StockReservation,
)
from app.models.marketplace import Store
from app.repositories.category_tree import category_roots, category_visible, subtree_ids_by_slug
from app.schemas.pagination import page_offset
from app.services.inventory import stock_figures

ALLOCATING_STATES = ("active", "committed")
CatalogSortField = Literal["name", "price", "newest", "bestselling", "top_rated"]
CatalogSortDirection = Literal["asc", "desc"]
# Direction used when none is sent: names A-Z, cheapest first, newest first, most sold first.
DEFAULT_DIRECTIONS: dict[str, CatalogSortDirection] = {
    "name": "asc",
    "price": "asc",
    "newest": "desc",
    "bestselling": "desc",
    "top_rated": "desc",
}
# Bestselling (B3, rule approved 2026-10-26): only delivered orders count, because delivery is
# the one status that is a reliable sale today, cash on delivery included; 'delivered' is final
# (order_service.ORDER_TRANSITIONS). Only deliveries in the last BESTSELLING_WINDOW count, dated
# by the order's 'delivered' status history row (orders have no delivered_at column). Refunds
# and returns are subtracted once they exist (module 15).
SOLD_ORDER_STATUS = "delivered"
BESTSELLING_WINDOW = timedelta(days=90)
SEARCH_CONFIG = "simple"
# Every lexeme of a websearch_to_tsquery result, as tsquery text ('word', with '' for a quote),
# gets the prefix marker: 'word' -> 'word':*. Operators (&, |, !, <->) are kept as they are.
LEXEME_PATTERN = r"'((?:[^']|'')+)'"
PREFIX_REPLACEMENT = r"'\1':*"


def list_active_categories(session: Session) -> list[Category]:
    return list(
        session.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order, Category.name, Category.id)
        )
    )


def active_menu_brands(session: Session) -> dict[UUID, list[Brand]]:
    """The active brands of each category's menu list, in staff order (ADR-012, 2026-11-16)."""
    rows = session.execute(
        select(CategoryMenuBrand.category_id, Brand)
        .join(Brand, Brand.id == CategoryMenuBrand.brand_id)
        .where(Brand.is_active.is_(True))
        .order_by(CategoryMenuBrand.category_id, CategoryMenuBrand.position)
    ).tuples()
    brands: dict[UUID, list[Brand]] = {}
    for category_id, brand in rows:
        brands.setdefault(category_id, []).append(brand)
    return brands


def public_spotlight_slugs(
    session: Session,
    picks: dict[UUID, UUID],
    parents: dict[UUID, UUID | None],
) -> dict[UUID, str]:
    """The slugs of the picked spotlight products ({category: product}) that are public and in
    the picking category or below it; parents maps every active category to its parent."""
    if not picks:
        return {}
    rows = session.execute(
        select(Product.id, Product.slug, Product.category_id).where(
            Product.id.in_(set(picks.values())),
            Product.id.in_(_base_public_products().with_only_columns(Product.id)),
        )
    ).tuples()
    found: dict[UUID, tuple[str, UUID]] = {
        product_id: (slug, category_id) for product_id, slug, category_id in rows
    }
    slugs: dict[UUID, str] = {}
    for category_id, product_id in picks.items():
        if product_id not in found:
            continue
        slug, first = found[product_id]
        ancestor: UUID | None = first
        seen: set[UUID] = set()
        while ancestor is not None and ancestor not in seen:
            if ancestor == category_id:
                slugs[category_id] = slug
                break
            seen.add(ancestor)
            ancestor = parents.get(ancestor)
    return slugs


def list_active_brands_with_product_counts(session: Session) -> list[tuple[Brand, int]]:
    """Active brands with the number of their public products (same rule as the listing)."""
    public_counts = (
        _base_public_products()
        .with_only_columns(Product.brand_id, func.count(Product.id).label("product_count"))
        .where(Product.brand_id.is_not(None))
        .group_by(Product.brand_id)
        .subquery()
    )
    # type_coerce gives the count column a Python type (int), so each row is (Brand, int).
    product_count = type_coerce(func.coalesce(public_counts.c.product_count, 0), Integer)
    rows = session.execute(
        select(Brand, product_count)
        .outerjoin(public_counts, public_counts.c.brand_id == Brand.id)
        .where(Brand.is_active.is_(True))
        .order_by(Brand.name, Brand.id)
    ).all()
    return [(brand, count) for brand, count in rows]


def _public_product_options():
    return (
        joinedload(Product.category),
        joinedload(Product.brand),
        joinedload(Product.store),
        selectinload(Product.images.and_(ProductImage.variant_id.is_(None))),
        selectinload(Product.variants.and_(ProductVariant.is_active.is_(True))).selectinload(
            ProductVariant.images
        ),
    )


def _base_public_products():
    """The single public-visibility rule: an active product of an approved store (ADR-014
    phase 2; suspending a store hides its products), in a visible category, with an active brand
    or none."""
    return (
        select(Product)
        .join(Product.category)
        .join(Store, Store.id == Product.store_id)
        .outerjoin(Product.brand)
        .where(
            Product.status == "active",
            Store.status == "approved",
            Category.is_active.is_(True),
            # Hidden parent, hidden subtree: the same rule as the public category tree.
            category_visible(Product.category_id),
            or_(Product.brand_id.is_(None), Brand.is_active.is_(True)),
        )
    )


def public_product_ids():
    """The ids of every public product (the same rule as the listing)."""
    return _base_public_products().with_only_columns(Product.id)


def _available_variant_exists(variant_id):
    reserved_quantity = (
        select(func.coalesce(func.sum(StockReservation.quantity), 0))
        .where(
            StockReservation.variant_id == InventoryBalance.variant_id,
            StockReservation.status.in_(ALLOCATING_STATES),
        )
        .scalar_subquery()
    )
    available = InventoryBalance.on_hand - InventoryBalance.unavailable_quantity - reserved_quantity
    return (
        select(InventoryBalance.variant_id)
        .where(
            InventoryBalance.variant_id == variant_id,
            available > 0,
        )
        .exists()
    )


def _matching_variant_exists(
    *, min_price: int | None, max_price: int | None, in_stock: bool | None
):
    query = select(ProductVariant.id).where(
        ProductVariant.product_id == Product.id, ProductVariant.is_active.is_(True)
    )
    if min_price is not None:
        query = query.where(ProductVariant.price >= min_price)
    if max_price is not None:
        query = query.where(ProductVariant.price <= max_price)
    if in_stock:
        return query.where(_available_variant_exists(ProductVariant.id)).exists()
    if in_stock is False:
        # A product is out of stock only when none of its matching active variants
        # has available inventory. Missing inventory rows count as unavailable.
        available_query = query.where(_available_variant_exists(ProductVariant.id))
        return query.exists() & ~available_query.exists()
    return query.exists()


def _on_sale_variant_exists():
    """An active variant of the product priced below its compare-at price (Deals, 2026-10-27)."""
    return (
        select(ProductVariant.id)
        .where(
            ProductVariant.product_id == Product.id,
            ProductVariant.is_active.is_(True),
            ProductVariant.compare_at_price.is_not(None),
            ProductVariant.compare_at_price > ProductVariant.price,
        )
        .exists()
    )


@dataclass(frozen=True)
class ProductFilters:
    """The public product list's filters (also used for facets). Empty values filter nothing."""

    category_slug: str | None = None
    brand_slugs: tuple[str, ...] = ()
    search: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    in_stock: bool | None = None
    featured: bool | None = None
    on_sale: bool | None = None
    min_rating: int | None = None
    store_slug: str | None = None  # ADR-014 phase 2: one approved store's products
    # ADR-014 phase 6: (attribute key, codes) pairs; any code of a key matches, all keys apply.
    attributes: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _filtered_products(f: ProductFilters):
    query = _base_public_products()
    if f.store_slug:
        query = query.where(Store.slug == f.store_slug)
    for key, codes in f.attributes:
        query = query.where(Product.specifications[key].astext.in_(codes))
    if f.min_rating is not None:
        query = query.where(Product.rating_average >= f.min_rating)
    if f.featured is not None:
        query = query.where(Product.is_featured.is_(f.featured))
    if f.on_sale is not None:
        query = query.where(_on_sale_variant_exists() if f.on_sale else ~_on_sale_variant_exists())
    if f.category_slug:  # the category and its subcategories
        query = query.where(Product.category_id.in_(subtree_ids_by_slug(f.category_slug)))
    if f.brand_slugs:
        query = query.where(Brand.slug.in_(f.brand_slugs))
    if f.search:
        query = query.where(Product.search_vector.op("@@")(search_query(f.search)))
    if f.min_price is not None or f.max_price is not None or f.in_stock is not None:
        query = query.where(
            _matching_variant_exists(
                min_price=f.min_price, max_price=f.max_price, in_stock=f.in_stock
            )
        )
    return query


def search_query(search: str):
    """Full-text query for `q`: websearch syntax (quoted phrases, `or`, `-word`) in the 'simple'
    configuration, with prefix matching on every word. The text is a bound parameter; input that
    yields no words (only punctuation) matches nothing."""
    web = cast(func.websearch_to_tsquery(SEARCH_CONFIG, search), Text)
    return func.to_tsquery(
        SEARCH_CONFIG, func.regexp_replace(web, LEXEME_PATTERN, PREFIX_REPLACEMENT, "g")
    )


def lowest_active_price():
    """Lowest price among the product's active variants; NULL when it has none."""
    return (
        select(func.min(ProductVariant.price))
        .where(ProductVariant.product_id == Product.id, ProductVariant.is_active.is_(True))
        .correlate(Product)
        .scalar_subquery()
    )


def units_sold():
    """Units of the product in orders delivered within BESTSELLING_WINDOW (B3); 0 when none."""
    delivered_recently = (
        select(OrderStatusHistory.id)
        .where(
            OrderStatusHistory.order_id == Order.id,
            OrderStatusHistory.status == SOLD_ORDER_STATUS,
            OrderStatusHistory.created_at >= func.now() - BESTSELLING_WINDOW,
        )
        .exists()
    )
    return (
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.product_id == Product.id,
            Order.status == SOLD_ORDER_STATUS,
            delivered_recently,
        )
        .correlate(Product)
        .scalar_subquery()
    )


def _ordering(
    search: str | None,
    sort_by: CatalogSortField | None,
    sort_direction: CatalogSortDirection | None,
) -> list[Any]:
    """ORDER BY for the listing. Product ID (ascending) always breaks remaining ties.

    - No sort_by with a search: best match first (ts_rank), then name A-Z.
    - No sort_by without a search: name.
    - price: lowest active variant price; products without an active variant come last in both
      directions.
    - top_rated (module 20): average rating, then number of approved reviews; sort_direction
      flips both; products without reviews come last in both directions.
    - bestselling: units sold (units_sold); sort_direction flips only that. Ties, including
      every product with no recent sales, go featured first, then newest, so the storefront's
      Bestsellers section is never empty or random while active products exist.
    """
    if sort_by is None and search:
        rank = func.ts_rank(Product.search_vector, search_query(search))
        return [rank.desc(), Product.name.asc(), Product.id.asc()]
    field: CatalogSortField = sort_by or "name"
    direction = sort_direction or DEFAULT_DIRECTIONS[field]
    if field == "price":
        price = lowest_active_price()
        primary = price.asc() if direction == "asc" else price.desc()
        return [primary.nulls_last(), Product.id.asc()]
    if field == "top_rated":
        # Module 20: best average first, then most reviews; unreviewed products always last.
        if direction == "desc":
            average, reviews = Product.rating_average.desc(), Product.rating_count.desc()
        else:
            average, reviews = Product.rating_average.asc(), Product.rating_count.asc()
        return [average.nulls_last(), reviews, Product.id.asc()]
    if field == "bestselling":
        sold = units_sold()
        primary = sold.asc() if direction == "asc" else sold.desc()
        return [primary, Product.is_featured.desc(), Product.created_at.desc(), Product.id.asc()]
    column = Product.name if field == "name" else Product.created_at
    return [column.asc() if direction == "asc" else column.desc(), Product.id.asc()]


def list_public_products(
    session: Session,
    *,
    filters: ProductFilters,
    page: int,
    size: int,
    sort_by: CatalogSortField | None,
    sort_direction: CatalogSortDirection | None,
) -> tuple[list[Product], int]:
    matching = _filtered_products(filters)
    total = _count(session, matching)
    products = list(
        session.scalars(
            matching.options(*_public_product_options())
            .order_by(*_ordering(filters.search, sort_by, sort_direction))
            .offset(page_offset(page, size))
            .limit(size)
        ).unique()
    )
    return products, total


def _count(session: Session, query) -> int:
    return session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0


# Facets (frontend phase 2, approved 2026-10-27): option counts for the listing's filter panel.
# Price bands follow Category.dc.html; a product counts in every band one of its active variants
# falls in (the price filter matches any variant, too).
PRICE_BANDS: tuple[tuple[int | None, int | None], ...] = (
    (None, 199_999),
    (200_000, 399_999),
    (400_000, 599_999),
    (600_000, 999_999),
    (1_000_000, None),
)
RATING_THRESHOLDS = (4, 3, 2, 1)


def _counts_within(session: Session, filters: ProductFilters, conditions: list[Any]) -> list[int]:
    """For the products matching filters, how many meet each condition (one query)."""
    matching = _filtered_products(filters).with_only_columns(Product.id).subquery()
    row = session.execute(
        select(*[func.count().filter(condition) for condition in conditions])
        .select_from(Product)
        .where(Product.id.in_(select(matching.c.id)))
    ).one()
    return [int(value) for value in row]


def _attribute_counts(session: Session, filters: ProductFilters, key: str) -> list[dict[str, Any]]:
    """A furniture attribute's codes with matches, in the attribute's own order, ignoring that
    attribute's own filter (multi-select, like brands). A chosen code without matches stays
    listed with count 0, so it can be unticked."""
    without = replace(filters, attributes=tuple(p for p in filters.attributes if p[0] != key))
    value = Product.specifications[key].astext
    rows = session.execute(
        _filtered_products(without)
        .with_only_columns(value, type_coerce(func.count(Product.id), Integer))
        .where(value.in_(ATTRIBUTES[key].choices))
        .group_by(value)
    ).all()
    counts: dict[str, int] = {code: n for code, n in rows}
    for _, codes in (p for p in filters.attributes if p[0] == key):
        for code in codes:
            counts.setdefault(code, 0)
    return [{"value": c, "count": counts[c]} for c in ATTRIBUTES[key].choices if c in counts]


def catalogue_facets(session: Session, filters: ProductFilters) -> dict[str, Any]:
    """Counts for each filter option. Each group ignores its own filter and applies the others,
    so a count is what the list would show with that option picked (multi-select brands)."""
    without_brand = replace(filters, brand_slugs=())
    brand_rows = session.execute(
        _filtered_products(without_brand)
        .with_only_columns(Brand.slug, Brand.name, type_coerce(func.count(Product.id), Integer))
        .where(Product.brand_id.is_not(None))
        .group_by(Brand.slug, Brand.name)
    ).all()
    brands: dict[Any, dict[str, Any]] = {
        slug: {"slug": slug, "name": name, "count": n} for slug, name, n in brand_rows
    }
    missing = [slug for slug in filters.brand_slugs if slug not in brands]
    if missing:  # a selected brand with no matches stays listed, so it can be unticked
        for slug, name in session.execute(
            select(Brand.slug, Brand.name).where(Brand.slug.in_(missing), Brand.is_active)
        ):
            brands[slug] = {"slug": slug, "name": name, "count": 0}

    # Categories (frontend phase 3, 2026-10-27): the brand page's Category group and the search
    # page's category chips. Single choice, in the storefront menu's order. Counted per main
    # category (category hierarchy, 2026-11-16): a subcategory's products count for its main one.
    without_category = replace(filters, category_slug=None)
    roots = category_roots()
    main = aliased(Category, name="main_category")
    category_rows = session.execute(
        _filtered_products(without_category)
        .with_only_columns(
            main.slug,
            main.name,
            main.sort_order,
            type_coerce(func.count(Product.id), Integer),
        )
        .join(roots, roots.c.id == Product.category_id)
        .join(main, main.id == roots.c.root_id)
        .group_by(main.slug, main.name, main.sort_order)
    ).all()
    categories: dict[Any, dict[str, Any]] = {
        slug: {"slug": slug, "name": name, "count": n, "_order": order}
        for slug, name, order, n in category_rows
    }
    if filters.category_slug and filters.category_slug not in categories:
        row = session.execute(
            select(Category.slug, Category.name, Category.sort_order).where(
                Category.slug == filters.category_slug, Category.is_active
            )
        ).first()
        if row is not None:  # the chosen category stays listed, so it can be cleared
            categories[row[0]] = {"slug": row[0], "name": row[1], "count": 0, "_order": row[2]}

    without_price = replace(filters, min_price=None, max_price=None)
    band_counts = _counts_within(
        session,
        without_price,
        [
            _matching_variant_exists(min_price=low, max_price=high, in_stock=filters.in_stock)
            for low, high in PRICE_BANDS
        ],
    )
    without_stock = replace(filters, in_stock=None)
    in_stock, out_of_stock = _counts_within(
        session,
        without_stock,
        [
            _matching_variant_exists(
                min_price=filters.min_price, max_price=filters.max_price, in_stock=stock
            )
            for stock in (True, False)
        ],
    )
    rating_counts = _counts_within(
        session,
        replace(filters, min_rating=None),
        [Product.rating_average >= stars for stars in RATING_THRESHOLDS],
    )
    attributes = [
        {"key": key, "values": _attribute_counts(session, filters, key)}
        for key in FILTER_ATTRIBUTES
    ]
    return {
        "attributes": attributes,
        "total": _count(session, _filtered_products(filters)),
        "brands": sorted(brands.values(), key=lambda b: (str(b["name"]).lower(), b["slug"])),
        "categories": [
            {"slug": c["slug"], "name": c["name"], "count": c["count"]}
            for c in sorted(
                categories.values(), key=lambda c: (c["_order"], str(c["name"]).lower())
            )
        ],
        "price_bands": [
            {"min_price": low, "max_price": high, "count": count}
            for (low, high), count in zip(PRICE_BANDS, band_counts, strict=True)
        ],
        "availability": {"in_stock": in_stock, "out_of_stock": out_of_stock},
        "ratings": [
            {"min_rating": stars, "count": count}
            for stars, count in zip(RATING_THRESHOLDS, rating_counts, strict=True)
        ],
    }


def get_public_product_by_slug(session: Session, slug: str) -> Product | None:
    return session.scalar(
        _base_public_products().where(Product.slug == slug).options(*_public_product_options())
    )


def get_public_products_by_ids(session: Session, product_ids: list[UUID]) -> list[Product]:
    """The products among product_ids that are public now (same rule as the listing)."""
    if not product_ids:
        return []
    return list(
        session.scalars(
            _base_public_products()
            .where(Product.id.in_(product_ids))
            .options(*_public_product_options())
        ).unique()
    )


def public_product_exists(session: Session, product_id: UUID) -> bool:
    return (
        session.scalar(
            _base_public_products().with_only_columns(Product.id).where(Product.id == product_id)
        )
        is not None
    )


def public_product_slugs(session: Session, product_ids: list[UUID]) -> dict[UUID, str]:
    """The slug of each product among product_ids that is public now (links from order lines)."""
    if not product_ids:
        return {}
    rows = session.execute(
        _base_public_products()
        .with_only_columns(Product.id, Product.slug)
        .where(Product.id.in_(product_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


def get_available_quantities(session: Session, variant_ids: list[UUID]) -> dict[UUID, int]:
    """Available units per SKU that has an inventory record, from the one stock calculation
    (app.services.inventory.stock_figures). SKUs without a record are absent (available 0)."""
    if not variant_ids:
        return {}
    figures, columns = stock_figures(variant_ids)
    rows = session.execute(
        figures.where(ProductVariant.id.in_(variant_ids), columns.has_inventory_record)
    ).mappings()
    return {row["variant_id"]: int(row["available_quantity"]) for row in rows}
