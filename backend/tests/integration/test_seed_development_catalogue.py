"""scripts/seed_development_catalogue.py (frontend phase 1, checkpoint 2; approved 2026-10-26).

Runs on the disposable per-test PostgreSQL schema (tests/conftest.py), with image storage in a
temporary folder and the worker's job processing run inline. It never touches a real database.
"""

import importlib.util
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import CartRateLimiter
from app.integrations.media import LocalMediaStorage, get_media_storage
from app.main import app
from app.models import (
    AuditRecord,
    Banner,
    Brand,
    Category,
    MediaObject,
    Order,
    Page,
    Product,
    ProductReview,
    ProductVariant,
    Setting,
    StockReservation,
    User,
    WishlistItem,
)
from app.models.content import PAGE_SLUGS
from app.services import bulk_images, dev_data_guard, jobs

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the class is built
    spec.loader.exec_module(module)
    return module


seed_dev = _load("seed_dev")
seeder = _load("seed_development_catalogue")
data = seeder.CATALOGUE
seeder_data = sys.modules["seed_catalogue_data"]


@pytest.fixture
def storage(tmp_path, monkeypatch) -> Iterator[LocalMediaStorage]:
    media = LocalMediaStorage(tmp_path / "media", get_settings().image_public_base_url)
    app.dependency_overrides[get_media_storage] = lambda: media
    monkeypatch.setattr("app.services.catalog.get_media_storage", lambda: media)
    monkeypatch.setattr(bulk_images, "get_media_storage", lambda: media)
    yield media
    app.dependency_overrides.pop(get_media_storage, None)


def run_jobs_inline(db: Session, job_ids: list[uuid.UUID]) -> None:
    """What the worker process does, in the test process."""
    now = datetime.now(UTC)
    while (item_id := jobs.claim_next(db, now)) is not None:
        jobs.process(db, item_id, now)


@pytest.fixture
def seeded(db: Session, storage, cart_limiter: CartRateLimiter, monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "Staff-Pass-2026")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "Customer-Pass-2026")
    seed_dev.seed(db)  # delivery zones; the catalogue seed never sets the threshold

    def run(catalogue=data):
        return seeder.seed(db, storage, cart_limiter, catalogue, run_jobs_inline)

    return run


def count(db: Session, model, *where) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def outcomes(report) -> dict[str, dict[str, int]]:
    return {kind: dict(counter) for kind, counter in report.counts.items()}


