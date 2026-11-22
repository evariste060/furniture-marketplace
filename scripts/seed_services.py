"""Seed the furniture services (ADR-014 decision 15, phase 6: the technical services of ADR-013
become furniture services, with the same tables, endpoints and UI), and hide the six technical
services of the electronics shop.

Run from backend/, with the API database migrated and the seed administrator present
(scripts/seed_development_catalogue.py):

    uv run python ../scripts/seed_services.py            # dry run: prints the plan
    uv run python ../scripts/seed_services.py --confirm  # applies it

It refuses unless APP_ENV=development is set explicitly (environment or backend/.env) and the
database host is local. Nothing runs this on startup, deploy or migration.

Every change goes through the application service as the seed administrator, so it is validated
and audited like a change made in the admin. Re-runnable: a service whose slug already exists is
left exactly as staff keep it (texts, items, order, visibility), and items are added only to a
service this run creates. A technical service is only hidden (is_active false), never deleted,
so its past requests stay readable in the admin. Services are created without an image: the
storefront shows its placeholder until staff upload a photo. Kinyarwanda texts are left empty
(the storefront falls back to English) until reviewed translations are written in the admin.

Every text here is a DEVELOPMENT DRAFT for the project owner to confirm. Prices are never shown:
a service is requested through its form and quoted by the store, as before.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
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
from app.models import ServiceCategory, User  # noqa: E402
from app.schemas.services import (  # noqa: E402
    ServiceCreateRequest,
    ServiceItemCreateRequest,
    ServiceUpdateRequest,
)
from app.services.technical_services import ServiceAdmin  # noqa: E402

CTX = RequestContext(ip_address=None, user_agent="seed_services")


@dataclass(frozen=True)
class SeedService:
    slug: str
    name: str
    icon: str
    card: str
    intro: str
    items: tuple[str, ...]


SERVICES: tuple[SeedService, ...] = (
    SeedService(
        "furniture-assembly",
        "Furniture Assembly",
        "hammer",
        "Flat-pack and large furniture put together at your home or office by trained fitters.",
        "Our fitters assemble beds, wardrobes, desks, shelving and kitchen units, from any store "
        "on the marketplace or bought elsewhere.\n\n"
        "They bring their own tools, check every part before they start, and take the packaging "
        "away when they finish.",
        (
            "Beds, bunk beds and cots",
            "Wardrobes, dressers and chests of drawers",
            "Desks, office chairs and meeting tables",
            "Shelving, bookcases and TV units",
            "Garden and outdoor sets",
            "Packaging removed after assembly",
        ),
    ),
    SeedService(
        "installation-wall-mounting",
        "Installation & Wall Mounting",
        "ruler",
        "Shelves, cabinets, TV units and mirrors fixed safely to your walls.",
        "We measure, drill and mount wall cabinets, floating shelves, mirrors and TV units, with "
        "the right fixings for brick, block or plasterboard walls.\n\n"
        "Large pieces such as wardrobes and bookcases are anchored to the wall so they cannot "
        "tip over, which matters most in children's rooms.",
        (
            "Wall cabinets and floating shelves",
            "Mirrors and wall art",
            "TV units and wall brackets",
            "Anti-tip anchoring for tall furniture",
            "Curtain rails and blinds",
        ),
    ),
    SeedService(
        "delivery-and-setup",
        "Delivery & Room Setup",
        "truck",
        "Heavy pieces carried in, placed where you want them and set up, across Kigali.",
        "For large orders and heavy pieces, our team carries the furniture up stairs and through "
        "narrow doors, places it in the right room and sets it up.\n\n"
        "Offices, hotels and schools can book a whole room or floor at once.",
        (
            "Carrying up stairs and through narrow doors",
            "Placing furniture in the room of your choice",
            "Setting up beds, tables and seating",
            "Whole-room setup for offices, hotels and schools",
        ),
    ),
    SeedService(
        "upholstery-repair",
        "Upholstery & Furniture Repair",
        "sofa",
        "Sofas and chairs reupholstered, and broken joints, legs and drawers repaired.",
        "Give a favourite sofa or set of dining chairs a new life: we replace worn foam and "
        "fabric, and repair loose joints, broken legs and sticking drawers.\n\n"
        "We collect the piece in Kigali, or work at your home when it is too large to move.",
        (
            "Sofa and chair reupholstery",
            "Foam and cushion replacement",
            "Loose joints, legs and frames",
            "Drawer runners and door hinges",
            "Collection and return in Kigali",
        ),
    ),
    SeedService(
        "refinishing",
        "Wood Refinishing & Polishing",
        "paintbrush",
        "Scratched or faded wooden furniture sanded, stained and polished.",
        "We restore wooden tables, cabinets and doors: sanding out scratches and stains, "
        "matching the colour and finishing with oil, lacquer or polish.",
        (
            "Sanding and scratch removal",
            "Staining and colour matching",
            "Oil, lacquer and polish finishes",
            "Antique and family pieces",
        ),
    ),
)

# The electronics shop's technical services (ADR-013): hidden, never deleted.
RETIRED = (
    "cctv-security",
    "gate-automation",
    "automation-access-control",
    "it-networking",
    "electronics-repair",
    "technical-training",
)


def retire(db: Session, admin: User, apply: bool) -> list[str]:
    """The technical services still shown, hidden (only read in a dry run)."""
    hidden: list[str] = []
    for service in db.scalars(
        select(ServiceCategory).where(ServiceCategory.slug.in_(RETIRED), ServiceCategory.is_active)
    ):
        hidden.append(service.slug)
        if apply:
            ServiceAdmin.update(db, admin, service.id, ServiceUpdateRequest(is_active=False), CTX)
    return hidden


def seed(db: Session, admin: User, apply: bool) -> tuple[list[str], list[str]]:
    """(created, kept) slugs. A dry run only reads."""
    created: list[str] = []
    kept: list[str] = []
    for spec in SERVICES:
        if db.scalar(select(ServiceCategory.id).where(ServiceCategory.slug == spec.slug)):
            kept.append(spec.slug)
            continue
        created.append(spec.slug)
        if not apply:
            continue
        service = ServiceAdmin.create(
            db,
            admin,
            ServiceCreateRequest(
                slug=spec.slug,
                name_en=spec.name,
                short_description_en=spec.card,
                intro_en=spec.intro,
                icon=spec.icon,  # type: ignore[arg-type]
            ),
            CTX,
        )
        for title in spec.items:
            ServiceAdmin.add_item(
                db, admin, service.id, ServiceItemCreateRequest(title_en=title), CTX
            )
    return created, kept


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
                admin = _admin(db)
                created, kept = seed(db, admin, args.confirm)
                hidden = retire(db, admin, args.confirm)
            except AppError as exc:
                print(f"Stopped: {exc.code}: {exc.message}", file=sys.stderr)
                return 1
            suffix = "" if args.confirm else " (dry run, nothing written)"
            print(f"Furniture services{suffix}:")
            verb = "created" if args.confirm else "to create"
            print(f"  {verb}: {len(created)} {', '.join(created)}".rstrip())
            print(f"  already present, left as they are: {len(kept)} {', '.join(kept)}".rstrip())
            verb = "hidden" if args.confirm else "to hide"
            print(f"  technical services {verb}: {len(hidden)} {', '.join(hidden)}".rstrip())
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
