"""Link the existing brands to their main categories (ADR-012 decision 9, approved by the project
owner on 2026-11-17): each brand gets the main categories of its products (a product in a
subcategory counts for its main category) and the main categories whose store menu lists it
(the migration already linked those). A brand with neither stays unlinked and is reported, for
staff to choose.

Run from backend/, with the API database migrated (revision b3e8f1a6c4d2) and the seed
administrator present (scripts/seed_development_catalogue.py):

    uv run python ../scripts/backfill_brand_categories.py            # dry run: prints the plan
    uv run python ../scripts/backfill_brand_categories.py --confirm  # applies it

It refuses unless APP_ENV=development is set explicitly (environment or backend/.env) and the
database host is local. Nothing runs this on startup, deploy or migration.

Every link is saved through the application service as the seed administrator (one audited
brand update per brand). It only adds categories, never removes one, and a re-run adds
nothing new; run it once, before staff start curating, as it would re-add a product category
staff took away.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))

from apply_category_taxonomy import _admin, guard  # noqa: E402
from reset_dev_images import explicit_setting  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.errors import AppError  # noqa: E402
from app.core.request_context import RequestContext  # noqa: E402
from app.models import Brand, BrandCategory, Category, CategoryMenuBrand, Product, User  # noqa: E402
from app.schemas.catalog_admin import BrandUpdateRequest  # noqa: E402
from app.services.catalog_admin import CatalogAdminService  # noqa: E402

CTX = RequestContext(ip_address=None, user_agent="backfill_brand_categories")


def proposed_links(db: Session) -> tuple[dict[uuid.UUID, list[uuid.UUID]], list[Brand]]:
    """(brand id -> its main category ids after adding the missing ones, in menu order) for the
    brands missing any, and the unlinked brands nothing points to."""
    mains = list(
        db.scalars(
            select(Category).where(Category.parent_id.is_(None)).order_by(Category.sort_order)
        )
    )
    order = {c.id: i for i, c in enumerate(mains)}
    parent = dict(db.execute(select(Category.id, Category.parent_id)).all())
    linked: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for brand_id, category_id in db.execute(
        select(BrandCategory.brand_id, BrandCategory.category_id)
    ):
        linked[brand_id].add(category_id)
    found: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for brand_id, category_id in db.execute(
        select(Product.brand_id, Product.category_id).where(Product.brand_id.is_not(None))
    ):
        assert brand_id is not None
        found[brand_id].add(parent[category_id] or category_id)
    for brand_id, category_id in db.execute(
        select(CategoryMenuBrand.brand_id, CategoryMenuBrand.category_id)
    ):
        found[brand_id].add(category_id)
    plan: dict[uuid.UUID, list[uuid.UUID]] = {}
    lonely: list[Brand] = []
    for brand in db.scalars(select(Brand).order_by(Brand.name)):
        have = linked.get(brand.id, set())
        wanted = {c for c in found.get(brand.id, ()) if c in order} | have
        if wanted - have:
            plan[brand.id] = sorted(wanted, key=order.__getitem__)
        elif not have:
            lonely.append(brand)
    return plan, lonely


def backfill(db: Session, admin: User, apply: bool) -> None:
    plan, lonely = proposed_links(db)
    names = dict(db.execute(select(Category.id, Category.name)).all())
    brands = {b.id: b.name for b in db.scalars(select(Brand))}
    already = len(brands) - len(plan) - len(lonely)
    print("Brand categories" + ("" if apply else " (dry run, nothing written)") + ":")
    for brand_id, homes in sorted(plan.items(), key=lambda kv: brands[kv[0]].lower()):
        print(f"  {brands[brand_id]}: {', '.join(names[c] for c in homes)}")
        if apply:
            CatalogAdminService.update_brand(
                db, admin, brand_id, BrandUpdateRequest(category_ids=homes), CTX
            )
    print(f"  given categories: {len(plan)}; nothing to add: {already}")
    if lonely:
        print(f"  no products or menu, left for staff: {', '.join(b.name for b in lonely)}")


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
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
            try:
                backfill(db, _admin(db), args.confirm)
            except AppError as exc:
                print(f"Stopped: {exc.code}: {exc.message}", file=sys.stderr)
                return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
