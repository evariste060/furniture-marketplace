"""Delete every image row and image file of a DEVELOPMENT database (approved 2026-10-26).

Needed once per development database before `alembic upgrade` to the media registry (revision
c4e8f2a6b9d1), which refuses while image rows without registry entries exist. No hosted
environment holds images. Afterwards re-seed the catalogue. Run from backend/:

    uv run python ../scripts/reset_dev_images.py --confirm

It deletes: product image rows; category images and brand logos (the columns are cleared, the
categories and brands stay); media registry rows, if the registry exists; and the image folders
under MEDIA_ROOT (products/ from module 7, public/ and private/). Nothing else is touched.

Refuses unless APP_ENV=development is set explicitly (environment or backend/.env), the database
host is local (localhost, 127.0.0.1, ::1 or a docker-compose service name) and --confirm is
given. Connects with MIGRATION_DATABASE_URL (the schema owner), because the runtime role cannot
delete media registry rows that are still in use. Credentials are never printed.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import Connection, make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402

ENV_FILE = BACKEND / ".env"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
IMAGE_FOLDERS = ("products", "public", "private")
REFUSED_ENV = "Refused: reset_dev_images.py runs only when APP_ENV=development is set explicitly."


def explicit_setting(name: str) -> str | None:
    """A setting as configured (environment first, then backend/.env); never the default."""
    file_values = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
    for source in (dict(os.environ), file_values):
        for key, value in source.items():
            if key.upper() == name and value is not None and value.strip():
                return value.strip()
    return None


def compose_services() -> set[str]:
    """Service names in docker-compose.yml (a container reaches the database by that name)."""
    compose = REPO / "docker-compose.yml"
    if not compose.is_file():
        return set()
    names: set[str] = set()
    in_services = False
    for line in compose.read_text(encoding="utf-8").splitlines():
        if line.startswith("services:"):
            in_services = True
        elif line and not line.startswith(" "):
            in_services = False
        elif in_services and line.startswith("  ") and not line.startswith("   "):
            name = line.strip().rstrip(":")
            if name and not name.startswith("#"):
                names.add(name)
    return names


def is_local_host(host: str | None) -> bool:
    return host is not None and (host in LOCAL_HOSTS or host in compose_services())


def reset(conn: Connection) -> dict[str, int]:
    tables = set(inspect(conn).get_table_names())
    columns = {
        table: {c["name"] for c in inspect(conn).get_columns(table)}
        for table in ("categories", "brands")
    }
    counts = {"product images": conn.execute(text("DELETE FROM product_images")).rowcount}
    for table, prefix in (("categories", "image"), ("brands", "logo")):
        present = [
            f"{prefix}_{suffix}"
            for suffix in ("key", "width", "height", "media_id", "original_media_id")
            if f"{prefix}_{suffix}" in columns[table]
        ]
        marker = f"{prefix}_media_id" if f"{prefix}_media_id" in present else f"{prefix}_key"
        cleared = ", ".join(f"{column} = NULL" for column in present)
        counts[f"{table} {prefix}s"] = conn.execute(
            text(f"UPDATE {table} SET {cleared} WHERE {marker} IS NOT NULL")  # noqa: S608
        ).rowcount
    if "media_objects" in tables:
        counts["media registry rows"] = conn.execute(text("DELETE FROM media_objects")).rowcount
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="required: really delete")
    args = parser.parse_args(argv)
    if explicit_setting("APP_ENV") != "development":
        print(REFUSED_ENV, file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.app_env != "development":
        print(REFUSED_ENV, file=sys.stderr)
        return 2
    owner_url = explicit_setting("MIGRATION_DATABASE_URL")
    if owner_url is None:
        print("Refused: MIGRATION_DATABASE_URL is not set.", file=sys.stderr)
        return 2
    url = make_url(owner_url)
    if not is_local_host(url.host):
        print("Refused: the database host is not local.", file=sys.stderr)
        return 2
    if not args.confirm:
        print("Refused: pass --confirm to delete every image row and image file.", file=sys.stderr)
        return 2
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            counts = reset(conn)
    finally:
        engine.dispose()
    removed = []
    for folder in IMAGE_FOLDERS:
        path = settings.media_root / folder
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(folder)
    summary = ", ".join(f"{n} {label}" for label, n in counts.items())
    print(f"Deleted {summary}.")
    print(f"Removed media folders: {', '.join(removed) or 'none'}. Re-seed the catalogue next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
