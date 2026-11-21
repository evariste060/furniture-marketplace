"""Seed (or remove) the development catalogue: categories, brands, products, images, banners,
staff, customers and orders (frontend phase 1, checkpoint 2; approved 2026-10-26), plus draft
policy pages and a sample store contact (module 19, approved 2026-10-29).

Run from backend/, with the API database migrated, the runtime role provisioned, the delivery
zones seeded (`uv run python ../scripts/seed_dev.py`) and the worker running next to it
(`uv run python -m app.worker`), because product photos go through the real bulk upload:

    uv run python ../scripts/seed_development_catalogue.py --confirm
    uv run python ../scripts/seed_development_catalogue.py --cleanup --confirm

Both refuse unless APP_ENV=development is set explicitly (environment or backend/.env) and the
database host is local (localhost, 127.0.0.1, ::1 or a docker-compose service name). Nothing runs
this on startup, deploy or migration.

Seeding connects with DATABASE_URL (the runtime role) and goes through the application services,
so every change is validated, priced and audited as if staff and customers made it: the seed
administrator acts for the catalogue, each seed customer places their own cash-on-delivery
orders through the cart and checkout, and the seed administrator moves them through the order
statuses. Product photos come from backend/seed/photos/<slug>.<ext> (position 1) or
<slug>__<n>.<ext> (position n) when present, otherwise plain generated placeholders; they are
sent through the bulk image upload in batches of at most 20 files and processed by the worker,
then the products are activated with the bulk-activate rule (at least one image).

Stores (ADR-014 phase 2): every product belongs to a store. The seed creates the demo
seller stores of scripts/seed_catalogue_data.py (each owner a verified seed customer who
applies through the store service; the seed administrator approves), and shares the seed
products out over them in order. Each product, its variants and opening stock are created by
its store's owner through the seller scope; the administrator only moderates (featured picks,
activation). Cleanup removes the seed stores and their history with the seed people.

Idempotent: the seed keys are in scripts/seed_catalogue_data.py. A rerun creates only what is
missing and reports created/updated/skipped/failed per kind. It never resets the stock or the
prices of existing variants, never touches orders of other customers and never changes the
free-delivery threshold. Policy pages are written only where that language version does not
exist yet, and contact settings only while unset, so staff edits are never overwritten.

Passwords: SEED_STAFF_PASSWORD and SEED_CUSTOMER_PASSWORD (see backend/.env.example) when set;
otherwise a random password per new account, printed once. Existing accounts keep theirs.

Cleanup connects with MIGRATION_DATABASE_URL (the schema owner) and removes, in one transaction,
the seed orders and everything that hangs off them, the seed products' stock, variants and
images (their files are retired to the worker), the seed banners, the seed policy pages and
contact settings that still hold the seed text, and the seed staff and customers. It keeps
categories and brands. It refuses if a seed variant is in an order or a
stock reservation of anyone else, or if a promotion targets a seed product.
"""

from __future__ import annotations

import argparse
import io
import os
import secrets
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, cast

SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from reset_dev_images import explicit_setting, is_local_host  # noqa: E402
from seed_catalogue_data import (  # noqa: E402
    CATALOGUE,
    EMAIL_DOMAIN,
    LOW_STOCK_THRESHOLD,
    OPENING_STOCK,
    SKU_PREFIX,
    Catalogue,
    SeedBanner,
    SeedProduct,
)
from sqlalchemy import create_engine, delete, func, select, text, type_coerce  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.engine import CursorResult, make_url  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.rate_limit import CartRateLimiter, get_cart_rate_limiter  # noqa: E402
from app.core.request_context import RequestContext  # noqa: E402
from app.core.roles import Role, staff_role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.transaction import atomic  # noqa: E402
from app.integrations.media import MediaStorage, get_media_storage  # noqa: E402
from app.models import (  # noqa: E402
    Address,
    Banner,
    Brand,
    Cart,
    CartItem,
    Category,
    DeliveryZone,
    DiscountRedemption,
    DiscountTarget,
    ImportJob,
    InventoryBalance,
    Invoice,
    Job,
    JobItem,
    Order,
    OrderItem,
    OrderStatusHistory,
    Page,
    PaymentAttempt,
    PaymentEvent,
    Product,
    ProductImage,
    ProductReview,
    ProductVariant,
    ReviewToken,
    Setting,
    StaffRoleAssignment,
    StockMovement,
    StockReservation,
    User,
    WishlistItem,
)
from app.models.marketplace import Store, StoreStatusHistory  # noqa: E402
from app.repositories.staff_repository import StaffRepository  # noqa: E402
from app.repositories.store_repository import StoreRepository  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.schemas.address import AddressCreateRequest  # noqa: E402
from app.schemas.auth import RegisterRequest  # noqa: E402
from app.schemas.banners import BannerCreateRequest, BannerUpdateRequest  # noqa: E402
from app.schemas.catalog_admin import BrandCreateRequest, CategoryCreateRequest  # noqa: E402
from app.schemas.checkout import CheckoutRequest  # noqa: E402
from app.schemas.inventory import StockAdjustmentRequest  # noqa: E402
from app.schemas.pages import PageUpdateRequest  # noqa: E402
from app.schemas.product_admin import (  # noqa: E402
    ProductCreateRequest,
    ProductUpdateRequest,
    VariantCreateRequest,
)
from app.schemas.staff import StaffCreateRequest  # noqa: E402
from app.schemas.stores import StoreApplicationRequest, StoreStatusRequest  # noqa: E402
from app.services import bulk_images  # noqa: E402
from app.services.address_service import AddressService  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402
from app.services.banners import BannerService  # noqa: E402
from app.services.cart_service import CartOwner, CartService  # noqa: E402
from app.services.catalog_admin import CatalogAdminService  # noqa: E402
from app.services.catalog_scope import CatalogScope  # noqa: E402
from app.services.checkout_service import CheckoutService  # noqa: E402
from app.services.image_admin import processed_upload  # noqa: E402
from app.services.image_processing import ProcessedImage  # noqa: E402
from app.services.inventory_admin import InventoryAdminService  # noqa: E402
from app.services.media_registry import retire  # noqa: E402
from app.services.order_service import OrderService  # noqa: E402
from app.services.pages import PageService  # noqa: E402
from app.services.product_admin import ProductAdminService, bulk_activate  # noqa: E402
from app.services.review_service import ReviewService  # noqa: E402
from app.services.review_service import author_name as review_author  # noqa: E402
from app.services.settings_service import SettingsService  # noqa: E402
from app.services.staff_service import StaffService  # noqa: E402
from app.services.store_service import StoreService  # noqa: E402

