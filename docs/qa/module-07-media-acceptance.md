# Module 7 (media) — acceptance record

| Field | Value |
| --- | --- |
| Module | 7 — media (`docs/IMPLEMENTATION_PLAN.md` §5, "7 — media") |
| Requirements | PRD PR-03 (product page shows images), PR-10 (staff manage variants/images), PRD §6 non-functional "compressed images"; Technical plan §6 (product schema supports images), §7 risk "poor mobile performance" |
| Linked tests | QA/UAT checklist TC-21 (mobile performance and images); also TC-04 (product page images) and TC-16 (staff roles) for the image routes |
| Branch | `feat/module-07-media` (original commit `290a841`, identical tree to `9392d4f`, plus the follow-up commits listed in the PR) |
| Trello card | None recorded for module 7 in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-24 |
| Recommendation | **Not Done.** The code and the automated tests are ready for review. Human review, the ADR-004 serving decision and the storefront part of TC-21 are still open (see "Open items"). |

## Acceptance criteria

Status values: **Verified** (checked on this branch with the evidence named), **Decided** (a recorded decision closes it, open to the reviewer), **Open** (work or approval missing).

| # | Criterion (source) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `POST /staff/products/{id}/images`, `PATCH /staff/images/{id}`, `DELETE /staff/images/{id}` exist and need `catalog:manage` (plan §5) | Verified | `backend/app/api/v1/endpoints/image_admin.py`; `test_sales_staff_manage_images`, `test_other_roles_are_forbidden_and_nothing_is_stored`, `test_anonymous_requests_are_unauthorized` |
| 2 | `product_images` gains `thumbnail_key`, `width`, `height` (plan §5) | Verified | Migration `76768b844c03`; `tests/integration/test_image_media_migration.py` (upgrade → downgrade → upgrade on a disposable schema, constraints, models match the migrated schema) |
| 3 | JPEG/PNG/WebP up to 5 MB; decoded with Pillow, declared type not trusted; metadata stripped; ≤ 1600 px plus a 400 px thumbnail (plan §7 Q6–Q7) | Verified | `tests/unit/test_image_processing.py`; `test_the_declared_name_and_content_type_are_ignored`; `test_unsupported_or_invalid_files_are_rejected_and_nothing_is_stored`; `test_files_over_5_mb_get_413_and_nothing_is_stored` |
| 4 | Stored under `MEDIA_ROOT` with a random key, served from `MEDIA_BASE_URL`, both in `.env.example` (plan §5) | Verified (development) | `backend/.env.example`; `tests/unit/test_media_storage.py`; `test_development_serves_media_files_at_media` |
| 5 | Staging/production serving consistent with hosting (ADR-004) | **Open** | ADR-004 does not exist. The requirements for any host are in `docs/deployment/media.md`; the deployment templates now carry `MEDIA_ROOT` and `MEDIA_BASE_URL`; the API refuses to start outside development unless `MEDIA_BASE_URL` is a public `https://` URL. Decision D-M1 below. |
| 6 | Tests: wrong types, oversize, corrupt files, ordering, delete removes files, forbidden roles (plan §5) | Verified | Tests named in rows 1–3; `test_new_images_are_appended_and_public_order_follows_sort_order`; `test_delete_removes_the_row_then_both_files`; `tests/postgres/test_pg_images.py` (runtime role, concurrent uploads in two processes, live 413) |
| 7 | Missing resources, malformed IDs, file-write failure, no free sort position | Verified | `test_a_missing_file_or_unknown_product_is_rejected`; `test_image_updates_are_validated_and_audited`; `test_malformed_ids_are_rejected_before_anything_is_stored`; `test_a_failed_file_write_stores_no_row_and_leaves_no_file`; `test_a_failed_file_write_returns_a_generic_500`; `test_no_higher_sort_order_gives_409_and_stores_nothing` |
| 8 | Errors use the standard error shape; nothing sensitive in logs (done checklist) | Verified | `tests/unit/test_errors.py::test_openapi_documents_every_error_with_the_standard_schema`; `test_a_failed_file_write_returns_a_generic_500` (no path or exception text in the body); `test_delete_failures_are_reported_and_logged_without_paths` |
| 9 | Endpoints correct in `/docs` with examples (done checklist) | Verified | Response, request and error examples on all three routes and on `CatalogImage`; `test_openapi_documents_every_image_response_with_valid_examples`; `test_documented_error_examples_match_real_responses` (each error the API returns is a documented example, verbatim); `tests/postgres/test_pg_http.py::test_live_openapi_is_valid_complete_and_accurate` (OpenAPI 3.1 validation on a live server) |
| 10 | Runtime-role grants for the table, pinned in tests and ADR-006 (plan §2) | Verified | `scripts/provision_runtime_role.py`; `tests/unit/test_runtime_role_grants.py`; `test_runtime_role_can_delete_images_but_not_other_catalogue_rows`; ADR-006 |
| 11 | Seed data for local testing (done checklist; plan §2) | Decided | Decision D-M4 below |
| 12 | Oversized upload response and authentication order | Decided | Decision D-M2 below; `test_an_oversized_anonymous_upload_gets_413_and_a_small_one_401` pins the behaviour, and the 413 description in OpenAPI states it |
| 13 | Image deletion is safe for historical orders | Decided (for module 14) | Decision D-M3 below |
| 14 | Pull request reviewed, CI green (done checklist) | **Open** | PR opened against `dev`; human review is still required |
| 15 | Deployed to staging (done checklist) | **Open** | Not possible from this repository (plan §7 Q27) |
| 16 | TC-21 run and recorded | **Partial** | Backend part below; storefront part blocked |

