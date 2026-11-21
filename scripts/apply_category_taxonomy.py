"""Apply the approved category taxonomy (category hierarchy, ADR-012; mapping approved by the
project owner on 2026-11-16): main categories, their subcategories, the new brands, the brand
names TECNO and OPPO, the brands each main category's menu lists, and the development products
moved into subcategories.

Run from backend/, with the API database migrated and the seed administrator present
(scripts/seed_development_catalogue.py):

    uv run python ../scripts/apply_category_taxonomy.py            # dry run: prints the plan
    uv run python ../scripts/apply_category_taxonomy.py --confirm  # applies it

It refuses unless APP_ENV=development is set explicitly (environment or backend/.env) and the
database host is local. Nothing runs this on startup, deploy or migration.

Every change goes through the application services as the seed administrator, so it is
validated and audited like a change made in the admin. Re-runnable: what already matches is
skipped. It renames main categories only while they still have their old name, re-parents a
subcategory only when it is not where the mapping puts it, and moves a product only while it is
still in the category the mapping moves it from, so changes staff made are never overwritten
(they are reported). It never deletes anything and never changes a product's brand.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))

from reset_dev_images import explicit_setting, is_local_host  # noqa: E402
from seed_catalogue_data import CATALOGUE  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.request_context import RequestContext  # noqa: E402
from app.core.roles import Role  # noqa: E402
from app.models import Brand, Category, CategoryMenuBrand, Product, User  # noqa: E402
from app.schemas.catalog_admin import (  # noqa: E402
    BrandCreateRequest,
    BrandUpdateRequest,
    CategoryCreateRequest,
    CategoryMenuBrandsRequest,
    CategoryUpdateRequest,
)
from app.schemas.product_admin import ProductUpdateRequest  # noqa: E402
from app.services.catalog_admin import CatalogAdminService  # noqa: E402
from app.services.product_admin import ProductAdminService  # noqa: E402

CTX = RequestContext(ip_address=None, user_agent="apply_category_taxonomy")

# Main categories in menu order: (slug, name, old name it may be renamed from). The short names
# are the owner's (2026-11-17, for the store menu; they apply everywhere). Slugs stay.
MAIN: tuple[tuple[str, str, str | None], ...] = (
    ("phones", "Phones", "Phones & Tablets"),
    ("laptops", "Laptops", "Laptops & Computers"),
    ("tvs-audio", "TVs", "TVs & Audio"),
    ("home-appliances", "Home Appliances", None),
    ("accessories", "Accessories", None),
    ("cameras-photography", "Cameras", "Cameras & Photography"),
)

# Subcategories per main category, in order: (slug, name).
SUBCATEGORIES: dict[str, tuple[tuple[str, str], ...]] = {
    "phones": (("smartphones", "Smartphones"), ("tablets", "Tablets")),
    # Pending the business owner's confirmation (approved for now on 2026-11-16).
    "laptops": (
        ("notebooks", "Laptops"),  # "laptops" is the main category's slug
        ("gaming-laptops", "Gaming Laptops"),
        ("desktops-all-in-ones", "Desktops & All-in-Ones"),
        ("monitors", "Monitors"),
    ),
    "tvs-audio": (
        ("televisions", "Televisions"),
        ("speakers", "Speakers"),
        ("soundbars", "Soundbars"),
        ("headphones-earbuds", "Headphones & Earbuds"),
    ),
    "home-appliances": tuple(
        (name.lower().replace(" ", "-"), name)
        for name in (
            "Refrigerators",
            "Freezers",
            "Washing Machines",
            "Dryers",
            "Air Conditioners",
            "Fans",
            "Microwaves",
            "Electric Ovens",
            "Dishwashers",
            "Vacuum Cleaners",
            "Water Dispensers",
            "Water Heaters",
            "Irons",
            "Air Purifiers",
            "Generators",
        )
    ),
    "accessories": (
        ("phone-cases-covers", "Phone Cases & Covers"),
        ("screen-protectors", "Screen Protectors"),
        ("phone-chargers", "Phone Chargers"),
        ("charging-cables", "Charging Cables"),
        ("wireless-chargers", "Wireless Chargers"),
        ("power-banks", "Power Banks"),
        ("keyboards", "Keyboards"),
        ("computer-mice", "Computer Mice"),
        ("mouse-pads", "Mouse Pads"),
        ("laptop-bags-backpacks", "Laptop Bags & Backpacks"),
        ("laptop-stands", "Laptop Stands"),
        ("laptop-cooling-pads", "Laptop Cooling Pads"),
        ("usb-flash-drives", "USB Flash Drives"),
        ("memory-cards", "Memory Cards"),
        ("external-hard-drives", "External Hard Drives"),
        ("external-ssds", "External SSDs"),
        ("usb-hubs-adapters", "USB Hubs & Adapters"),
        ("hdmi-cables", "HDMI Cables"),
        ("webcams", "Webcams"),
        ("phone-holders-stands", "Phone Holders & Stands"),
        ("smartwatch-bands", "Smartwatch Bands"),
        ("stylus-pens", "Stylus Pens"),
        ("gaming-accessories", "Gaming Accessories"),
    ),
    "cameras-photography": (
        ("cameras", "Cameras"),
        ("camera-lenses", "Camera Lenses"),
        ("camera-tripods", "Camera Tripods"),
        ("camera-gimbals", "Camera Gimbals"),
        ("camera-flashes", "Camera Flashes"),
        ("camera-bags", "Camera Bags"),
        ("camera-batteries", "Camera Batteries"),
        ("ring-lights", "Ring Lights"),
        ("studio-lighting", "Studio Lighting"),
        ("drones", "Drones"),
        ("camera-microphones", "Camera Microphones"),
    ),
}

NEW_BRANDS: tuple[tuple[str, str], ...] = tuple(
    (name.lower().replace(" ", "-"), name)
    for name in (
        "Google", "Oppo", "Vivo", "Huawei", "Nokia", "OnePlus", "Motorola", "Realme", "Itel",
        "Honor", "ASUS", "Acer", "MSI", "Microsoft", "Razer", "Gigabyte", "Sony", "TCL",
        "Skyworth", "Toshiba", "Philips", "Panasonic", "Bose", "Harman Kardon", "Marshall",
        "Beats", "Canon", "Nikon", "Fujifilm", "GoPro", "DJI", "Insta360", "Olympus",
        "Hasselblad",
    )
)  # fmt: skip

# The main category each new brand belongs to (ADR-012 decision 9, 2026-11-17), by the group
# it was listed in above.
NEW_BRAND_CATEGORY: dict[str, str] = {
    **dict.fromkeys(
        ("google", "oppo", "vivo", "huawei", "nokia", "oneplus", "motorola", "realme", "itel",
         "honor"),
        "phones",
    ),
    **dict.fromkeys(("asus", "acer", "msi", "microsoft", "razer", "gigabyte"), "laptops"),
    **dict.fromkeys(
        ("sony", "tcl", "skyworth", "toshiba", "philips", "panasonic", "bose", "harman-kardon",
         "marshall", "beats"),
        "tvs-audio",
    ),
    **dict.fromkeys(
        ("canon", "nikon", "fujifilm", "gopro", "dji", "insta360", "olympus", "hasselblad"),
        "cameras-photography",
    ),
}  # fmt: skip

# Product moves: product slug -> (from category, to category). Products not listed stay where
# they are (the air fryer in Home Appliances and the Galaxy Watch 6 in Accessories).
_PHONES = (
    "apple-iphone-13", "apple-iphone-15", "infinix-hot-40i", "infinix-zero-30-5g",
    "samsung-galaxy-a15", "samsung-galaxy-a35-5g", "samsung-galaxy-a55-5g", "samsung-galaxy-s24",
    "tecno-camon-30", "tecno-spark-20", "xiaomi-redmi-13c", "xiaomi-redmi-note-13-pro",
)  # fmt: skip
_LAPTOPS = (
    "apple-macbook-air-13-m2", "dell-inspiron-15", "dell-latitude-5440", "hp-250-g9",
    "hp-pavilion-15", "lenovo-ideapad-slim-3", "lenovo-thinkpad-e14",
)  # fmt: skip
# Brand names as the owner listed them (2026-11-16): (slug, old name, new name). Slugs stay.
BRAND_RENAMES: tuple[tuple[str, str, str], ...] = (
    ("tecno", "Tecno", "TECNO"),
    ("oppo", "Oppo", "OPPO"),
)

# The brands the "All Categories" menu lists per main category, in order (approved
# 2026-11-16). Set only while the category has no list yet, so staff changes are kept.
MENU_BRANDS: dict[str, tuple[str, ...]] = {
    "phones": (
        "apple", "samsung", "xiaomi", "tecno", "infinix",
        "huawei", "google", "oppo", "vivo", "motorola",
    ),
    "laptops": (
        "apple", "hp", "dell", "lenovo", "asus",
        "acer", "microsoft", "msi", "samsung", "huawei",
    ),
    # TVs & Audio lists brands too (owner's list, 2026-11-16); the other main categories have no
    # list, so their menu lists their subcategories.
    "tvs-audio": (
        "samsung", "lg", "hisense", "sony", "tcl",
        "philips", "panasonic", "jbl", "bose", "xiaomi",
    ),
}  # fmt: skip

# Earlier defaults this script set: a list still equal to one of them is replaced by the list
# above; any other list was changed by staff and is kept.
PREVIOUS_MENU_BRANDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "tvs-audio": (("samsung", "lg", "hisense", "jbl", "apple", "xiaomi"),),
}

MOVES: dict[str, tuple[str, str]] = {
    **{slug: ("phones", "smartphones") for slug in _PHONES},
    **{slug: ("laptops", "notebooks") for slug in _LAPTOPS},
    "hp-victus-15": ("laptops", "gaming-laptops"),
    "samsung-65-crystal-uhd-tv": ("tvs-audio", "televisions"),
    "lg-32-hd-smart-tv": ("tvs-audio", "televisions"),
    "lg-55-4k-smart-tv": ("tvs-audio", "televisions"),
    "hisense-43-smart-tv": ("tvs-audio", "televisions"),
    "samsung-hw-b550-soundbar": ("tvs-audio", "soundbars"),
    "hisense-hs218-soundbar": ("tvs-audio", "soundbars"),
    "jbl-charge-5": ("tvs-audio", "speakers"),
    "jbl-flip-6": ("tvs-audio", "speakers"),
    "lg-inverter-refrigerator-420l": ("home-appliances", "refrigerators"),
    "hisense-205l-refrigerator": ("home-appliances", "refrigerators"),
    "lg-8kg-front-load-washer": ("home-appliances", "washing-machines"),
    "hisense-1-5hp-split-ac": ("home-appliances", "air-conditioners"),
    "samsung-20l-microwave": ("home-appliances", "microwaves"),
    "anker-nano-20w-charger": ("accessories", "phone-chargers"),
    "anker-usb-c-cable-2m": ("accessories", "charging-cables"),
    "anker-powercore-20000": ("accessories", "power-banks"),
    # Headphones and earbuds belong under TVs & Audio only (overlap fix, 2026-11-16).
    "apple-airpods-pro-2": ("accessories", "headphones-earbuds"),
    "samsung-galaxy-buds-fe": ("accessories", "headphones-earbuds"),
    "xiaomi-redmi-buds-5": ("accessories", "headphones-earbuds"),
    "jbl-tune-520bt": ("accessories", "headphones-earbuds"),
}


class Plan:
    """Counts what was (or, in a dry run, would be) done, and the notes to read."""

    def __init__(self, apply: bool) -> None:
        self.apply = apply
        self.counts: Counter[str] = Counter()
        self.notes: list[str] = []

    def did(self, kind: str, what: str, detail: str = "") -> None:
        self.counts[f"{kind} {what}"] += 1
        if detail:
            self.notes.append(f"{'' if self.apply else '(dry run) '}{what}: {detail}")

    def skip(self, kind: str, reason: str = "") -> None:
        self.counts[f"{kind} unchanged"] += 1
        if reason:
            self.notes.append(f"kept: {reason}")


def _category(db: Session, slug: str) -> Category | None:
    return db.scalar(select(Category).where(Category.slug == slug))


def _admin(db: Session) -> User:
    spec = next(p for p in CATALOGUE.staff if p.role == Role.ADMINISTRATOR.value)
    admin = db.scalar(select(User).where(func.lower(User.email) == spec.email.lower()))
    if admin is None:
        raise SystemExit("The seed administrator is missing: run seed_development_catalogue.py.")
    return admin


def apply_taxonomy(db: Session, admin: User, plan: Plan) -> None:
    # Main categories: renamed (slug kept) while they still have the old name, or created last.
    for order, (slug, name, old_name) in enumerate(MAIN, start=1):
        category = _category(db, slug)
        if category is None:
            if plan.apply:
                CatalogAdminService.create_category(
                    db, admin, CategoryCreateRequest(name=name, slug=slug, sort_order=order), CTX
                )
            plan.did("main categories", "created", f"main category {name} ({slug})")
        elif category.name != name and category.name == old_name:
            if plan.apply:
                CatalogAdminService.update_category(
                    db, admin, category.id, CategoryUpdateRequest(name=name), CTX
                )
            plan.did("main categories", "renamed", f"{old_name} -> {name} ({slug})")
        else:
            plan.skip("main categories")

    # Subcategories: created under their main category, or moved there if elsewhere.
    for main_slug, subs in SUBCATEGORIES.items():
        main = _category(db, main_slug)
        if main is None:  # only in a dry run, before the main category exists
            plan.did("subcategories", "created", f"{len(subs)} under {main_slug}")
            continue
        for order, (slug, name) in enumerate(subs, start=1):
            sub = _category(db, slug)
            if sub is None:
                if plan.apply:
                    CatalogAdminService.create_category(
                        db,
                        admin,
                        CategoryCreateRequest(
                            name=name, slug=slug, parent_id=main.id, sort_order=order
                        ),
                        CTX,
                    )
                plan.did("subcategories", "created")
            elif sub.parent_id != main.id:
                if sub.parent_id is None and db.scalar(
                    select(func.count()).where(Category.parent_id == sub.id)
                ):
                    plan.skip("subcategories", f"{slug} is a main category with subcategories")
                    continue
                if plan.apply:
                    CatalogAdminService.update_category(
                        db, admin, sub.id, CategoryUpdateRequest(parent_id=main.id), CTX
                    )
                plan.did("subcategories", "moved", f"{slug} under {main_slug}")
            else:
                plan.skip("subcategories")

    # Brands: created when neither the slug nor the name exists yet.
    for slug, name in NEW_BRANDS:
        exists = db.scalar(
            select(Brand.id).where((Brand.slug == slug) | (func.lower(Brand.name) == name.lower()))
        )
        if exists is None:
            home = _category(db, NEW_BRAND_CATEGORY[slug])
            if home is None:
                plan.skip("brands", f"{slug}: category {NEW_BRAND_CATEGORY[slug]} does not exist")
                continue
            if plan.apply:
                CatalogAdminService.create_brand(
                    db, admin, BrandCreateRequest(name=name, slug=slug, category_ids=[home.id]), CTX
                )
            plan.did("brands", "created")
        else:
            plan.skip("brands")

    # Brand names: renamed only while they still have the old name.
    for slug, old_name, new_name in BRAND_RENAMES:
        found = db.scalar(select(Brand).where(Brand.slug == slug))
        if found is None or found.name == new_name:
            plan.skip("brand names", "" if found else f"brand {slug} does not exist")
        elif found.name != old_name:
            plan.skip("brand names", f"{slug} is now called {found.name}")
        else:
            if plan.apply:
                CatalogAdminService.update_brand(
                    db, admin, found.id, BrandUpdateRequest(name=new_name), CTX
                )
            plan.did("brand names", "renamed", f"{old_name} -> {new_name} ({slug})")

    # Menu brands: set while the main category has no list, or still has an earlier default.
    for main_slug, brand_slugs in MENU_BRANDS.items():
        main = _category(db, main_slug)
        if main is None:
            plan.skip("menu brand lists", f"category {main_slug} does not exist")
            continue
        current = tuple(
            db.scalars(
                select(Brand.slug)
                .join(CategoryMenuBrand, CategoryMenuBrand.brand_id == Brand.id)
                .where(CategoryMenuBrand.category_id == main.id)
                .order_by(CategoryMenuBrand.position)
            )
        )
        if current == brand_slugs:
            plan.skip("menu brand lists")
            continue
        if current and current not in PREVIOUS_MENU_BRANDS.get(main_slug, ()):
            plan.skip("menu brand lists", f"{main_slug} has a list staff changed (kept)")
            continue
        by_slug = dict(
            db.execute(select(Brand.slug, Brand.id).where(Brand.slug.in_(brand_slugs)))
            .tuples()
            .all()
        )
        missing = [b for b in brand_slugs if b not in by_slug]
        if missing and plan.apply:
            plan.skip("menu brand lists", f"{main_slug}: brands missing: {', '.join(missing)}")
            continue
        if plan.apply:
            CatalogAdminService.set_menu_brands(
                db,
                admin,
                main.id,
                CategoryMenuBrandsRequest(brand_ids=[by_slug[b] for b in brand_slugs]),
                CTX,
            )
        plan.did("menu brand lists", "set", f"{main_slug}: {', '.join(brand_slugs)}")

    # Products: moved only while still in the category the mapping moves them from.
    for product_slug, (from_slug, to_slug) in MOVES.items():
        product = db.scalar(select(Product).where(Product.slug == product_slug))
        if product is None:
            plan.skip("products", f"{product_slug} does not exist")
            continue
        current = db.get(Category, product.category_id)
        current_slug = current.slug if current else None
        if current_slug == to_slug:
            plan.skip("products")
            continue
        if current_slug != from_slug:
            plan.skip("products", f"{product_slug} is in {current_slug}, not {from_slug}")
            continue
        target = _category(db, to_slug)
        if plan.apply:
            assert target is not None
            ProductAdminService.update_product(
                db, admin, product.id, ProductUpdateRequest(category_id=target.id), CTX
            )
        plan.did("products", "moved", f"{product_slug}: {from_slug} -> {to_slug}")


def guard() -> str | None:
    """None when allowed; otherwise the refusal message."""
    if explicit_setting("APP_ENV") != "development" or get_settings().app_env != "development":
        return "Refused: this runs only when APP_ENV=development is set explicitly."
    url = explicit_setting("DATABASE_URL")
    if url is None:
        return "Refused: DATABASE_URL is not set."
    if not is_local_host(make_url(url).host):
        return "Refused: the database host is not local."
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="apply (default: dry run)")
    args = parser.parse_args(argv)
    refusal = guard()
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2
    url = explicit_setting("DATABASE_URL")
    assert url is not None
    engine = create_engine(make_url(url))
    plan = Plan(apply=args.confirm)
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
            try:
                apply_taxonomy(db, _admin(db), plan)
            except AppError as exc:
                print(f"Stopped: {exc.code}: {exc.message}", file=sys.stderr)
                return 1
            finally:
                print(
                    "Category taxonomy"
                    + ("" if plan.apply else " (dry run, nothing written)")
                    + ":"
                )
                for key, n in sorted(plan.counts.items()):
                    print(f"  {key}: {n}")
                for note in plan.notes:
                    print(f"  - {note}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