PHOTOS = BACKEND / "seed" / "photos"
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
BATCH_FILES = bulk_images.MAX_FILES  # 20
BATCH_BYTES = 100 * 1024 * 1024
JOB_WAIT_SECONDS = 300
CTX = RequestContext(ip_address=None, user_agent="seed_development_catalogue")
ORDER_PATH = ("received", "confirmed", "processing", "dispatched", "delivered")
REFUSED_ENV = "Refused: the catalogue seed runs only when APP_ENV=development is set explicitly."

# Design tokens (frontend/design/tokens-and-components.css).
NAVY, PRI, LIGHT, BORDER, MUTED, PAGE = (
    "#0D2D52",
    "#0866F5",
    "#EAF3FF",
    "#E2E8F0",
    "#64748B",
    "#F5F8FC",
)


# --------------------------------------------------------------------------------------------
# Report


@dataclass
class Report:
    counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    problems: list[str] = field(default_factory=list)
    passwords: list[tuple[str, str]] = field(default_factory=list)

    def add(self, kind: str, outcome: str, problem: str | None = None) -> None:
        self.counts[kind][outcome] += 1
        if problem:
            self.problems.append(f"{kind}: {problem}")

    def lines(self) -> list[str]:
        out = []
        for kind, counter in self.counts.items():
            parts = ", ".join(
                f"{counter[o]} {o}"
                for o in ("created", "updated", "skipped", "failed")
                if counter[o]
            )
            out.append(f"  {kind:<18} {parts}")
        return out


# --------------------------------------------------------------------------------------------
# Placeholder images: a plain studio look (light background, soft shadow, a simple device
# outline, the name and the category). Deterministic, so a rerun produces the same bytes.


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text_value: str, font, width: int) -> list[str]:
    words, lines, line = text_value.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines[:3]


def _device(draw: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, s: float) -> None:
    """A simple outline of the product type, centred on (cx, cy), scaled by s."""

    def box(w: float, h: float, dy: float = 0, r: float = 24) -> tuple[float, ...]:
        return (cx - w * s / 2, cy - h * s / 2 + dy * s, cx + w * s / 2, cy + h * s / 2 + dy * s)

    line = max(4, int(6 * s))
    if kind == "phones":
        draw.rounded_rectangle(
            box(220, 440), radius=int(36 * s), fill="white", outline=NAVY, width=line
        )
        draw.rounded_rectangle(box(184, 380), radius=int(18 * s), fill=LIGHT)
        draw.rounded_rectangle(box(56, 10, -200), radius=int(5 * s), fill=NAVY)
    elif kind == "laptops":
        draw.rounded_rectangle(
            box(420, 270, -40), radius=int(18 * s), fill="white", outline=NAVY, width=line
        )
        draw.rounded_rectangle(box(376, 226, -40), radius=int(8 * s), fill=LIGHT)
        draw.rounded_rectangle(box(500, 28, 110), radius=int(12 * s), fill=NAVY)
    elif kind == "tvs-audio":
        draw.rounded_rectangle(
            box(520, 310, -30), radius=int(14 * s), fill="white", outline=NAVY, width=line
        )
        draw.rectangle(box(482, 272, -30), fill=LIGHT)
        draw.rectangle(box(24, 60, 155), fill=NAVY)
        draw.rounded_rectangle(box(180, 16, 190), radius=int(8 * s), fill=NAVY)
    elif kind == "home-appliances":
        draw.rounded_rectangle(
            box(300, 460), radius=int(22 * s), fill="white", outline=NAVY, width=line
        )
        draw.line((cx - 150 * s, cy - 70 * s, cx + 150 * s, cy - 70 * s), fill=NAVY, width=line)
        draw.rounded_rectangle(box(14, 70, -150), radius=int(7 * s), fill=PRI)
        draw.rounded_rectangle(box(14, 110, 30), radius=int(7 * s), fill=PRI)
    else:  # accessories
        draw.ellipse(box(330, 330), fill="white", outline=NAVY, width=line)
        draw.ellipse(box(230, 230), fill=LIGHT)
        draw.ellipse(box(70, 70), fill=PRI)


