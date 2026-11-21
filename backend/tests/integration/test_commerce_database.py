from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import (
    Brand,
    Category,
    InventoryBalance,
    Order,
    OrderItem,
    PaymentEvent,
    Product,
    ProductVariant,
    StockMovement,
    StockReservation,
)
from app.services.inventory import (
    InventoryUnavailable,
    TransitionOutcome,
    adjust_stock,
    commit_order_reservations,
    create_order_with_reservations,
    dispatch_order_inventory,
    expire_due_reservations,
    release_order_reservations,
)
from tests.support.media import image_row

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def db_engine():
    if not TEST_DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL is not configured; set it to the dedicated "
            "rwanda_ecommerce_test database.",
            pytrace=False,
        )
    test_url = make_url(TEST_DATABASE_URL)
    if test_url.database != "rwanda_ecommerce_test":
        pytest.fail(
            "PostgreSQL integration tests require TEST_DATABASE_URL to target "
            "'rwanda_ecommerce_test'; refusing to use another database.",
            pytrace=False,
        )

    admin_engine = create_engine(
        test_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    schema = f"test_{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = None
    try:
        schema_url = test_url.set(host="127.0.0.1").update_query_dict(
            {"options": f"-csearch_path={schema}"}
        )
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = schema_url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        try:
            command.upgrade(
                Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head"
            )
        finally:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url
            get_settings.cache_clear()
        engine = create_engine(
            schema_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def api_client(session_factory):
    from fastapi.testclient import TestClient

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed_sku(session: Session, *, on_hand: int = 1) -> ProductVariant:
    category = Category(name="Phones", slug=f"phones-{uuid4().hex}")
    brand = Brand(name="Example", slug=f"example-{uuid4().hex}")
    product = Product(
        name="Example phone",
        slug=f"example-phone-{uuid4().hex}",
        category=category,
        brand=brand,
        specifications={"storage": "128 GB"},
        status="active",
    )
    variant = ProductVariant(product=product, sku=f"SKU-{uuid4().hex}", name="Black", price=125000)
    variant.inventory = InventoryBalance(on_hand=on_hand, unavailable_quantity=0)
    session.add(product)
    session.flush()
    return variant


def _new_order(variant_id, *, order_number: str | None = None) -> Order:
    order = Order(
        order_number=order_number or f"ORD-{uuid4().hex}",
        checkout_idempotency_key=f"checkout-{uuid4().hex}",
        subtotal=125000,
        total=125000,
        recipient_name="Test Customer",
        recipient_phone="0780000000",
        delivery_address_snapshot={"district": "Kigali"},
    )
    order.items.append(
        OrderItem(
            variant_id=variant_id,
            sku_snapshot="SKU-SNAPSHOT",
            product_name_snapshot="Phone at purchase time",
            variant_snapshot={"colour": "black"},
            specifications_snapshot={"storage": "128 GB"},
            quantity=1,
            unit_price=125000,
            line_subtotal=125000,
            line_total=125000,
        )
    )
    return order


def test_database_constraints_reject_negative_price_and_duplicate_sku(session_factory):
    with session_factory() as session, session.begin():
        variant = _seed_sku(session)
        original_sku = variant.sku

    with session_factory() as session:
        invalid = _seed_sku(session)
        invalid.price = -1
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with session_factory() as session:
        duplicate = _seed_sku(session)
        duplicate.sku = original_sku
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with session_factory() as session:
        session.add(
            ProductVariant(
                product_id=uuid4(),
                sku=f"MISSING-PRODUCT-{uuid4().hex}",
                name="Invalid foreign key",
                price=10,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_order_item_keeps_catalogue_snapshot_after_product_edit(session_factory):
    with session_factory() as session, session.begin():
        variant = _seed_sku(session)
        product = variant.product
        order = _new_order(variant.id)
        create_order_with_reservations(
            session,
            order,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        item_id = order.items[0].id
        product.name = "Renamed after sale"
        variant.price = 150000

    with session_factory() as session:
        item = session.get(OrderItem, item_id)
        assert item.product_name_snapshot == "Phone at purchase time"
        assert item.unit_price == 125000
        assert item.specifications_snapshot == {"storage": "128 GB"}
        assert item.order.status_history[0].status == "received"


def test_concurrent_last_unit_checkout_reserves_only_once(session_factory):
    with session_factory() as session, session.begin():
        variant = _seed_sku(session, on_hand=1)
        variant_id = variant.id

    barrier = Barrier(2)

    def attempt_checkout() -> str:
        with session_factory() as session:
            order = _new_order(variant_id)
            barrier.wait(timeout=10)
            try:
                create_order_with_reservations(
                    session,
                    order,
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
                return "reserved"
            except InventoryUnavailable:
                return "unavailable"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt_checkout(), range(2)))

    assert sorted(results) == ["reserved", "unavailable"]
    with session_factory() as session:
        active = session.scalar(
            select(StockReservation).where(
                StockReservation.variant_id == variant_id,
                StockReservation.status.in_(("active", "committed")),
            )
        )
        assert active is not None and active.quantity == 1


def test_multiline_shortage_rolls_back_order_and_every_reservation(session_factory):
    with session_factory() as session, session.begin():
        available = _seed_sku(session, on_hand=1)
        unavailable = _seed_sku(session, on_hand=0)
        order = _new_order(available.id)
        order.items.append(
            OrderItem(
                variant_id=unavailable.id,
                sku_snapshot="OUT-OF-STOCK",
                product_name_snapshot="Unavailable item",
                quantity=1,
                unit_price=100,
                line_subtotal=100,
                line_total=100,
            )
        )
        order_number = order.order_number

    with session_factory() as session:
        with pytest.raises(InventoryUnavailable):
            create_order_with_reservations(
                session,
                order,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        assert session.scalar(select(Order).where(Order.order_number == order_number)) is None
        assert session.scalar(select(StockReservation)) is None


def test_cancellation_release_allows_next_checkout(session_factory):
    with session_factory() as session, session.begin():
        variant = _seed_sku(session, on_hand=1)
        variant_id = variant.id

    first_order = _new_order(variant_id)
    with session_factory() as session:
        create_order_with_reservations(
            session,
            first_order,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    with session_factory() as session:
        first = release_order_reservations(session, first_order.id, reason="cancelled")
        again = release_order_reservations(session, first_order.id, reason="cancelled")
        assert first.outcome == TransitionOutcome.RELEASED
        assert again.outcome == TransitionOutcome.ALREADY_RELEASED

    second_order = _new_order(variant_id)
    with session_factory() as session:
        create_order_with_reservations(
            session,
            second_order,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


def test_reservation_commit_dispatch_and_expiry_are_consistent(session_factory):
    with session_factory() as session, session.begin():
        variant = _seed_sku(session, on_hand=2)
        variant_id = variant.id

    order = _new_order(variant_id)
    with session_factory() as session:
        create_order_with_reservations(
            session,
            order,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    with session_factory() as session:
        assert commit_order_reservations(session, order.id).outcome == TransitionOutcome.COMMITTED
    with session_factory() as session:
        assert dispatch_order_inventory(session, order.id) == 1
    with session_factory() as session:
        assert dispatch_order_inventory(session, order.id) == 1
    with session_factory() as session:
        balance = session.scalar(
            select(InventoryBalance).where(InventoryBalance.variant_id == variant_id)
        )
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order.id)
        )
        movement = session.scalar(
            select(StockMovement).where(StockMovement.variant_id == variant_id)
        )
        assert balance.on_hand == 1
        assert reservation.status == "fulfilled"
        assert movement.quantity_delta == -1

        assert (
            adjust_stock(
                session,
                variant_id=variant_id,
                quantity_delta=1,
                reason="receipt",
                idempotency_key=f"receipt:{uuid4()}",
                actor=None,
            ).movement.quantity_delta
            == 1
        )

    expired_order = _new_order(variant_id)
    with session_factory() as session:
        create_order_with_reservations(
            session,
            expired_order,
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    time.sleep(1.2)
    with session_factory() as session:
        assert expire_due_reservations(session).orders == 1
    with session_factory() as session:
        expired = session.scalar(
            select(StockReservation).where(StockReservation.order_id == expired_order.id)
        )
        assert expired.status == "expired"
        assert expired.released_at is not None
        late = commit_order_reservations(session, expired_order.id)
        assert late.outcome == TransitionOutcome.NEEDS_RECONCILIATION


def test_payment_provider_event_key_is_idempotently_unique(session_factory):
    event_time = datetime.now(UTC)
    event_key = f"provider-event-{uuid4()}"
    with session_factory() as session:
        session.add(
            PaymentEvent(
                provider="test-provider",
                event_key=event_key,
                verification_status="verified",
                processing_status="processed",
                received_at=event_time,
            )
        )
        session.commit()

    with session_factory() as session:
        session.add(
            PaymentEvent(
                provider="test-provider",
                event_key=event_key,
                verification_status="verified",
                processing_status="processed",
                received_at=event_time,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_public_catalog_filters_visibility_and_lists_active_categories_brands(
    session_factory, api_client
):
    with session_factory() as session, session.begin():
        category = Category(name="Phones", slug=f"phones-{uuid4().hex}", sort_order=2)
        inactive_category = Category(name="Hidden", slug=f"hidden-{uuid4().hex}", is_active=False)
        brand = Brand(name="Example", slug=f"example-{uuid4().hex}")
        inactive_brand = Brand(name="Private", slug=f"private-{uuid4().hex}", is_active=False)
        visible = Product(
            name="Visible phone",
            slug=f"visible-{uuid4().hex}",
            status="active",
            category=category,
            brand=brand,
        )
        hidden_products = [
            Product(
                name=f"{status} phone",
                slug=f"{status}-{uuid4().hex}",
                status=status,
                category=category,
                brand=brand,
            )
            for status in ("draft", "hidden", "archived")
        ]
        hidden_category_product = Product(
            name="Inactive category phone",
            slug=f"inactive-category-{uuid4().hex}",
            status="active",
            category=inactive_category,
        )
        hidden_brand_product = Product(
            name="Inactive brand phone",
            slug=f"inactive-brand-{uuid4().hex}",
            status="active",
            category=category,
            brand=inactive_brand,
        )
        session.add_all([visible, *hidden_products, hidden_category_product, hidden_brand_product])
        session.flush()
        visible_slug = visible.slug
        hidden_slug = hidden_products[1].slug
        category_slug = category.slug
        brand_slug = brand.slug

    categories = api_client.get("/api/v1/catalog/categories").json()
    brands = api_client.get("/api/v1/catalog/brands").json()
    results = api_client.get("/api/v1/catalog/products").json()
    assert [row["slug"] for row in categories] == [category_slug]
    assert [row["slug"] for row in brands] == [brand_slug]
    assert results["total"] == 1
    assert results["items"][0]["slug"] == visible_slug
    assert (
        api_client.get(
            "/api/v1/catalog/products", params={"category": category_slug, "brand": brand_slug}
        ).json()["total"]
        == 1
    )
    assert api_client.get("/api/v1/catalog/products", params={"q": "visible"}).json()["total"] == 1
    assert api_client.get(f"/api/v1/catalog/products/{hidden_slug}").status_code == 404


def test_public_product_details_include_prices_specs_ordered_images_and_inventory(
    session_factory, api_client
):
    with session_factory() as session, session.begin():
        category = Category(name="Phones", slug=f"phones-{uuid4().hex}")
        brand = Brand(name="Example", slug=f"brand-{uuid4().hex}")
        product = Product(
            name="Example phone",
            slug=f"example-{uuid4().hex}",
            status="active",
            category=category,
            brand=brand,
            specifications={"screen": "6.1 inch", "storage": "128 GB"},
            warranty_text="One year manufacturer warranty",
        )
        active = ProductVariant(
            product=product,
            sku=f"SKU-{uuid4().hex}",
            name="Black",
            attributes={"colour": "black"},
            price=12345,
            compare_at_price=15000,
        )
        ProductVariant(
            product=product,
            sku=f"SKU-{uuid4().hex}",
            name="Inactive blue",
            price=11000,
            is_active=False,
        )
        product.images.extend(
            [
                image_row(None, 2, key="product/second.jpg"),
                image_row(None, 1, key="product/first.jpg"),
            ]
        )
        variant_images = [
            image_row(None, 4, key="variant/second.jpg"),
            image_row(None, 3, key="variant/first.jpg"),
        ]
        for image in variant_images:
            image.product = product
        active.images.extend(variant_images)
        active.inventory = InventoryBalance(on_hand=8, unavailable_quantity=1)
        session.add(product)
        session.flush()
        for status, quantity in (("active", 2), ("committed", 1), ("released", 3)):
            order = _new_order(active.id)
            session.add(order)
            session.flush()
            session.add(
                StockReservation(
                    order_id=order.id,
                    variant_id=active.id,
                    quantity=quantity,
                    status=status,
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    committed_at=datetime.now(UTC) if status == "committed" else None,
                    released_at=datetime.now(UTC) if status == "released" else None,
                    idempotency_key=f"catalog:{uuid4().hex}",
                )
            )
        slug = product.slug

    response = api_client.get(f"/api/v1/catalog/products/{slug}")
    assert response.status_code == 200
    data = response.json()
    assert data["specifications"] == {"screen": "6.1 inch", "storage": "128 GB"}
    assert data["warranty_text"] == "One year manufacturer warranty"
    assert [image["url"].rsplit("/media/", 1)[1] for image in data["images"]] == [
        "product/first.jpg",
        "product/second.jpg",
    ]
    assert len(data["variants"]) == 1
    variant = data["variants"][0]
    assert variant["price"] == 12345
    assert variant["compare_at_price"] == 15000
    assert variant["currency_code"] == "RWF"
    assert variant["stock_status"] == "in_stock"  # 4 available, no low-stock threshold
    assert "available_quantity" not in variant
    assert variant["in_stock"] is True
    assert [image["url"].rsplit("/media/", 1)[1] for image in variant["images"]] == [
        "variant/first.jpg",
        "variant/second.jpg",
    ]


def test_catalog_reports_zero_stock_without_balance_and_filters_price_stock_and_pages(
    session_factory, api_client
):
    with session_factory() as session, session.begin():
        category = Category(name="Phones", slug=f"phones-{uuid4().hex}")
        brand = Brand(name="Example", slug=f"brand-{uuid4().hex}")
        variants = []
        for name, price, with_balance in (
            ("Alpha phone", 100, True),
            ("Beta phone", 200, False),
        ):
            product = Product(
                name=name,
                slug=f"{name.split()[0].lower()}-{uuid4().hex}",
                status="active",
                category=category,
                brand=brand,
            )
            variant = ProductVariant(
                product=product,
                sku=f"SKU-{uuid4().hex}",
                name="Standard",
                price=price,
            )
            if with_balance:
                variant.inventory = InventoryBalance(on_hand=2, unavailable_quantity=0)
                ProductVariant(
                    product=product,
                    sku=f"SKU-{uuid4().hex}",
                    name="Unavailable option",
                    price=price,
                )
            session.add(product)
            variants.append(variant)
        session.flush()

    page = api_client.get("/api/v1/catalog/products", params={"page": 1, "size": 1})
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    in_stock = api_client.get("/api/v1/catalog/products", params={"in_stock": "true"}).json()
    assert in_stock["total"] == 1
    out_of_stock = api_client.get("/api/v1/catalog/products", params={"in_stock": "false"}).json()
    assert out_of_stock["total"] == 1
    assert out_of_stock["items"][0]["name"] == "Beta phone"
    priced = api_client.get(
        "/api/v1/catalog/products", params={"min_price": "150", "max_price": "250"}
    ).json()
    assert priced["total"] == 1
    assert priced["items"][0]["variants"][0]["stock_status"] == "out_of_stock"


def test_catalog_validates_filters_and_hides_nonpublic_or_missing_slugs(api_client):
    for params in (
        {"page": 0},
        {"size": 101},
        {"min_price": "20", "max_price": "10"},
        {"min_price": "-1"},
        {"min_price": "150.50"},
        {"max_price": "1000000000000"},
        {"size": "not-a-number"},
        {"sort_by": "popularity"},  # module 9 sorts are name, price and newest
        {"sort_direction": "sideways"},
        {"q": "   "},
        {"q": "x" * 161},
    ):
        assert api_client.get("/api/v1/catalog/products", params=params).status_code == 422
    reversed_range = api_client.get(
        "/api/v1/catalog/products", params={"min_price": "20", "max_price": "10"}
    ).json()["error"]
    assert reversed_range["code"] == "validation_error"
    assert reversed_range["details"][0]["loc"] == ["query", "min_price"]
    missing = api_client.get("/api/v1/catalog/products/not-a-public-slug")
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "product_not_found",
        "message": "Product not found",
        "details": None,
    }


def test_catalog_search_fields_punctuation_and_combined_filters(session_factory, api_client):
    """Module 9: q is full-text search (name, model, brand) with prefix matching."""
    with session_factory() as session, session.begin():
        phones = Category(name="Phones", slug=f"phones-{uuid4().hex}")
        laptops = Category(name="Laptops", slug=f"laptops-{uuid4().hex}")
        google = Brand(name="Google", slug=f"google-{uuid4().hex}")
        other_brand = Brand(name="Other", slug=f"other-{uuid4().hex}")
        target = Product(
            name="Pixel 100% phone",
            slug=f"pixel-{uuid4().hex}",
            model="GX-10",
            status="active",
            category=phones,
            brand=google,
        )
        target_variant = ProductVariant(
            product=target, sku=f"PIXEL-{uuid4().hex}", name="Black", price=100
        )
        target_variant.inventory = InventoryBalance(on_hand=3, unavailable_quantity=0)
        decoys = [
            Product(
                name="Other phone",
                slug=f"other-phone-{uuid4().hex}",
                model="GX-11",
                status="active",
                category=phones,
                brand=other_brand,
            ),
            Product(
                name="Pixel laptop",
                slug=f"pixel-laptop-{uuid4().hex}",
                model="GX-10",
                status="active",
                category=laptops,
                brand=google,
            ),
        ]
        decoys[0].variants.append(
            ProductVariant(sku=f"OTHER-{uuid4().hex}", name="Standard", price=100)
        )
        session.add_all([target, *decoys])
        session.flush()
        target_slug = target.slug
        phone_category_slug = phones.slug
        google_slug = google.slug

    for term in ("pixel", "google", "gx-10"):
        response = api_client.get("/api/v1/catalog/products", params={"q": term})
        assert response.status_code == 200
        assert target_slug in {item["slug"] for item in response.json()["items"]}

    # Punctuation is not a wildcard: input without letters or digits matches nothing, and
    # "100%" finds the word 100 in the name.
    for term in ("%", "_", "!!", "'"):
        punctuation = api_client.get("/api/v1/catalog/products", params={"q": term})
        assert punctuation.status_code == 200, term
        assert punctuation.json()["total"] == 0, term
    percent = api_client.get("/api/v1/catalog/products", params={"q": "100%"}).json()
    assert [item["slug"] for item in percent["items"]] == [target_slug]

    combined = api_client.get(
        "/api/v1/catalog/products",
        params={
            "category": phone_category_slug,
            "brand": google_slug,
            "q": "GX-10",
            "min_price": "100",
            "max_price": "100",
            "in_stock": "true",
        },
    )
    assert combined.status_code == 200
    assert combined.json()["total"] == 1
    assert [item["slug"] for item in combined.json()["items"]] == [target_slug]

    no_matches = api_client.get("/api/v1/catalog/products", params={"q": "no-such-device"})
    assert no_matches.status_code == 200
    assert no_matches.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_catalog_name_sort_directions_have_stable_pagination(session_factory, api_client):
    with session_factory() as session, session.begin():
        category = Category(name="Sort test", slug=f"sort-{uuid4().hex}")
        products = [
            Product(
                name=name,
                slug=f"{name.lower()}-{uuid4().hex}",
                status="active",
                category=category,
            )
            for name in ("Bravo", "Alpha", "Alpha")
        ]
        session.add_all(products)
        session.flush()
        expected_ascending = [
            product.slug for product in sorted(products, key=lambda item: (item.name, str(item.id)))
        ]
        expected_descending = [
            product.slug
            for name in ("Bravo", "Alpha")
            for product in sorted(
                (item for item in products if item.name == name), key=lambda item: str(item.id)
            )
        ]

    def get_page(page: int, direction: str):
        return api_client.get(
            "/api/v1/catalog/products",
            params={
                "page": page,
                "size": 2,
                "sort_by": "name",
                "sort_direction": direction,
            },
        )

    ascending_first = get_page(1, "asc")
    ascending_second = get_page(2, "asc")
    assert ascending_first.status_code == ascending_second.status_code == 200
    assert [item["slug"] for item in ascending_first.json()["items"]] == expected_ascending[:2]
    assert [item["slug"] for item in ascending_second.json()["items"]] == expected_ascending[2:]
    assert ascending_first.json()["total"] == ascending_second.json()["total"] == 3

    descending_first = get_page(1, "desc")
    descending_second = get_page(2, "desc")
    assert [item["slug"] for item in descending_first.json()["items"]] == expected_descending[:2]
    assert [item["slug"] for item in descending_second.json()["items"]] == expected_descending[2:]

    last_page = api_client.get("/api/v1/catalog/products", params={"page": 3, "size": 2})
    assert last_page.status_code == 200
    assert last_page.json() == {"items": [], "total": 3, "page": 3, "size": 2}