def test_seed_creates_the_catalogue_once_and_cleanup_removes_it(
    db: Session, client: TestClient, seeded
):
    report = seeded()
    assert report.problems == []
    got = outcomes(report)
    assert got["staff"] == {"created": 1}  # SC-05: the Marketplace Administrator only
    assert got["customers"] == {"created": 5}
    assert got["categories"] == {"created": 5, "updated": 5}  # created, then the image
    assert got["brands"] == {"created": 12, "updated": 12}
    assert got["products"] == {"created": len(data.products)}
    assert got["variants"] == {"created": sum(len(p.variants) for p in data.products)}
    assert got["product images"] == {"created": len(data.products)}
    assert got["activation"] == {"updated": len(data.products)}
    assert got["orders"] == {"created": 15}
    assert got["reviews"] == {"created": 12}
    assert report.passwords == []  # passwords came from the environment

    # The categories are exactly the Header.dc.html nav; every product is active with an image.
    names = db.scalars(select(Category.name).order_by(Category.sort_order)).all()
    assert names == ["Phones", "Laptops", "TVs & Audio", "Home Appliances", "Accessories"]
    assert count(db, Product, Product.status == "active") == len(data.products)
    assert count(db, Banner, Banner.is_active) == 3
    assert count(db, Brand, Brand.logo_media_id.is_not(None)) == 12
    statuses = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    assert statuses == {
        "delivered": 8,
        "dispatched": 2,
        "processing": 1,
        "confirmed": 1,
        "received": 2,
        "cancelled": 1,
    }
    threshold: object = db.execute(
        text("SELECT value FROM settings WHERE key = 'delivery.free_delivery_threshold'")
    ).scalar_one()
    assert threshold == 50_000  # seed_dev's value; the catalogue seed leaves it alone

    # Reviews: 9 approved, 2 pending, 1 rejected; totals come from the approved ones only.
    review_statuses = dict(
        db.execute(select(ProductReview.status, func.count()).group_by(ProductReview.status)).all()
    )
    assert review_statuses == {"approved": 9, "pending": 2, "rejected": 1}
    power_bank = client.get("/api/v1/catalog/products/anker-powercore-20000").json()["rating"]
    assert power_bank["count"] == 2 and power_bank["average"] == 4.5  # the 2-star was rejected
    assert count(db, AuditRecord, AuditRecord.action == "catalog.review_approve") == 9

    # The storefront reads them: featured, bestselling (delivered units), and loadable images.
    featured = client.get("/api/v1/catalog/products", params={"featured": "true"}).json()
    assert featured["total"] == sum(p.featured for p in data.products)
    best = client.get(
        "/api/v1/catalog/products", params={"sort_by": "bestselling", "size": 3}
    ).json()
    assert [p["slug"] for p in best["items"]] == [
        "anker-powercore-20000",
        "tecno-spark-20",
        "apple-iphone-15",
    ]
    image = best["items"][0]["images"][0]
    assert image["width"] == 1200 and image["url"].startswith("http")

    # Rerun: nothing is duplicated, stock is not reset.
    on_hand: object = db.execute(text("SELECT sum(on_hand) FROM inventory_balances")).scalar_one()
    again = outcomes(seeded())
    assert all(set(c) == {"skipped"} for c in again.values()), again
    assert count(db, Order) == 15
    assert db.execute(text("SELECT sum(on_hand) FROM inventory_balances")).scalar_one() == on_hand

    # Saved products (module 21): a seed customer's, and a seed product in someone else's list.
    seed_customer = db.scalar(
        select(User.id).where(User.email.endswith("@seed.3sixty.local"), User.is_staff.is_(False))
    )
    seed_product = db.scalar(select(Product.id).limit(1))
    outsider = db.scalar(select(User.id).where(User.email.not_like("%@seed.3sixty.local")))
    if outsider is None:
        outsider_user = User(email="outsider@example.com", full_name="Outsider")
        db.add(outsider_user)
        db.flush()
        outsider = outsider_user.id
    db.add_all(
        [
            WishlistItem(user_id=seed_customer, product_id=seed_product),
            WishlistItem(user_id=outsider, product_id=seed_product),
        ]
    )
    db.commit()

    # Cleanup: everything seeded goes, categories and brands stay, the reservation guard is back.
    removed = seeder.cleanup(db)
    assert removed["wishlist items"] == 2
    assert removed["product reviews"] == 12
    assert count(db, ProductReview) == 0
    assert count(db, WishlistItem) == 0
    assert removed["orders"] == 15 and removed["products"] == len(data.products)
    assert removed["people"] == 6 and removed["banners"] == 3  # SC-05: 1 administrator, 5 customers
    for model in (Order, Product, ProductVariant, StockReservation, Banner):
        assert count(db, model) == 0, model
    assert count(db, User, User.email.endswith("@seed.3sixty.local")) == 0
    assert count(db, Category) == 5 and count(db, Brand) == 12
    assert count(db, MediaObject, MediaObject.state == "deleting") > 0  # files go to the worker
    enabled: object = db.execute(
        text(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = 'stock_reservations_guard' "
            "AND tgrelid = 'stock_reservations'::regclass"
        )
    ).scalar_one()
    assert enabled == "O"

    # And the seed works again afterwards.
    assert outcomes(seeded())["orders"] == {"created": 15}


def _small(products=1):
    return seeder.Catalogue(
        data.categories[:1],
        tuple(b for b in data.brands if b.slug == "samsung"),
        tuple(p for p in data.products if p.category == "phones" and p.brand == "samsung")[
            :products
        ],
        (),
        data.staff[:1],
        (),
        (),
    )


def test_draft_pages_and_contact_are_seeded_once_and_staff_edits_survive_cleanup(
    db: Session, client: TestClient, admin_auth: dict, seeded
):
    """Module 19 (2026-10-29): every policy page in both languages, each marked as a draft, and
    the sample contact; nothing staff wrote is overwritten or removed."""
    small = _small()
    content = seeder.Catalogue(
        small.categories,
        small.brands,
        (),
        (),
        small.staff,
        (),
        (),
        pages=data.pages,
        contact=data.contact,
    )
    assert {(p.slug, p.locale) for p in data.pages} == {
        (slug, locale) for slug in PAGE_SLUGS for locale in ("en", "rw")
    }
    drafts = {"en": seeder_data.DRAFT_EN, "rw": seeder_data.DRAFT_RW}
    assert all(p.body.startswith(drafts[p.locale]) for p in data.pages)
    h = admin_auth["headers"]
    edited = {"title": "Our warranty", "body": "Approved text.", "is_published": True}
    assert client.put("/api/v1/staff/pages/warranty?lang=en", json=edited, headers=h).is_success
    assert client.patch(
        "/api/v1/staff/settings", json={"contact.email": "sales@example.rw"}, headers=h
    ).is_success

    got = outcomes(seeded(content))
    assert got["pages"] == {"created": 11, "skipped": 1}
    assert got["contact settings"] == {"created": 5, "skipped": 1}
    assert outcomes(seeded(content))["pages"] == {"skipped": 12}
    public = client.get("/api/v1/settings").json()
    assert (public["phone"], public["email"]) == ("+250 788 123 456", "sales@example.rw")
    assert client.get("/api/v1/pages/privacy-policy?lang=rw").status_code == 200

    counts = seeder.cleanup(db, content)
    assert (counts["pages"], counts["contact settings"]) == (11, 5)
    assert db.scalars(select(Page.title)).all() == ["Our warranty"]
    assert db.scalars(select(Setting.key).where(Setting.key.like("contact.%"))).all() == [
        "contact.email"
    ]


