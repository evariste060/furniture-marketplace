"""Background worker process (ADR-009; checkpoint 1b, 2026-10-26). Run it next to the API:

    uv run python -m app.worker            # run until stopped (Ctrl+C)
    uv run python -m app.worker --once     # one pass of every task, then exit
    uv run python -m app.worker reconcile  # list stored files without a registry row

It connects with DATABASE_URL (the runtime role) and:
- processes queued job items (bulk image upload) on JOB_WORKER_CONCURRENCY threads; items are
  claimed with SKIP LOCKED, so several workers may run at once (app.services.jobs);
- requeues items whose worker stopped mid-item, and marks catalogue imports left 'processing'
  by a stopped API process as failed;
- does the media cleanup: at start and every 15 minutes it sweeps abandoned and expired files,
  and every few seconds it deletes the files the API has retired (app.services.media_cleanup);
- once a week logs how many stored files have no registry row (report only).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from datetime import UTC, datetime, timedelta
from types import FrameType

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.integrations.media import get_media_storage
from app.services import bulk_images, jobs, media_cleanup
from app.services.catalog_import import fail_stale_imports

logger = logging.getLogger("app.worker")
JOB_TYPES = (bulk_images.JOB_TYPE,)  # importing a job module registers its handler

IDLE_SECONDS = 5.0
RECONCILE_INTERVAL = timedelta(days=7)
MAX_ITEMS_PER_PASS = 50


class Worker:
    def __init__(self) -> None:
        self.stopping = threading.Event()
        self.storage = get_media_storage()
        self.next_sweep = datetime.min.replace(tzinfo=UTC)
        self.next_reconcile = datetime.now(UTC) + RECONCILE_INTERVAL

    def stop(self, signum: int, frame: FrameType | None) -> None:
        logger.info("Worker stopping (signal %d)", signum)
        self.stopping.set()

    def maintain(self) -> bool:
        """Housekeeping: stale items and imports, the media sweep and deletions, reconcile."""
        now = datetime.now(UTC)
        with SessionLocal() as db:
            busy = bool(jobs.requeue_stale(db, now))
            if now >= self.next_sweep:
                media_cleanup.sweep(db, now)
                fail_stale_imports(db, now)
                self.next_sweep = now + media_cleanup.SWEEP_INTERVAL
            result = media_cleanup.delete_due(db, self.storage, now)
            busy = busy or bool(result.deleted or result.failed)
            if now >= self.next_reconcile:
                unknown = media_cleanup.reconcile(db, self.storage)
                logger.info(
                    "Media reconciliation: %d stored files have no registry row", len(unknown)
                )
                self.next_reconcile = now + RECONCILE_INTERVAL
        return busy

    def process_one(self) -> bool:
        """Claim and process one job item. False when none is ready."""
        with SessionLocal() as db:
            item_id = jobs.claim_next(db, datetime.now(UTC))
            if item_id is None:
                return False
            jobs.process(db, item_id, datetime.now(UTC))
        return True

    def run_once(self) -> bool:
        """One pass of every task (used by --once and tests). True when something was done."""
        busy = self.maintain()
        for _ in range(MAX_ITEMS_PER_PASS):
            if not self.process_one():
                break
            busy = True
        return busy

    def _job_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                busy = self.process_one()
            except Exception:  # noqa: BLE001 - keep the thread alive; the item is requeued
                logger.exception("Job item processing failed")
                busy = False
            if not busy:
                self.stopping.wait(IDLE_SECONDS)

    def run_forever(self) -> None:
        concurrency = get_settings().job_worker_concurrency
        threads = [
            threading.Thread(target=self._job_loop, name=f"job-{n}", daemon=True)
            for n in range(concurrency)
        ]
        for thread in threads:
            thread.start()
        logger.info("Worker started (%d job threads)", concurrency)
        while not self.stopping.is_set():
            try:
                busy = self.maintain()
            except Exception:  # noqa: BLE001 - keep the worker alive; the next pass retries
                logger.exception("Worker maintenance pass failed")
                busy = False
            if not busy:
                self.stopping.wait(IDLE_SECONDS)
        for thread in threads:
            thread.join(timeout=30)
        logger.info("Worker stopped")


def reconcile() -> int:
    with SessionLocal() as db:
        unknown = media_cleanup.reconcile(db, get_media_storage())
    for visibility, key in unknown:
        print(f"{visibility}\t{key}")
    print(f"{len(unknown)} stored file(s) without a registry row (nothing was deleted).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker", description=__doc__)
    parser.add_argument("command", nargs="?", choices=["run", "reconcile"], default="run")
    parser.add_argument("--once", action="store_true", help="one pass of every task, then exit")
    args = parser.parse_args(argv)
    configure_logging()
    if args.command == "reconcile":
        return reconcile()
    worker = Worker()
    if args.once:
        worker.run_once()
        return 0
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
