"""Seed development data (plan §2 and §5). Refuses to run unless APP_ENV=development is set
explicitly, in the shell environment or in backend/.env (the shell wins, as for the app).
The Settings default (development) is deliberately not trusted: an unset APP_ENV is refused
before any database connection is made.

Run from backend/ after `alembic upgrade head` and `provision_runtime_role.py`:

    uv run python ../scripts/seed_dev.py

Module 12 (RE-026 B1) seeds the three delivery zones and the free-delivery threshold. Every value
is a **placeholder** to be replaced with approved values before launch: Nyarugenge 1 500 RWF,
Kicukiro 2 000 RWF, Gasabo 2 000 RWF, threshold 50 000 RWF (changed from 200 000 on 2026-10-26
to match the storefront design). There is deliberately no
production seed migration, so these values cannot reach production unnoticed.

Safe to rerun: a district that already has a zone, and a threshold that is already set, are
left exactly as they are (their fee history included); only what is missing is added. The
script connects with DATABASE_URL (the runtime role has the grants it needs) and prints only
what it created, never a credential.
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.transaction import atomic  # noqa: E402
from app.models import DeliveryFeeRule, DeliveryZone, Setting  # noqa: E402
from app.repositories import delivery_repository  # noqa: E402
from app.schemas.settings import FREE_DELIVERY_THRESHOLD  # noqa: E402

# (code, name, district, fee in whole RWF, sort order): placeholders (RE-026 B1).
DEV_ZONES: tuple[tuple[str, str, str, int, int], ...] = (
    ("nyarugenge", "Nyarugenge", "Nyarugenge", 1_500, 1),
    ("kicukiro", "Kicukiro", "Kicukiro", 2_000, 2),
    ("gasabo", "Gasabo", "Gasabo", 2_000, 3),
)
DEV_FREE_DELIVERY_THRESHOLD = 50_000  # placeholder (RE-026 B1), as in the design
ENV_FILE = BACKEND / ".env"  # the file app.core.config reads
REFUSED = "seed_dev.py runs only when APP_ENV=development is set explicitly (environment or .env)."


def explicit_app_env() -> str | None:
    """APP_ENV as configured, ignoring the Settings default: the process environment first,
    then ENV_FILE; names match case-insensitively, as pydantic-settings matches them."""
    file_values = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
    for source in (dict(os.environ), file_values):
        for name, value in source.items():
            if name.upper() == "APP_ENV" and value is not None and value.strip():
                return value.strip()
    return None


def seed(db: Session) -> list[str]:
    """Add the missing development delivery data in one transaction; returns what was added."""
    created: list[str] = []
    with atomic(db):
        for code, name, district, fee, sort_order in DEV_ZONES:
            if delivery_repository.zone_by_district(db, district) is not None:
                continue
            if delivery_repository.code_taken(db, code):
                print(f"Skipped {district}: the code '{code}' is used by another zone.")
                continue
            zone = DeliveryZone(code=code, name=name, district=district, sort_order=sort_order)
            db.add(zone)
            db.flush()
            db.add(DeliveryFeeRule(zone_id=zone.id, fee=fee, starts_at=func.now()))
            created.append(f"zone {code} ({fee} RWF)")
        inserted = db.execute(
            insert(Setting)
            .values(key=FREE_DELIVERY_THRESHOLD, value=DEV_FREE_DELIVERY_THRESHOLD)
            .on_conflict_do_nothing(index_elements=[Setting.key])
            .returning(Setting.key)
        ).first()
        if inserted is not None:
            created.append(f"{FREE_DELIVERY_THRESHOLD} = {DEV_FREE_DELIVERY_THRESHOLD}")
    return created


def main() -> int:
    if explicit_app_env() != "development":  # checked before settings or any connection
        print(REFUSED, file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.app_env != "development":  # the value the app would use must agree
        print(REFUSED, file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
            created = seed(db)
    finally:
        engine.dispose()
    if created:
        print("Seeded (development placeholders): " + "; ".join(created) + ".")
    else:
        print("Nothing to seed: the development data is already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