def studio_image(name: str, caption: str, kind: str, size: tuple[int, int] = (1200, 1200)) -> bytes:
    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(height):  # white to the page colour, top to bottom
        t = y / max(1, height - 1)
        shade = tuple(int(255 + (c - 255) * t) for c in (0xF5, 0xF8, 0xFC))
        draw.line((0, y, width, y), fill=shade)
    scale = min(width, height) / 1200
    cx, cy = width // 2, int(height * 0.42)
    draw.ellipse(
        (cx - 330 * scale, cy + 250 * scale, cx + 330 * scale, cy + 300 * scale), fill=BORDER
    )
    _device(draw, kind, cx, cy, scale * 1.15)
    title_font, caption_font = _font(int(52 * scale)), _font(int(30 * scale))
    y = int(height * 0.74)
    caption_width = draw.textlength(caption.upper(), font=caption_font)
    draw.text(((width - caption_width) / 2, y), caption.upper(), font=caption_font, fill=MUTED)
    y += int(52 * scale)
    for line in _wrap(draw, name, title_font, int(width * 0.84)):
        line_width = draw.textlength(line, font=title_font)
        draw.text(((width - line_width) / 2, y), line, font=title_font, fill=NAVY)
        y += int(66 * scale)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def logo_image(name: str) -> bytes:
    image = Image.new("RGB", (800, 400), "white")
    draw = ImageDraw.Draw(image)
    font = _font(110)
    w = draw.textlength(name, font=font)
    draw.text(((800 - w) / 2, 130), name, font=font, fill=NAVY, stroke_width=2, stroke_fill=NAVY)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def banner_image() -> bytes:
    """The right-hand visual of the Main.dc.html hero: devices on a light circle."""
    image = Image.new("RGB", (1600, 1200), LIGHT)
    draw = ImageDraw.Draw(image)
    draw.ellipse((300, 100, 1300, 1100), fill="white")
    draw.ellipse((380, 180, 1220, 1020), outline="#C9DCFB", width=6)
    _device(draw, "laptops", 760, 560, 1.5)
    _device(draw, "phones", 1180, 760, 0.8)
    _device(draw, "accessories", 400, 880, 0.5)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def product_photos(product: SeedProduct, category_name: str) -> list[tuple[str, bytes]]:
    """(file name, bytes) for each photo: backend/seed/photos when present, else a placeholder."""
    found: list[tuple[str, bytes]] = []
    if PHOTOS.is_dir():
        for path in sorted(PHOTOS.iterdir()):
            placement = bulk_images.parse_file_name(path.name)
            if (
                path.is_file()
                and path.suffix.lower() in PHOTO_EXTENSIONS
                and placement is not None
                and placement.slug == product.slug
            ):
                found.append((path.name, path.read_bytes()))
    if found:
        return found
    return [(f"{product.slug}.jpg", studio_image(product.name, category_name, product.category))]


# --------------------------------------------------------------------------------------------
# Seeding


def _new_password(env_name: str, report: Report, email: str) -> str:
    configured = os.environ.get(env_name) or explicit_setting(env_name)
    if configured:
        return configured
    password = f"Seed-{secrets.token_urlsafe(12)}7a"
    report.passwords.append((email, password))
    return password


def _user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def seed_staff(db: Session, data: Catalogue, report: Report) -> User:
    """The seed administrator first (it acts for everything else), then one account per role."""
    admin_spec = next(p for p in data.staff if p.role == Role.ADMINISTRATOR.value)
    admin = _user_by_email(db, admin_spec.email)
    if admin is None:
        with atomic(db):
            admin = StaffRepository.create(
                db,
                full_name=admin_spec.full_name,
                password_hash=hash_password(
                    _new_password("SEED_STAFF_PASSWORD", report, admin_spec.email)
                ),
                role=Role.ADMINISTRATOR.value,
                email=admin_spec.email,
                phone=None,
            )
            db.flush()
            AuditService.log_event(
                db,
                action="staff.seed_create",
                status="success",
                entity_type="user",
                entity_id=admin.id,
                context=CTX,
                details={"role": Role.ADMINISTRATOR.value, "channel": "dev_seed"},
            )
        report.add("staff", "created")
    elif not admin.is_active or staff_role(admin) != Role.ADMINISTRATOR.value:
        raise SystemExit(
            f"Refused: {admin_spec.email} exists but is not an active administrator; "
            "run --cleanup --confirm first."
        )
    else:
        report.add("staff", "skipped")
    for person in data.staff:
        if person is admin_spec:
            continue
        if _user_by_email(db, person.email) is not None:
            report.add("staff", "skipped")
            continue
        assert person.role is not None
        try:
            StaffService.create(
                db,
                admin,
                StaffCreateRequest(
                    email=person.email,
                    full_name=person.full_name,
                    password=_new_password("SEED_STAFF_PASSWORD", report, person.email),
                    role=person.role,  # type: ignore[arg-type]
                ),
                CTX,
            )
            report.add("staff", "created")
        except AppError as exc:
            db.rollback()
            report.add("staff", "failed", f"{person.email}: {exc.message}")
    return admin


def seed_customers(db: Session, data: Catalogue, report: Report) -> dict[str, User]:
    customers: dict[str, User] = {}
    for person in data.customers:
        user = _user_by_email(db, person.email)
        if user is None:
            try:
                req = RegisterRequest(
                    email=person.email,
                    phone=person.phone,
                    full_name=person.full_name,
                    password=_new_password("SEED_CUSTOMER_PASSWORD", report, person.email),
                )
                # Development seed accounts (seed.3sixty.local) are created verified: no
                # verification email can reach them (ADR-006 amendment 2026-11-12).
                with atomic(db):
                    user = UserRepository.create_customer(
                        db,
                        full_name=req.full_name,
                        password_hash=hash_password(req.password),
                        email=req.email,
                        phone=req.phone,
                        email_verified_at=datetime.now(UTC),
                    )
                report.add("customers", "created")
            except IntegrityError:
                db.rollback()
                report.add("customers", "failed", f"{person.email}: email or phone already in use")
                continue
            except AppError as exc:
                db.rollback()
                report.add("customers", "failed", f"{person.email}: {exc.message}")
                continue
        else:
            report.add("customers", "skipped")
        if not db.scalar(select(func.count(Address.id)).where(Address.user_id == user.id)):
            AddressService.create_address(
                db,
                user,
                AddressCreateRequest(
                    label="Home",
                    recipient_name=person.full_name,
                    phone=person.phone or "",
                    province="Kigali City",
                    district=person.district,
                    sector=person.sector,
                    street_address=person.street,
                    is_default=True,
                ),
                CTX,
            )
        customers[person.key] = user
    return customers


