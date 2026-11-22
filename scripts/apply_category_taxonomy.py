"""Apply the furniture category taxonomy (ADR-014 decision 14, phase 6): the main categories and
subcategories of backend/app/core/furniture.py, and hide the categories and brands that are not
furniture once nothing uses them (the electronics ones left by the earlier catalogue).

Run from backend/, with the API database migrated and the seed administrator present
(scripts/seed_development_catalogue.py):

    uv run python ../scripts/apply_category_taxonomy.py            # dry run: prints the plan
    uv run python ../scripts/apply_category_taxonomy.py --confirm  # applies it

It refuses unless APP_ENV=development is set explicitly (environment or backend/.env) and the
database host is local. Nothing runs this on startup, deploy or migration.

Every change goes through the application services as the seed administrator, so it is
validated and audited like a change made in the admin. Re-runnable: what already matches is
skipped. It creates a missing taxonomy category, and moves a subcategory under its main category
only when it is elsewhere. It never renames, never deletes and never changes a product. A
category outside the taxonomy is hidden only while no product is in it or under it, and a brand
outside the development manufacturers only while no product has it; the others are reported
and left alone. Hidden rows stay in the admin, where staff can show them again.
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
from app.core.furniture import TAXONOMY, TAXONOMY_SLUGS  # noqa: E402
from app.core.request_context import RequestContext  # noqa: E402
from app.core.roles import Role  # noqa: E402
from app.models import Brand, Category, Product, User  # noqa: E402
from app.schemas.catalog_admin import (  # noqa: E402
    BrandUpdateRequest,
    CategoryCreateRequest,
    CategoryUpdateRequest,
)
from app.services.catalog_admin import CatalogAdminService  # noqa: E402

CTX = RequestContext(ip_address=None, user_agent="apply_category_taxonomy")


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


def _subtree_has_products(db: Session, category: Category) -> bool:
    ids, frontier = {category.id}, [category.id]
    while frontier:
        children = list(db.scalars(select(Category.id).where(Category.parent_id.in_(frontier))))
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    return bool(db.scalar(select(func.count(Product.id)).where(Product.category_id.in_(ids))))


def apply_taxonomy(db: Session, admin: User, plan: Plan) -> None:
    for order, main in enumerate(TAXONOMY, start=1):
        parent = _category(db, main.slug)
        if parent is None:
            if plan.apply:
                parent = CatalogAdminService.create_category(
                    db,
                    admin,
                    CategoryCreateRequest(
                        name=main.name,
                        slug=main.slug,
                        sort_order=order,
                        description=main.description,
                    ),
                    CTX,
                )
            plan.did("main categories", "created", f"{main.name} ({main.slug})")
        else:
            plan.skip("main categories")
        for position, child in enumerate(main.children, start=1):
            category = _category(db, child.slug)
            if category is None:
                if plan.apply and parent is not None:
                    CatalogAdminService.create_category(
                        db,
                        admin,
                        CategoryCreateRequest(
                            name=child.name,
                            slug=child.slug,
                            sort_order=position,
                            parent_id=parent.id,
                        ),
                        CTX,
                    )
                plan.did("subcategories", "created", f"{child.name} under {main.name}")
            elif parent is not None and category.parent_id != parent.id:
                if plan.apply:
                    CatalogAdminService.update_category(
                        db, admin, category.id, CategoryUpdateRequest(parent_id=parent.id), CTX
                    )
                plan.did("subcategories", "moved", f"{child.name} under {main.name}")
            else:
                plan.skip("subcategories")

    # Categories outside the taxonomy: hidden once empty, top levels first.
    others = db.scalars(
        select(Category)
        .where(Category.slug.not_in(TAXONOMY_SLUGS), Category.is_active)
        .order_by(Category.parent_id.is_not(None), Category.sort_order)
    ).all()
    for category in others:
        if _subtree_has_products(db, category):
            plan.skip("other categories", f"{category.name} ({category.slug}) still has products")
            continue
        if plan.apply:
            CatalogAdminService.update_category(
                db, admin, category.id, CategoryUpdateRequest(is_active=False), CTX
            )
        plan.did("other categories", "hidden", f"{category.name} ({category.slug})")

    # Brands outside the development manufacturers: hidden once no product has them.
    furniture_brands = {b.slug for b in CATALOGUE.brands}
    brands = db.scalars(
        select(Brand).where(Brand.slug.not_in(furniture_brands), Brand.is_active)
    ).all()
    for brand in brands:
        if db.scalar(select(func.count(Product.id)).where(Product.brand_id == brand.id)):
            plan.skip("other brands", f"{brand.name} ({brand.slug}) still has products")
            continue
        if plan.apply:
            CatalogAdminService.update_brand(
                db, admin, brand.id, BrandUpdateRequest(is_active=False), CTX
            )
        plan.did("other brands", "hidden", f"{brand.name} ({brand.slug})")


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
                    "Furniture taxonomy"
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