## TC-21 — Mobile performance and images

Expected result (QA/UAT checklist §2): "Images load efficiently; key flow usable on constrained mobile connection."

| Field | Value |
| --- | --- |
| Status | **Blocked** for the scenario as written; backend part **Pass** |
| Tester / date | Backend engineering, 2026-10-24 |
| Environment | Local, Windows 11, Python 3.14, Pillow 13.0.0, branch `feat/module-07-media` |
| Defect | None raised; finding F-1 below needs a decision |

What can be tested now is what the backend produces. The storefront pages (home, listing, product, cart, checkout) do not exist yet, and no staging host exists. So "loads efficiently on a constrained mobile connection" cannot be measured. It needs the storefront pages, a deployed environment with the serving settings in `docs/deployment/media.md`, and a throttled mobile run (for example Lighthouse mobile with network throttling, or a real mid-range phone).

Backend evidence: synthetic photo-like images (gradients, shapes and noise, so they compress like product photos rather than flat colour) were passed through `app.services.image_processing.process_image`:

| Input | Upload | Stored image | Stored size | Thumbnail | Thumbnail size | Processing time |
| --- | --- | --- | --- | --- | --- | --- |
| JPEG 4000×3000 | 1619 KB | 1600×1200 | 73 KB | 400×300 | 13 KB | 665 ms |
| JPEG 3024×4032 (portrait) | 1391 KB | 1600×2133 | 153 KB | 400×533 | 20 KB | 655 ms |
| PNG 2000×1500 | 3466 KB | 1600×1200 | 1950 KB | 400×300 | 107 KB | 1857 ms |
| WebP 3000×2000 | 669 KB | 1600×1067 | 26 KB | 400×267 | 6 KB | 641 ms |

- Pass: JPEG and WebP uploads become 26–153 KB images and 6–20 KB thumbnails, so a listing page can load thumbnails of a few KB to tens of KB each. Responses carry `width` and `height`, so the storefront can reserve space and avoid layout shift.
- **F-1 (needs a decision):** a photo uploaded as PNG stays large (1.9 MB stored, 107 KB thumbnail), because the approved rule (decision D3) re-encodes each image in its own format and PNG is lossless. Options: (a) keep the rule and tell catalogue staff to upload photos as JPEG or WebP (admin guide); (b) convert PNG uploads without transparency to JPEG, which changes approved decision D3 and the stored format. Engineering recommendation: (a) for the MVP. It needs no code change, and transparent PNGs (logos, cut-outs) stay intact. Owner: Technical Product Lead with engineering lead.
- Portrait photos are limited by width only (1600 px), so a tall image can be 2133 px high. This is as the plan specifies.
- Caching: files are written once under random keys, so production can serve them with `Cache-Control: public, max-age=31536000, immutable` (`docs/deployment/media.md`). The development server (`/media`) does not set caching headers; it is not used for TC-21.

## Decisions

### D-M1 — Staging and production media serving (needs ADR-004; operations and engineering lead)

