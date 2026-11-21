# ADR-010: Durable job queue and worker process

Status: **Accepted** by the project owner on 2026-10-26 (checkpoint 1b, topic 4).

## Context

Bulk image upload (up to 20 files per request) must decode and store every file, which is too slow to finish inside the request. FastAPI background tasks run in the API process and are lost when it restarts, so work could disappear silently. The media registry (ADR-009) also needs a process that deletes retired files.

## Decision

1. **Jobs live in PostgreSQL** (revision `d5f9b3c7e1a2`, `app/models/jobs.py`). `jobs` holds one request's work (type, state `queued` → `processing` → `finished`, creator, counts, `finished_at`); `job_items` holds one unit of work each (state `queued`/`processing`/`done`/`failed`, `attempts`, `locked_at`, `error`, `result`, `payload`, and a `target` naming what it changes). `(job_id, item_index)` is unique.
2. **A separate worker process** does the work: `uv run python -m app.worker`, run next to the API with the same `DATABASE_URL` (the runtime role) and `MEDIA_ROOT`. It runs `JOB_WORKER_CONCURRENCY` job threads (default 2) and the housekeeping loop (media cleanup, stale items, stale imports). `--once` runs one pass; several workers may run at once.
3. **Claiming** (`app/services/jobs.py`): one transaction locks the next queued item with `SELECT … FOR UPDATE SKIP LOCKED`, marks it `processing` (attempts + 1, `locked_at`) and commits, so two workers never take the same item. Items run in (job `created_at`, item index) order; an item is not claimed while an earlier unfinished item has the same `target`, so two changes to the same thing (for example one product image position) land in job order.
4. **Failures.** A handler raises `ItemFailed` for a permanent failure (the item is `failed` with `<code>: <message>`). Any other error requeues the item until 3 attempts, then fails it. An item `processing` for more than 10 minutes belongs to a stopped worker and is requeued (or failed after 3 attempts). Staff requeue a job's failed items with `POST /staff/jobs/{id}/retry-failed` (audited as `job.retry_failed`); items rejected before they were queued (result `"final": true`) cannot be retried.
5. **Audit context.** Work done for a job is audited with the job's creator as actor and `request_id = job:<id>`.
6. **Catalogue import stays synchronous** (decision of 2026-10-26). It runs inside its request in one transaction, so a crash rolls back every catalogue change; only the `import_jobs` row could be left `processing`. The worker marks such a row failed after 10 minutes, with an audit record. Revisit (move the import onto this queue) if an import exceeds about 2 000 rows or 30 seconds.

## Consequences

- Development runs two processes: the API and the worker (README). Without the worker, queued jobs wait and retired image files stay on disk; the API itself keeps working.
- Grants: the runtime role has `SELECT, INSERT, UPDATE` on `jobs` and `job_items`; nothing is deleted.
- New job types add a value to the `jobs.type` check constraint (migration) and a handler in `app.services.jobs.HANDLERS`.
