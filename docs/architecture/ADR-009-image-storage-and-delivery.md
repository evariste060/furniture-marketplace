# ADR-009: Image storage and delivery

Status: **Accepted** by the project owner on 2026-10-25 (frontend phase 1 plan); **amended 2026-10-26** (checkpoint 1b: media registry, deletion outbox and cleanup worker, interface shaped for object storage, module 7 layout removed). Scope: local development. Hosting, a CDN and cloud storage remain open in ADR-004; the planned production shape is recorded below but nothing cloud is built.

## Context

Module 7 (plan §7 Q6–Q7) stored each product image as a re-encoded copy resized to 1600 px wide plus a 400 px thumbnail, directly under `MEDIA_ROOT`. The storefront design needs category images and brand logos too, and display sizes differ per screen (cards, gallery, hero). Fixed server-side sizes would either be too small for some screens or force more variants. Deleting files inside a request (module 7) could leave a row pointing at a missing file, or an orphan file, when a request or the process failed halfway.

## Decision

1. **Resizing happens at delivery, not at upload.** The frontend asks for the width it needs: the Next.js image optimizer locally, later a CDN with image transformations behind a custom loader. One width list everywhere: 400/800/1600 (`images.deviceSizes`). The backend stores no resized variants and converts no formats.
2. **Storage behind an interface shaped for object storage.** `app.integrations.media.MediaStorage`: `put(key, data, visibility, content_type, cache_control)` (bytes or a stream copied in chunks; never overwrites), `get`, `exists`, `delete` (a missing file is success; a failure raises `StorageError`), `public_url`, `list(prefix)` and `free_bytes`. One backend exists: `LocalMediaStorage`, chosen with `STORAGE_BACKEND=local` (the default).
3. **Two copies per image, one key.** Under `MEDIA_ROOT`:
   - `private/<key>`: the exact uploaded bytes, never served over HTTP;
   - `public/<key>`: the public source, served at `IMAGE_PUBLIC_BASE_URL` (default `http://localhost:8000/media`; the API serves it itself in development).
   Both folders are inside `backend/media/`, which is git-ignored. Incoming bulk uploads (later) go to `private/incoming/<job id>/<item id>`.
4. **Keys** are generated server-side: `<owner>/<owner id>/<32 hex>-<12 hex>.<ext>`, owner `products`, `categories`, `brands` or `banners`, the 12 hex characters being the start of the SHA-256 of the original upload. Replacing an image always creates a new key, so a URL never shows a different picture and needs no cache purge. Public files are written with `Cache-Control: public, max-age=31536000, immutable` (metadata for object storage).
5. **Upload pipeline** (`app/services/image_processing.py`):
   - validate the content with Pillow, never the file name or declared type: JPEG, PNG or WebP only, at most 5 MB, `MAX_IMAGE_PIXELS` = 50 000 000 set explicitly (on Pillow too); corrupt files and decompression bombs are refused;
   - public source in the **original format**: first frame only, EXIF orientation applied, all metadata stripped (EXIF, GPS, ICC, text chunks), transparency kept, scaled down only when the longest side is above 2400 px; JPEG and WebP at quality 92, PNG lossless;
   - Pillow work runs in FastAPI's threadpool (sync endpoints), never on the event loop, and at most `IMAGE_PROCESSING_CONCURRENCY` (default 2) images are processed at once per API process.
6. **Media registry and deletion outbox** (2026-10-26; `app/models/media.py`, `app/services/media_registry.py`). Every stored file has a `media_objects` row: key, visibility, kind (`original`, `public_source`, `incoming`), state (`pending` → `active` → `deleting`), SHA-256, size, dimensions, owner, and cleanup bookkeeping (`delete_after`, `attempts`, `last_error`). Images, category images, brand logos (and banners) link to their two objects by foreign key (`ON DELETE RESTRICT`), so a file in use cannot lose its row.
   - **Add or replace:** TX-A registers both files as `pending` and commits; the files are written; TX-B links the row, activates the new objects and marks the replaced ones `deleting`, then commits. If a write or TX-B fails, the new files and rows are discarded best-effort; anything left stays `pending`.
   - **Delete:** the row is removed and its objects marked `deleting` in one transaction.
   - **Cleanup worker** (`python -m app.worker`, `app/services/media_cleanup.py`): at start and every 15 minutes it marks `pending` objects older than an hour, and expired incoming uploads, as `deleting`; continuously it deletes each due `deleting` object's row (the foreign keys refuse if it is still used) and then its file, in one transaction, claiming rows with `SKIP LOCKED` so several workers can run. A failed deletion keeps the row with `attempts`, `last_error` and an exponential backoff (at most an hour); staff see these at `GET /staff/media/cleanup-problems`. Weekly it logs how many stored files have no registry row; `python -m app.worker reconcile` lists them. Reconciliation never deletes.
   - So a replaced image stays reachable until its replacement is committed, a rolled-back request never loses a live file, and a crash at any point is repaired by the worker.
7. **API image object:** one shared schema, `PublicImage` `{url, width, height, alt, position}`, used by product `images`, category `image`, brand `logo` and banner `image`; a single image has position 0. `url` is the public source; `alt` falls back to the product, category or brand name. The staff product image response keeps its module 7 fields for one release; its `thumbnail_url` equals `url` and is marked deprecated in OpenAPI.
8. **Health:** `GET /health` reports `checks.storage` (`ok` or `degraded`). Degraded storage keeps the API up; the storefront shows a placeholder for an image that fails to load. Publication state never changes because storage is down.

## Module 7 images (removed 2026-10-26)

No hosted environment ever held module 7 images (confirmed by the project owner on 2026-10-26), so they are not migrated. The `/media` fallback for the module 7 layout and its tests are removed: only `MEDIA_ROOT/public` is served. The registry migration (`c4e8f2a6b9d1`) refuses to run while image rows without registry entries exist; on a development database run `uv run python ../scripts/reset_dev_images.py --confirm` from `backend/` (development only, local database host only; it deletes image rows and image files and nothing else), upgrade, then re-seed. Had a deployed environment held images, the rule would have been: copy (never move), verify by SHA-256, one transaction per image, resumable and idempotent.

## Planned production shape (design only, 2026-10-26; nothing built)

- Two Cloudflare R2 buckets: **private** (originals, no public access) and **public** (the sanitised ≤2400 px sources) on a custom domain with Image Transformations. The public copy is a deliberate duplicate, because transformations need a publicly fetchable source; about 1–2 MB per image, roughly 2 GB per 1 000 images.
- An R2 backend implements `MediaStorage`; `visibility` selects the bucket. No service changes.
- The Next.js custom loader builds `/cdn-cgi/image/width=…,format=auto/<url>` with widths 400/800/1600.
- Keys are content-hashed and immutable, so replacing an image needs no purge; a hard delete (legal takedown) uses a purge-by-URL helper, added at deployment time.
- Later alternative: a Worker reading the private bucket instead of a public duplicate. Not now.

## Not decided here

Production serving, backups and the R2 rollout itself (ADR-004, `docs/deployment/media.md`). Catalogue import (module 8) has no image column; bulk image upload is a separate feature (checkpoint 1b).

## Supersedes

Plan §7 Q7's "1600 px plus a 400 px thumbnail, re-encoded at quality 85". Q6 (local disk for the MVP) still holds.