def _set_image(
    kind: str,
    report: Report,
    raw: bytes,
    setter: Callable[[ProcessedImage, int, RequestContext], object],
) -> None:
    try:
        setter(processed_upload(raw), len(raw), CTX)
        report.add(kind, "updated")
    except AppError as exc:
        report.add(kind, "failed", f"image: {exc.message}")


def seed_taxonomy(
    db: Session, storage: MediaStorage, admin: User, data: Catalogue, report: Report
) -> tuple[dict[str, Category], dict[str, Brand]]:
    categories: dict[str, Category] = {}
    for spec in data.categories:
        category = db.scalar(select(Category).where(Category.slug == spec.slug))
        if category is None:
            category = CatalogAdminService.create_category(
                db,
                admin,
                CategoryCreateRequest(
                    name=spec.name,
                    slug=spec.slug,
                    sort_order=spec.sort_order,
                    description=spec.description,
                ),
                CTX,
            )
            report.add("categories", "created")
        else:
            report.add("categories", "skipped")
        if category.image_media_id is None:
            _set_image(
                "categories",
                report,
                studio_image(spec.name, spec.description, spec.slug, (900, 900)),
                partial(CatalogAdminService.set_category_image, db, storage, admin, category.id),
            )
        categories[spec.slug] = category
    brands: dict[str, Brand] = {}
    for brand_spec in data.brands:
        brand = db.scalar(select(Brand).where(Brand.slug == brand_spec.slug))
        if brand is None:
            # A brand belongs to the categories of its products (ADR-012 decision 9).
            homes = sorted({p.category for p in data.products if p.brand == brand_spec.slug})
            home_ids = [categories[s].id for s in homes if s in categories] or [
                next(iter(categories.values())).id
            ]
            brand = CatalogAdminService.create_brand(
                db,
                admin,
                BrandCreateRequest(
                    name=brand_spec.name, slug=brand_spec.slug, category_ids=home_ids
                ),
                CTX,
            )
            report.add("brands", "created")
        else:
            report.add("brands", "skipped")
        if brand.logo_media_id is None:
            _set_image(
                "brands",
                report,
                logo_image(brand_spec.name),
                partial(CatalogAdminService.set_brand_logo, db, storage, admin, brand.id),
            )
        brands[brand_spec.slug] = brand
    return categories, brands


def is_seed_product(db: Session, product_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(func.count(ProductVariant.id)).where(
                ProductVariant.product_id == product_id,
                ProductVariant.sku.startswith(SKU_PREFIX),
            )
        )
    )


PLATFORM = CatalogScope.platform()


def seed_stores(db: Session, admin: User, data: Catalogue, report: Report) -> list[Store]:
    """The demo seller stores, approved (ADR-014 phase 2). Existing ones are kept as they are."""
    stores: list[Store] = []
    for spec in data.stores:
        owner = _user_by_email(db, spec.email)
        try:
            if owner is None:
                with atomic(db):
                    owner = UserRepository.create_customer(
                        db,
                        full_name=spec.owner_name,
                        password_hash=hash_password(
                            _new_password("SEED_CUSTOMER_PASSWORD", report, spec.email)
                        ),
                        email=spec.email,
                        phone=spec.phone,
                        email_verified_at=datetime.now(UTC),
                    )
            store = StoreRepository.get_by_owner(db, owner.id)
            if store is None:
                store = StoreService.apply(
                    db,
                    owner,
                    StoreApplicationRequest(
                        name=spec.name,
                        description=spec.description,
                        contact_email=spec.email,
                        contact_phone=spec.phone,
                        district=spec.district,
                        sector=spec.sector,
                    ),
                    CTX,
                )
                report.add("stores", "created")
            else:
                report.add("stores", "skipped")
            if store.status == "pending":
                store = StoreService.change_status(
                    db, admin, store.id, StoreStatusRequest(status="approved"), CTX
                )
                report.add("store approvals", "updated")
        except (AppError, IntegrityError) as exc:
            db.rollback()
            report.add("stores", "failed", f"{spec.name}: {getattr(exc, 'message', 'conflict')}")
            continue
        if store.status == "approved":
            stores.append(store)
        else:
            report.add("stores", "failed", f"{spec.name}: the store is {store.status}")
    return stores


