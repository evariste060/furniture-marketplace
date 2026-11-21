# Module 9 (catalogue search) — acceptance record

| Field | Value |
| --- | --- |
| Module | 9 — search (`docs/IMPLEMENTATION_PLAN.md` §5, "9 — search"; §7 Q5) |
| Requirements | PRD PR-02/PR-03 (browse, filter, search by name, brand and model); Technical plan §6 |
| Linked tests | TC-02 (browse category; filter brand and price; sort), TC-03 (search by name, brand and model) |
| Branch | `feat/module-09-search`, stacked on module 8 (`d8c9cc1`, not yet in `dev`), because migration `a3b4d2f1d8e6` follows module 8's `9d820b74f718` |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-24 |
| Recommendation | **Not Done.** The backend is complete and tested. Review, the storefront runs of TC-02/TC-03 and staging are open. |

## Acceptance criteria

| # | Criterion (plan §5) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GET /catalog/products` keeps its filters | Verified | `test_search_combines_with_every_filter`; existing `test_catalog_reports_zero_stock_…`, `test_catalog_validates_filters_…`, `test_catalog_search_fields_punctuation_and_combined_filters` |
| 2 | `sort_by=name\|price\|newest` (price = lowest active variant price) | Verified | `test_price_sort_uses_the_lowest_active_variant` (multi-variant and inactive cheaper variant), `test_products_without_an_active_variant_come_last_in_both_directions`, `test_newest_sort_defaults_to_newest_first`, `test_name_is_the_default_without_a_search`, `test_catalog_name_sort_directions_have_stable_pagination` |
| 3 | `search_vector` tsvector over name, model and brand name, `simple` configuration | Verified | Migration `a3b4d2f1d8e6`; `test_insert_sets_the_vector_with_weights` (exact stored vector) |
| 4 | Trigger maintenance, including brand renames | Verified | `test_product_changes_update_the_vector`, `test_changing_the_brand_of_a_product_updates_its_vector`, `test_renaming_a_brand_updates_only_its_products`, `test_renaming_a_brand_through_the_staff_api_updates_search`, `test_the_vector_cannot_be_overwritten`; runtime role: `tests/postgres/test_pg_search.py` |
| 5 | GIN index | Verified | `test_the_gin_index_exists_and_serves_the_search` (index definition `USING gin`, and the planner uses it) |
| 6 | `q` is full-text search with prefix matching (`websearch_to_tsquery` plus `:*`) | Verified | `test_every_word_matches_as_a_prefix`, `test_model_numbers_match_with_or_without_punctuation`, `test_web_search_syntax`, `test_words_must_all_match`, `test_punctuation_only_matches_nothing`, `test_query_syntax_in_input_is_treated_as_words` |
| 7 | Empty result: 200 with an empty page | Verified | `test_no_match_returns_200_and_an_empty_page`; punctuation-only queries |
| 8 | Tests: name, brand and model matches | Verified | `test_name_brand_and_model_match` |
| 9 | Tests: prefix matches on model numbers | Verified | `test_model_numbers_match_with_or_without_punctuation`, `test_a_full_model_number_matches_only_longer_models_that_extend_it` |
| 10 | Tests: ranking and sort stability | Verified | `test_search_orders_by_relevance_then_name_then_id`, `test_an_explicit_sort_overrides_relevance`, `test_equal_sort_values_page_deterministically_by_id` (every sort mode and the search order) |
| 11 | Tests: combined filters | Verified | `test_search_combines_with_every_filter` |
| 12 | Migration upgrade, downgrade and backfill | Verified | `tests/integration/test_product_search_migration.py` (existing product backfilled with the exact vector; data unchanged; downgrade removes the functions, triggers and column; `alembic check`) |
| 13 | PR reviewed, CI green, staging | **Open** | Not pushed (by instruction) |
| 14 | TC-02/TC-03 recorded | **Partial** | API-level evidence above; the storefront search and filter screens do not exist yet |

## TC-03 — Search by name, brand and model (API level)

| Field | Value |
| --- | --- |
| Status | **Pass** (API level). The storefront run, including the helpful no-results state, waits for the frontend. |
| Tester / date | Backend engineering, 2026-10-24 |
| Environment | Local, PostgreSQL 18.6, disposable test database, branch `feat/module-09-search` |
| Evidence | `test_name_brand_and_model_match`, `test_every_word_matches_as_a_prefix`, `test_model_numbers_match_with_or_without_punctuation`; no-match queries return 200 with an empty page |

## Decisions made within the plan (for the reviewer)

| # | Decision | Why |
| --- | --- | --- |
| D-S1 | Words containing punctuation are also indexed without it ("GX-10" → "gx 10", "gx10"). | The `simple` parser turns "GX-10" into "gx" and "-10", so "10" or "GX 10" would miss the product. Only punctuated words get extra forms, so phrases keep their order. |
| D-S2 | Without `sort_by`, a search is ordered by relevance (name > model > brand weights), then name and ID; `sort_direction` does not apply to that order. | The plan requires ranking; an explicit `sort_by` still wins. |
| D-S3 | `sort_direction` now defaults per field (asc for name and price, desc for newest). | "newest" should list the newest first by default. Name and price keep their former default. |
| D-S4 | Products without an active variant sort last by price in both directions. | They have no price; putting them last is deterministic and keeps priced products first. |
| D-S5 | A search phrase can span the end of the name and the start of the model (for example `"max gx"` on "ProBook Max" / "GX-100"). | Fields are concatenated in one vector. This matches how the product is usually written and is not broader than the plain words. |

## Open items before module 9 can be marked Done

1. Merge module 8 first (this branch contains it), then review this pull request.
2. TC-02 and TC-03 on the storefront when the search and listing pages exist.
3. Staging deployment (the migration backfills every product once; the catalogue is 100–200 products).