def test_cleanup_refuses_while_another_customer_ordered_a_seed_product(
    db: Session, client: TestClient, customer_auth: dict, seeded
):
    small = _small()
    seeded(small)
    variant = db.scalar(select(ProductVariant).where(ProductVariant.sku.startswith("DEV-")))
    assert variant is not None
    h = customer_auth["headers"]
    added = client.post(
        "/api/v1/cart/items", json={"variant_id": str(variant.id), "quantity": 1}, headers=h
    )
    assert added.status_code == 200, added.text
    placed = client.post(
        "/api/v1/checkout",
        json={
            "address": {
                "recipient_name": "Customer Alice",
                "phone": "0788 111 222",
                "district": "Gasabo",
                "street_address": "KG 11 Ave",
            },
            "payment_method": "cash_on_delivery",
        },
        headers={**h, "Idempotency-Key": f"key-{uuid.uuid4().hex}"},
    )
    assert placed.status_code == 201, placed.text
    with pytest.raises(seeder.CleanupRefused, match="1 order lines"):
        seeder.cleanup(db, small)
    assert count(db, Product) == 1 and count(db, Order) == 1  # nothing was removed


def test_a_slug_held_by_a_non_seed_product_is_reported_not_changed(
    db: Session, client: TestClient, admin_auth: dict, seeded
):
    small = _small()
    seeded(seeder.Catalogue(small.categories, small.brands, (), (), small.staff, (), ()))
    category = db.scalar(select(Category))
    assert category is not None
    spec = small.products[0]
    res = client.post(
        "/api/v1/staff/products",
        json={"name": "Real product", "slug": spec.slug, "category_id": str(category.id)},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 201, res.text
    report = seeded(small)
    assert outcomes(report)["products"] == {"failed": 1}
    assert "non-seed product" in report.problems[0]
    product = db.scalar(select(Product).where(Product.slug == spec.slug))
    assert product is not None and product.name == "Real product"


@pytest.mark.parametrize(
    ("env", "url", "args", "message"),
    [
        ("production", "postgresql+psycopg://u:p@127.0.0.1/x", ["--confirm"], "APP_ENV"),
        ("development", "postgresql+psycopg://u:p@db.example.rw/x", ["--confirm"], "not local"),
        ("development", "postgresql+psycopg://u:p@127.0.0.1/x", [], "--confirm"),
        (
            "development",
            "postgresql+psycopg://u:p@db.example.rw/x",
            ["--cleanup", "--confirm"],
            "not local",
        ),
    ],
)
def test_main_refuses_before_connecting(monkeypatch, capsys, env, url, args, message):
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    monkeypatch.setattr(seeder, "get_settings", lambda: SimpleNamespace(app_env=env))
    monkeypatch.setattr(seeder, "create_engine", lambda *a, **k: pytest.fail("connected"))
    assert seeder.main(args) == 2
    assert message in capsys.readouterr().err


def test_seed_sku_prefix_matches_the_production_guard():
    assert seeder.SKU_PREFIX == dev_data_guard.DEV_SKU_PREFIX
    skus = [v.sku for p in data.products for v in p.variants]
    assert all(s.startswith("DEV-") and "__" not in s for s in skus)
    assert len({s.lower() for s in skus}) == len(skus)
    assert len({p.slug for p in data.products}) == len(data.products)
    known = {v.code for p in data.products for v in p.variants if v.stock != "out"}
    assert all(code in known for o in data.orders for code, _ in o.lines)


def test_production_health_reports_development_skus(
    db: Session, client: TestClient, monkeypatch, caplog, seeded
):
    seeded(_small())
    assert client.get("/api/v1/health").json()["checks"]["catalogue"] == "ok"  # development
    monkeypatch.setattr(
        dev_data_guard, "get_settings", lambda: SimpleNamespace(app_env="production")
    )
    body = client.get("/api/v1/health").json()
    assert body["status"] == "degraded" and body["checks"]["catalogue"] == "degraded"
    assert "development seed SKU" in caplog.text
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: db)
    caplog.clear()
    dev_data_guard.check_at_startup()
    assert "development seed SKU" in caplog.text