def seed_products(
    db: Session,
    admin: User,
    data: Catalogue,
    categories: dict[str, Category],
    brands: dict[str, Brand],
    report: Report,
    stores: list[Store],
) -> dict[str, Product]:
    products: dict[str, Product] = {}
    if not stores:
        report.add("products", "failed", "no approved seed store to own the products")
        return products
    for index, spec in enumerate(data.products):
        product = db.scalar(select(Product).where(Product.slug == spec.slug))
        if product is not None and not is_seed_product(db, product.id):
            report.add("products", "failed", f"{spec.slug}: the slug belongs to a non-seed product")
            continue
        try:
            if product is None:
                store = stores[index % len(stores)]
                product = ProductAdminService.create_product(
                    db,
                    store.owner,
                    ProductCreateRequest(
                        name=spec.name,
                        slug=spec.slug,
                        category_id=categories[spec.category].id,
                        brand_id=brands[spec.brand].id,
                        model=spec.model,
                        description=spec.description,
                        specifications=dict(spec.specifications),
                        warranty_text=spec.warranty,
                    ),
                    CTX,
                    scope=CatalogScope.store(store.id),
                )
                if spec.featured:  # merchandising is the administrator's (ADR-014 decision 5)
                    product = ProductAdminService.update_product(
                        db,
                        admin,
                        product.id,
                        ProductUpdateRequest(is_featured=True),
                        CTX,
                        scope=PLATFORM,
                    )
                report.add("products", "created")
            else:
                report.add("products", "skipped")
        except AppError as exc:
            db.rollback()
            report.add("products", "failed", f"{spec.slug}: {exc.message}")
            continue
        for variant_spec in spec.variants:
            existing = db.scalar(
                select(ProductVariant).where(
                    func.lower(ProductVariant.sku) == variant_spec.sku.lower()
                )
            )
            if existing is not None:
                if existing.product_id != product.id:
                    report.add("variants", "failed", f"{variant_spec.sku}: used by another product")
                else:
                    report.add("variants", "skipped")  # never repriced or restocked
                continue
            owner = db.get(Store, product.store_id)
            assert owner is not None
            seller = owner.owner
            scope = CatalogScope.store(owner.id)
            try:
                ProductAdminService.create_variant(
                    db,
                    seller,
                    product.id,
                    VariantCreateRequest(
                        sku=variant_spec.sku,
                        name=variant_spec.name,
                        attributes=dict(variant_spec.attributes),
                        price=variant_spec.price,
                        compare_at_price=variant_spec.compare_at_price,
                        low_stock_threshold=LOW_STOCK_THRESHOLD,
                    ),
                    CTX,
                    scope=scope,
                )
                report.add("variants", "created")
                quantity = OPENING_STOCK[variant_spec.stock]
                if quantity:
                    InventoryAdminService.adjust(
                        db,
                        seller,
                        variant_spec.sku,
                        StockAdjustmentRequest(
                            reason="receipt",
                            quantity_delta=quantity,
                            note="Development seed: opening stock",
                        ),
                        f"seed-receipt-{variant_spec.sku}",
                        CTX,
                        scope=scope,
                    )
                    report.add("stock", "created")
            except AppError as exc:
                db.rollback()
                report.add("variants", "failed", f"{variant_spec.sku}: {exc.message}")
        products[spec.slug] = product
    return products


def _has_images(db: Session, product_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(select(func.count(ProductImage.id)).where(ProductImage.product_id == product_id))
    )


def _batches(files: list[tuple[str, bytes]]) -> Iterable[list[tuple[str, bytes]]]:
    batch: list[tuple[str, bytes]] = []
    size = 0
    for name, raw in files:
        if batch and (len(batch) == BATCH_FILES or size + len(raw) > BATCH_BYTES):
            yield batch
            batch, size = [], 0
        batch.append((name, raw))
        size += len(raw)
    if batch:
        yield batch


def wait_for_worker(db: Session, job_ids: list[uuid.UUID]) -> None:
    """Wait for the worker process to finish the jobs (it runs next to the API)."""
    deadline = time.monotonic() + JOB_WAIT_SECONDS
    while True:
        db.expire_all()
        open_jobs = db.scalar(
            select(func.count(Job.id)).where(Job.id.in_(job_ids), Job.state != "finished")
        )
        if not open_jobs:
            return
        if time.monotonic() > deadline:
            raise SystemExit(
                f"Timed out after {JOB_WAIT_SECONDS} s waiting for {open_jobs} bulk image "
                "job(s). Is the worker running (uv run python -m app.worker)? Rerun the seed "
                "afterwards; it continues where it stopped."
            )
        time.sleep(1)


def seed_images(
    db: Session,
    storage: MediaStorage,
    admin: User,
    data: Catalogue,
    products: dict[str, Product],
    categories: dict[str, Category],
    report: Report,
    run_jobs: Callable[[Session, list[uuid.UUID]], None],
) -> None:
    names = {c.slug: c.name for c in data.categories}
    files: list[tuple[str, bytes]] = []
    for spec in data.products:
        product = products.get(spec.slug)
        if product is None:
            continue
        if _has_images(db, product.id):
            report.add("product images", "skipped")
            continue
        files.extend(product_photos(spec, names[spec.category]))
    job_ids = []
    for batch in _batches(files):
        uploads = [bulk_images.Upload(n, io.BytesIO(raw), len(raw)) for n, raw in batch]
        job = bulk_images.start_bulk_upload(db, storage, admin, uploads)
        job_ids.append(job.id)
    if job_ids:
        run_jobs(db, job_ids)
        db.expire_all()
        for item in db.scalars(select(JobItem).where(JobItem.job_id.in_(job_ids))):
            outcome = (item.result or {}).get("outcome", item.state)
            if item.state == "done":
                report.add("product images", "created" if outcome == "added" else "updated")
            else:
                filename = (item.result or {}).get("filename") or item.payload.get("public", {})
                report.add("product images", "failed", f"{filename}: {item.error or outcome}")
    drafts = [
        p.id
        for p in db.scalars(
            select(Product).where(
                Product.id.in_([p.id for p in products.values()]), Product.status == "draft"
            )
        )
    ]
    if drafts:
        for product_id, outcome in bulk_activate(db, admin, drafts, CTX, scope=PLATFORM):
            if outcome == "activated":
                report.add("activation", "updated")
            else:
                report.add("activation", "failed", f"{product_id}: {outcome}")


def seed_banners(
    db: Session, storage: MediaStorage, admin: User, data: Catalogue, report: Report
) -> None:
    for spec in data.banners:
        banner = db.scalar(select(Banner).where(Banner.title_en == spec.title_en))
        if banner is None:
            banner = BannerService.create(db, admin, _banner_request(spec), CTX)
            report.add("banners", "created")
        else:
            report.add("banners", "skipped")
        if banner.image_media_id is None:
            raw = banner_image()
            BannerService.set_image(
                db, storage, admin, banner.id, processed_upload(raw), len(raw), CTX
            )
        if not banner.is_active:
            BannerService.update(db, admin, banner.id, BannerUpdateRequest(is_active=True), CTX)
            report.add("banners", "updated")