Question: where are images stored and served outside development? The options and the engineering recommendation (local disk on one API host behind the TLS proxy for the MVP) are in `docs/deployment/media.md`. Impact: until this is decided and set up, a staging or production deployment has no working image URLs, and TC-21 cannot run. Nothing in the code has to change for options A or B.

### D-M2 — An oversized upload gets 413 before authentication (engineering lead / security reviewer)

Behaviour: the upload size middleware runs in front of the application, so a request over 5 MB + 64 KB gets 413 `file_too_large` whether or not it is authenticated. A request within the limit is authenticated before anything is processed or stored: an anonymous one gets 401, a forbidden one 403.

Why it is so: FastAPI reads the whole multipart body before any dependency, including authentication, runs. Checking authentication first would mean either accepting the full upload from anyone before refusing it, or repeating session validation inside the middleware.

Impact: a 413 reveals nothing that the public OpenAPI document does not already show, and nothing is stored or read beyond the limit. The cost is that an anonymous client can make the API read and discard up to 32 MB (`DRAIN_LIMIT_BYTES`) per request before the connection closes. A proxy size limit in front of the API (`docs/deployment/media.md` item 4) bounds this on deployed environments.

Options: (a) keep as is and document it (done: OpenAPI 413 description, test); (b) skip draining for requests without an `Authorization` header (close straight after the 413), which reduces the cost but can show those clients a connection reset instead of the 413; (c) validate the session in the middleware.

Recommendation: **(a)**. Behaviour is unchanged on this branch, and the reviewer should confirm it.

### D-M3 — Order history and image deletion (decision for module 14; Technical Product Lead)

Today: deleting an image removes its row and then its files. `order_items.image_snapshot` exists as a plain string, but nothing writes it, because checkout (module 14) does not exist. A search of `backend/app` and `scripts` on 2026-10-24 found no writer. So no current order can lose an image.

Risk: if checkout later stores a catalogue image key in `image_snapshot`, deleting that image removes the file the order points to. ADR-002 leaves open whether order history shows an image at all ("Decide whether to preserve … image reference for order-history rendering").

Options for module 14:
- (a) Order history shows no image; `image_snapshot` stays null. No change to module 7.
- (b) Checkout copies the thumbnail to an order-owned key (for example `orders/<order id>/<line>.<ext>`) and stores that key. The order's image never depends on the catalogue, and image deletion stays as it is. It needs a small copy step and an additional key pattern in `MediaStorage`.
- (c) Checkout stores the catalogue key, and image deletion keeps files that any order item references. This needs a SELECT grant on `order_items` for the runtime role and a check in the delete path. The files then outlive the image row.

Recommendation: **(b)**, decided as part of the module 14 plan. Module 7 is not changed now: granting `order_items` access and changing delete behaviour before checkout exists would add privileges that nothing uses.

### D-M4 — Seed data (recorded decision)

Decision: module 7 adds no seed images. Product photos are business catalogue input: PRD §7 assigns the "initial catalogue of 100–200 products with photos, specs, price and stock" to Merchandising/business as required input, and ADR-002 says to "not invent … business catalogue data" in seeds. Module 5 recorded the same decision for categories and brands. `scripts/seed_dev.py` (plan §2) does not exist for any module yet. Tests create disposable images in a temporary `MEDIA_ROOT`. If a shared development seed is approved later, it should create placeholder images through `ImageAdminService.upload`, so that seeded files follow the same processing and key rules. The reviewer can overrule this.

## Open items before module 7 can be marked Done

1. Human review and approval of the pull request (Technical plan §5: "pull request review required").
2. D-M1: the ADR-004 hosting decision, then serving set up on staging per `docs/deployment/media.md`.
3. TC-21 on the storefront over a throttled mobile connection, after the storefront pages and staging exist; decide F-1.
4. Reviewer confirmation of D-M2 and D-M4; D-M3 to be closed in the module 14 plan.
5. Migration status: PR #23 (the revert) was merged on 2026-10-24, and `dev` was merged into this branch without conflicts. No deployed environment exists in the repository (no GitHub environments, deployments or secrets), and the local development database is at `37b61c6765c1`. Teammates' local databases are not verified; anyone at `76768b844c03` sees Alembic fail until PR #24 is merged.
6. Deployment to staging (outside this repository).
