"""Seed the six technical services (ADR-013, SC-02; texts from the Services module brief,
approved 2026-11-17).

Run from backend/, with the API database migrated and the seed administrator present
(scripts/seed_development_catalogue.py):

    uv run python ../scripts/seed_services.py            # dry run: prints the plan
    uv run python ../scripts/seed_services.py --confirm  # applies it

It refuses unless APP_ENV=development is set explicitly (environment or backend/.env) and the
database host is local. Nothing runs this on startup, deploy or migration.

Every change goes through the application service as the seed administrator, so it is validated
and audited like a change made in the admin. Re-runnable: a service whose slug already exists is
left exactly as staff keep it (texts, items, order, visibility), and items are added only to a
service this run creates. It never deletes anything. Services are created without an image: the
storefront shows its placeholder until staff upload a photo. Kinyarwanda texts are left empty
(the storefront falls back to English) until reviewed translations are written in the admin.

Services 4 (IT infrastructure) and 6 (technical training) and every intro are DRAFTS for the
business owner to confirm (docs/frontend/rw-review-admin.md lists them).
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
from app.schemas.services import ServiceCreateRequest, ServiceItemCreateRequest  # noqa: E402
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
        "cctv-security",
        "CCTV & Security Surveillance",
        "cctv",
        "Professional CCTV supply, installation and monitoring for homes, offices, shops and "
        "institutions.",
        "We supply, install and maintain CCTV systems that protect homes, offices, shops and "
        "institutions, and let you watch over them from your smartphone.\n\n"
        "Our technicians plan the cameras, cabling and recording equipment for your site, set "
        "everything up and stay available for inspection, maintenance and repair.",
        (
            "CCTV camera supply and installation",
            "IP, HD analogue and wireless camera systems",
            "Indoor and outdoor surveillance solutions",
            "DVR and NVR installation and configuration",
            "Remote monitoring through smartphones",
            "Night vision, motion detection and security alerts",
            "CCTV cabling, networking and system upgrades",
            "Inspection, maintenance, troubleshooting and repair",
            "Security surveillance for homes, offices, shops and institutions",
        ),
    ),
    SeedService(
        "gate-automation",
        "Smart Gates & Gate Automation",
        "gate",
        "Automatic sliding and swing gates you can open by remote or smartphone, installed and "
        "maintained by our team.",
        "We automate sliding and swing gates so you can open them by remote control or from "
        "your smartphone, safely and reliably.\n\n"
        "From the motor and controller to safety sensors and backup power, our team installs "
        "the complete system and keeps it running with diagnostics, repair and preventive "
        "maintenance.",
        (
            "Automatic sliding gate systems",
            "Automatic swing gate systems",
            "Electric gate motor supply and installation",
            "Remote-controlled gate systems",
            "GSM, Wi-Fi and smartphone-controlled gate access",
            "Gate automation controllers and accessories",
            "Safety sensors and vehicle detection",
            "Backup battery and power solutions",
            "Gate motor diagnostics, repair and preventive maintenance",
        ),
    ),
    SeedService(
        "automation-access-control",
        "Smart Automation & Access Control",
        "fingerprint",
        "Smart home and office automation, biometric and card access, smart locks and intercoms.",
        "We make homes and offices smarter and more secure with automation, access control and "
        "intercom systems.\n\n"
        "Choose biometric, card or keypad access, smart locks, video door phones, automatic "
        "doors or parking barriers, and we integrate them into one system that is easy to "
        "manage.",
        (
            "Smart home and office automation",
            "Biometric access control systems",
            "RFID and card access systems",
            "Keypad access control",
            "Electronic and smart door locks",
            "Video door phones and intercom systems",
            "Automatic doors and parking barriers",
            "Access management and system integration",
        ),
    ),
    SeedService(  # DRAFT: business owner to confirm
        "it-networking",
        "IT Infrastructure & Networking",
        "network",
        "Reliable networks for offices and institutions, from cabling and Wi-Fi to servers and "
        "ongoing IT support.",
        "We design, install and support the networks that offices and institutions depend on "
        "every day.\n\n"
        "From structured cabling and Wi-Fi to servers, firewalls and bandwidth management, we "
        "build a reliable infrastructure and keep it running with IT support and maintenance "
        "contracts.",
        (
            "Structured cabling (Cat6 and fibre)",
            "LAN and Wi-Fi network design and installation",
            "Router, switch and access point configuration",
            "Server installation and setup",
            "Network security and firewall setup",
            "Internet sharing and bandwidth management",
            "IT support and maintenance contracts",
        ),
    ),
    SeedService(
        "electronics-repair",
        "Phone, Computer & Electronics Repair",
        "wrench",
        "Fast, reliable repair for phones, tablets, laptops, desktops, printers and other "
        "electronics.",
        "Our technicians diagnose and repair phones, tablets, laptops, desktops, printers and "
        "other electronics quickly and reliably.\n\n"
        "We replace screens, batteries and charging ports, repair motherboards, upgrade memory "
        "and storage, install software and help recover data where feasible.",
        (
            "Smartphone and tablet repair",
            "Laptop and desktop computer repair",
            "Screen, battery and charging-port replacement",
            "Motherboard and PCB diagnostics and repair",
            "Operating system and software installation",
            "RAM and SSD upgrades",
            "Printer repair and maintenance",
            "Data backup and recovery assistance, where feasible",
            "General electronics diagnostics and troubleshooting",
        ),
    ),
    SeedService(  # DRAFT: business owner to confirm
        "technical-training",
        "Technical Training",
        "graduation-cap",
        "Hands-on practical training in security systems, networking and electronics repair.",
        "We train individuals and company teams in the practical skills our own technicians use "
        "every day.\n\n"
        "Sessions are hands-on, with real equipment, and cover security systems, gate "
        "automation and access control, networking, and phone and computer repair.",
        (
            "CCTV installation and maintenance training",
            "Gate automation and access control installation",
            "Networking fundamentals",
            "Phone and computer repair training",
            "Hands-on practical sessions with real equipment",
            "Training for individuals and company teams",
        ),
    ),
)


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
                created, kept = seed(db, _admin(db), args.confirm)
            except AppError as exc:
                print(f"Stopped: {exc.code}: {exc.message}", file=sys.stderr)
                return 1
            suffix = "" if args.confirm else " (dry run, nothing written)"
            print(f"Technical services{suffix}:")
            verb = "created" if args.confirm else "to create"
            print(f"  {verb}: {len(created)} {', '.join(created)}".rstrip())
            print(f"  already present, left as they are: {len(kept)} {', '.join(kept)}".rstrip())
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