def seed_content(db: Session, admin: User, data: Catalogue, report: Report) -> None:
    """Draft policy pages (published, each marked as a draft in its text) and the sample store
    contact (module 19). Existing pages and set contact values are left alone."""
    for spec in data.pages:
        exists = db.scalar(
            select(Page.id).where(Page.slug == spec.slug, Page.locale == spec.locale)
        )
        if exists is not None:
            report.add("pages", "skipped")
            continue
        request = PageUpdateRequest(title=spec.title, body=spec.body, is_published=True)
        PageService.put(db, admin, spec.slug, spec.locale, request, CTX)
        report.add("pages", "created")
    keys = [key for key, _ in data.contact]
    taken = set(db.scalars(select(Setting.key).where(Setting.key.in_(keys))))
    missing = {key: value for key, value in data.contact if key not in taken}
    if missing:
        SettingsService.update(db, admin, missing, CTX)
    for key in keys:
        report.add("contact settings", "skipped" if key in taken else "created")


def _banner_request(spec: SeedBanner) -> BannerCreateRequest:
    return BannerCreateRequest(
        title_en=spec.title_en,
        title_rw=spec.title_rw,
        overline_en=spec.overline_en,
        overline_rw=spec.overline_rw,
        subtitle_en=spec.subtitle_en,
        subtitle_rw=spec.subtitle_rw,
        cta_label_en=spec.cta_label_en,
        cta_label_rw=spec.cta_label_rw,
        cta_url=spec.cta_url,
        position=spec.position,
    )


def _seed_order(db: Session, user: User, key: str) -> Order | None:
    return db.scalar(
        select(Order).where(Order.user_id == user.id, Order.checkout_idempotency_key.endswith(key))
    )


def seed_orders(
    db: Session,
    admin: User,
    data: Catalogue,
    customers: dict[str, User],
    limiter: CartRateLimiter,
    report: Report,
) -> None:
    variants = {
        v.sku: v.id
        for v in db.scalars(select(ProductVariant).where(ProductVariant.sku.startswith(SKU_PREFIX)))
    }
    zones = {z.district for z in db.scalars(select(DeliveryZone).where(DeliveryZone.is_active))}
    for index, spec in enumerate(data.orders, start=1):
        key = f"seed-order-{index:02d}"
        user = customers.get(spec.customer)
        person = next(p for p in data.customers if p.key == spec.customer)
        if user is None:
            report.add("orders", "failed", f"{key}: customer {spec.customer} is missing")
            continue
        order = _seed_order(db, user, key)
        if order is None:
            if person.district not in zones:
                report.add(
                    "orders",
                    "failed",
                    f"{key}: no active delivery zone for {person.district}; run seed_dev.py first",
                )
                continue
            try:
                order = _place_order(db, user, spec.lines, spec.note, variants, limiter, key)
                report.add("orders", "created")
            except AppError as exc:
                db.rollback()
                report.add("orders", "failed", f"{key}: {exc.message}")
                continue
        else:
            report.add("orders", "skipped")
        try:
            _advance(db, admin, order, spec.status, report)
        except AppError as exc:
            db.rollback()
            report.add("order statuses", "failed", f"{key}: {exc.message}")


def _place_order(
    db: Session,
    user: User,
    lines: tuple[tuple[str, int], ...],
    note: str | None,
    variants: dict[str, uuid.UUID],
    limiter: CartRateLimiter,
    key: str,
) -> Order:
    owner = CartOwner(user=user)
    for line in CartService.get(db, owner, None).lines:  # leftovers of an interrupted run
        CartService.remove_item(db, owner, line.id)
    for code, quantity in lines:
        CartService.add_item(db, owner, variants[SKU_PREFIX + code], quantity, limiter, CTX)
    address = db.scalar(select(Address).where(Address.user_id == user.id, Address.is_default))
    assert address is not None
    response = CheckoutService.checkout(
        db,
        owner,
        CheckoutRequest(address_id=address.id, payment_method="cash_on_delivery", note=note),
        key,
        CTX,
    )
    order = db.get(Order, response.order.id)
    assert order is not None
    return order


def _advance(db: Session, admin: User, order: Order, target: str, report: Report) -> None:
    if target == "cancelled":
        steps = [] if order.status == "cancelled" else ["cancelled"]
    elif order.status == "cancelled" or order.status not in ORDER_PATH:
        steps = []
    else:
        steps = list(ORDER_PATH[ORDER_PATH.index(order.status) + 1 : ORDER_PATH.index(target) + 1])
    for status in steps:
        OrderService.change_status(
            db,
            order_id=order.id,
            actor=admin,
            new_status=status,
            ctx=CTX,
            reason="Development seed" if status == "cancelled" else None,
        )
        report.add("order statuses", "updated")


