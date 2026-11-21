"""Copy the images of a database from local disk (MEDIA_ROOT) to Cloudflare R2.

For a database whose images were stored with STORAGE_BACKEND=local (for example a catalogue seeded
before R2 was configured): every active media registry entry (original or public source; not
incoming bulk uploads, not files being deleted) is read from MEDIA_ROOT and written to the R2
bucket of its visibility, under the same key, so the database needs no change. Then set
STORAGE_BACKEND=r2 and the API serves the R2 URLs. Run from backend/:

    uv run python ../scripts/copy_media_to_r2.py --confirm

--public-only copies just the public sources (what the shop shows), for when the private bucket
is not ready yet; rerun without it later to add the originals.

Uses the R2_* settings of backend/.env (the same as STORAGE_BACKEND=r2) whatever STORAGE_BACKEND
says, and DATABASE_URL to read the registry. Idempotent: an object already in R2 is skipped, and
an existing object is never overwritten. A file missing on disk is reported and skipped.
Credentials are never printed.
"""

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.media import (  # noqa: E402
    PUBLIC_CACHE_CONTROL,
    LocalMediaStorage,
    StorageError,
    Visibility,
    get_media_storage,
)
from app.models.media import MediaObject  # noqa: E402

CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="write to the R2 buckets")
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="copy only the public sources (what the shop shows), not the private originals",
    )
    args = parser.parse_args(argv)
    if not args.confirm:
        print("Refused: pass --confirm to copy the images to R2.", file=sys.stderr)
        return 2
    os.environ["STORAGE_BACKEND"] = "r2"
    get_settings.cache_clear()
    settings = get_settings()  # refuses incomplete R2 settings
    local = LocalMediaStorage(settings.media_root, settings.image_public_base_url)
    r2 = get_media_storage()
    try:
        if args.public_only:
            next(iter(r2.list("products/", visibility="public")), None)  # public bucket reachable
        else:
            r2.free_bytes()  # both buckets reachable with these credentials
    except StorageError as exc:
        print(f"Refused: {exc} Check R2_* and the token's access to both buckets.", file=sys.stderr)
        return 1

    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as db:
            rows = db.execute(
                select(MediaObject.storage_key, MediaObject.visibility)
                .where(MediaObject.state == "active", MediaObject.kind != "incoming")
                .where(MediaObject.visibility == "public" if args.public_only else True)
                .order_by(MediaObject.visibility, MediaObject.storage_key)
            ).all()
    finally:
        engine.dispose()

    copied = skipped = missing = failed = 0
    for key, visibility_text in rows:
        visibility: Visibility = "public" if visibility_text == "public" else "private"
        try:
            if r2.exists(key, visibility=visibility):
                skipped += 1
                continue
            if not local.exists(key, visibility=visibility):
                print(f"missing on disk: {visibility}/{key}")
                missing += 1
                continue
            r2.put(
                key,
                local.get(key, visibility=visibility),
                visibility=visibility,
                content_type=CONTENT_TYPES.get(key.rsplit(".", 1)[-1], "application/octet-stream"),
                cache_control=PUBLIC_CACHE_CONTROL if visibility == "public" else None,
            )
            copied += 1
        except StorageError as exc:
            print(f"failed: {visibility}/{key}: {exc}")
            failed += 1
    print(
        f"{len(rows)} images: {copied} copied, {skipped} already in R2, {missing} missing on disk, "
        f"{failed} failed."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