def seed_reviews(
    db: Session, admin: User, data: Catalogue, customers: dict[str, User], report: Report
) -> None:
    """A review per listed line of a delivered seed order, sent as the customer would (pending),
    then approved or rejected through the review service, which recalculates the product's
    rating and audits the decision. An item that already has a review is skipped."""
    for spec in data.reviews:
        key = f"seed-order-{spec.order:02d}"
        order_spec = data.orders[spec.order - 1]
        user = customers.get(order_spec.customer)
        order = _seed_order(db, user, key) if user is not None else None
        if order is None or order.status != "delivered":
            report.add("reviews", "failed", f"{key}: no delivered order to review")
            continue
        item = next((i for i in order.items if i.sku_snapshot == SKU_PREFIX + spec.code), None)
        if item is None or item.product_id is None:
            report.add("reviews", "failed", f"{key}: no line {spec.code}")
            continue
        if db.scalar(select(ProductReview.id).where(ProductReview.order_item_id == item.id)):
            report.add("reviews", "skipped")
            continue
        with atomic(db):
            review = ProductReview(
                product_id=item.product_id,
                order_item_id=item.id,
                user_id=order.user_id,
                rating=spec.rating,
                title=spec.title,
                body=spec.body,
                author_name=review_author(order.recipient_name),
                status="pending",
            )
            db.add(review)
        if spec.status != "pending":
            ReviewService.moderate(db, review.id, spec.status, spec.reason, admin, CTX)
        report.add("reviews", "created")


def default_run_jobs(db: Session, job_ids: list[uuid.UUID]) -> None:
    wait_for_worker(db, job_ids)


def seed(
    db: Session,
    storage: MediaStorage,
    limiter: CartRateLimiter,
    data: Catalogue = CATALOGUE,
    run_jobs: Callable[[Session, list[uuid.UUID]], None] = default_run_jobs,
    report: Report | None = None,
) -> Report:
    report = report if report is not None else Report()
    admin = seed_staff(db, data, report)
    customers = seed_customers(db, data, report)
    categories, brands = seed_taxonomy(db, storage, admin, data, report)
    stores = seed_stores(db, admin, data, report)
    products = seed_products(db, admin, data, categories, brands, report, stores)
    seed_images(db, storage, admin, data, products, categories, report, run_jobs)
    seed_banners(db, storage, admin, data, report)
    seed_content(db, admin, data, report)
    seed_orders(db, admin, data, customers, limiter, report)
    seed_reviews(db, admin, data, customers, report)
    return report


# --------------------------------------------------------------------------------------------
# Cleanup


class CleanupRefused(Exception):
    pass


def _ids(db: Session, statement) -> list[uuid.UUID]:
    return list(db.scalars(statement))


def cleanup(db: Session, data: Catalogue = CATALOGUE) -> dict[str, int]:
    """Remove the seed data in one transaction (schema-owner session). Returns row counts."""
    counts: dict[str, int] = {}

    def run(label: str, statement) -> None:
        result = cast(CursorResult[Any], db.execute(statement))
        counts[label] = counts.get(label, 0) + (result.rowcount or 0)

    with atomic(db):
        slugs = [p.slug for p in data.products]
        product_ids = _ids(
            db,
            select(Product.id).where(
                Product.slug.in_(slugs),
                Product.id.in_(
                    select(ProductVariant.product_id).where(
                        ProductVariant.sku.startswith(SKU_PREFIX)
                    )
                ),
            ),
        )
        variant_ids = _ids(
            db, select(ProductVariant.id).where(ProductVariant.product_id.in_(product_ids))
        )
        people = _ids(db, select(User.id).where(User.email.endswith(f"@{EMAIL_DOMAIN}")))
        order_ids = _ids(db, select(Order.id).where(Order.user_id.in_(people)))

        foreign_items = db.scalar(
            select(func.count(OrderItem.id)).where(
                OrderItem.variant_id.in_(variant_ids), OrderItem.order_id.not_in(order_ids)
            )
        )
        foreign_holds = db.scalar(
            select(func.count(StockReservation.id)).where(
                StockReservation.variant_id.in_(variant_ids),
                StockReservation.order_id.not_in(order_ids),
            )
        )
        targets = db.scalar(
            select(func.count(DiscountTarget.id)).where(DiscountTarget.product_id.in_(product_ids))
        )
        if foreign_items or foreign_holds or targets:
            raise CleanupRefused(
                "Refused: seed products are used outside the seed "
                f"({foreign_items} order lines and {foreign_holds} stock reservations of other "
                f"customers, {targets} promotion targets). Nothing was removed."
            )

        # Carts: seed variants in anyone's cart, then the seed people's carts.
        run("cart lines", delete(CartItem).where(CartItem.variant_id.in_(variant_ids)))
        run("carts", delete(Cart).where(Cart.user_id.in_(people)))
        # Wishlists: the seed people's, and seed products in anyone's (module 21).
        run(
            "wishlist items",
            delete(WishlistItem).where(
                WishlistItem.user_id.in_(people) | WishlistItem.product_id.in_(product_ids)
            ),
        )

        # Orders. stock_reservations rows are never deleted by the application (the guard
        # trigger refuses). The guard lets the owner account delete them only while
        # app.dev_seed_cleanup is 'on'; SET LOCAL ends with this transaction (migration
        # b4e7d1a9c3f2). The runtime role has no DELETE privilege at all.
        db.execute(text("SET LOCAL app.dev_seed_cleanup = 'on'"))
        run(
            "stock reservations",
            delete(StockReservation).where(StockReservation.order_id.in_(order_ids)),
        )
        db.execute(text("SET LOCAL app.dev_seed_cleanup = 'off'"))
        # Reviews and review links (module 20) of the seed orders' items or seed products.
        seed_items = select(OrderItem.id).where(OrderItem.order_id.in_(order_ids))
        run(
            "product reviews",
            delete(ProductReview).where(
                ProductReview.order_item_id.in_(seed_items)
                | ProductReview.product_id.in_(product_ids)
            ),
        )
        run("review links", delete(ReviewToken).where(ReviewToken.order_item_id.in_(seed_items)))
        by_order = (
            ("order status history", OrderStatusHistory),
            ("discount redemptions", DiscountRedemption),
            ("invoices", Invoice),
        )
        for label, model in by_order:
            run(label, delete(model).where(model.order_id.in_(order_ids)))
        attempts = select(PaymentAttempt.id).where(PaymentAttempt.order_id.in_(order_ids))
        run("payment events", delete(PaymentEvent).where(PaymentEvent.attempt_id.in_(attempts)))
        run(
            "payment attempts", delete(PaymentAttempt).where(PaymentAttempt.order_id.in_(order_ids))
        )
        run("order lines", delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
        run("orders", delete(Order).where(Order.id.in_(order_ids)))

        # Stock, images (files retired to the worker), variants, products.
        run(
            "stock movements",
            delete(StockMovement).where(StockMovement.variant_id.in_(variant_ids)),
        )
        run(
            "stock balances",
            delete(InventoryBalance).where(InventoryBalance.variant_id.in_(variant_ids)),
        )
        images = db.execute(
            select(
                ProductImage.id, ProductImage.public_media_id, ProductImage.original_media_id
            ).where(ProductImage.product_id.in_(product_ids))
        ).all()
        run("product images", delete(ProductImage).where(ProductImage.product_id.in_(product_ids)))
        retire(db, [m for row in images for m in row[1:]])
        run("variants", delete(ProductVariant).where(ProductVariant.id.in_(variant_ids)))
        run("products", delete(Product).where(Product.id.in_(product_ids)))

        # Seed stores (ADR-014 phase 2), once no product of theirs is left.
        store_ids = _ids(db, select(Store.id).where(Store.owner_user_id.in_(people)))
        left = db.scalar(select(func.count(Product.id)).where(Product.store_id.in_(store_ids)))
        if left:
            raise CleanupRefused(
                f"Refused: the seed stores own {left} products that are not seed products. "
                "Nothing was removed."
            )
        media = db.execute(
            select(
                Store.logo_media_id,
                Store.logo_original_media_id,
                Store.cover_media_id,
                Store.cover_original_media_id,
            ).where(Store.id.in_(store_ids))
        ).all()
        run(
            "store history",
            delete(StoreStatusHistory).where(StoreStatusHistory.store_id.in_(store_ids)),
        )
        run("stores", delete(Store).where(Store.id.in_(store_ids)))
        retire(db, [m for row in media for m in row if m is not None])

        # Banners.
        titles = [b.title_en for b in data.banners]
        banners = db.execute(
            select(Banner.id, Banner.image_media_id, Banner.image_original_media_id).where(
                Banner.title_en.in_(titles)
            )
        ).all()
        run("banners", delete(Banner).where(Banner.title_en.in_(titles)))
        retire(db, [m for row in banners for m in row[1:]])

        # Policy pages and contact settings that still hold the seed text (module 19).
        for spec in data.pages:
            run(
                "pages",
                delete(Page).where(
                    Page.slug == spec.slug, Page.locale == spec.locale, Page.body == spec.body
                ),
            )
        for key, value in data.contact:
            run(
                "contact settings",
                delete(Setting).where(
                    Setting.key == key, Setting.value == type_coerce(value, JSONB)
                ),
            )

        # Seed staff (their jobs and import jobs first) and seed customers.
        run("jobs", delete(Job).where(Job.created_by_user_id.in_(people)))
        run("import jobs", delete(ImportJob).where(ImportJob.created_by_user_id.in_(people)))
        run("addresses", delete(Address).where(Address.user_id.in_(people)))
        run(
            "staff roles",
            delete(StaffRoleAssignment).where(StaffRoleAssignment.user_id.in_(people)),
        )
        run("people", delete(User).where(User.id.in_(people)))
        AuditService.log_event(
            db,
            action="dev_seed.cleanup",
            status="success",
            entity_type="dev_seed",
            entity_id=uuid.UUID(int=0),
            context=CTX,
            details={k: v for k, v in counts.items() if v},
        )
    return counts


# --------------------------------------------------------------------------------------------
# Entry point


def guard(url_setting: str) -> str | None:
    """None when allowed; otherwise the refusal message."""
    if explicit_setting("APP_ENV") != "development":
        return REFUSED_ENV
    if get_settings().app_env != "development":
        return REFUSED_ENV
    url = explicit_setting(url_setting)
    if url is None:
        return f"Refused: {url_setting} is not set."
    if not is_local_host(make_url(url).host):
        return "Refused: the database host is not local."
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="required: really write")
    parser.add_argument("--cleanup", action="store_true", help="remove the seed data instead")
    args = parser.parse_args(argv)
    url_setting = "MIGRATION_DATABASE_URL" if args.cleanup else "DATABASE_URL"
    refusal = guard(url_setting)
    if refusal is None and not args.confirm:
        refusal = "Refused: pass --confirm."
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2
    url = explicit_setting(url_setting)
    assert url is not None
    engine = create_engine(make_url(url))
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
            if args.cleanup:
                try:
                    counts = cleanup(db)
                except CleanupRefused as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                removed = ", ".join(f"{n} {label}" for label, n in counts.items() if n)
                print(f"Removed {removed or 'nothing'}.")
                print("Categories and brands are kept. The worker deletes the retired files.")
                return 0
            report = Report()
            try:
                seed(db, get_media_storage(), get_cart_rate_limiter(), report=report)
            finally:  # also after an error, so new accounts' passwords are never lost
                print_report(report)
    finally:
        engine.dispose()
    failed = sum(c["failed"] for c in report.counts.values())
    return 1 if failed else 0


def print_report(report: Report) -> None:
    print("Development catalogue seed:")
    print("\n".join(report.lines()))
    for problem in report.problems:
        print(f"  ! {problem}")
    if report.passwords:
        print("New accounts (passwords are shown only now):")
        for email, password in report.passwords:
            print(f"  {email}  {password}")


if __name__ == "__main__":
    sys.exit(main())
