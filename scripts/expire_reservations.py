"""Expire stock holds whose expiry time has passed (ADR-002 lifecycle, approved 2026-10-22).

Run from backend/ on a schedule (cron, a systemd timer or Windows Task Scheduler), e.g. every
minute:

    uv run python ../scripts/expire_reservations.py

- Uses DATABASE_URL (the least-privilege runtime account) from backend/.env or the environment.
- Expiry uses database time. Several copies may run at once and the script may be retried at
  any time: each order is locked before it is expired and busy orders are skipped, so no hold
  is released twice and expiry never races a payment commit.
- Processes batches until no free due order is left (or --max-batches is reached). Each batch
  commits on its own, with one audit record per expired order. Orders held by another worker or a
  payment commit are left to that transaction; anything still due is picked up on the next run.
- Exit codes: 0 done, 1 database error.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.services.inventory import expire_due_reservations  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expire due stock reservations.")
    parser.add_argument("--batch-size", type=int, default=100, help="orders per batch (1-1000)")
    parser.add_argument("--max-batches", type=int, default=50, help="stop after this many")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000 or args.max_batches < 1:
        parser.error("--batch-size must be 1-1000 and --max-batches at least 1")

    orders = lines = 0
    try:
        for _ in range(args.max_batches):
            with SessionLocal() as session:
                result = expire_due_reservations(session, limit=args.batch_size)
            orders += result.orders
            lines += result.lines
            if result.orders < args.batch_size:
                break
    except SQLAlchemyError as exc:
        print(f"Database error: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"Expired {orders} order(s), {lines} reservation line(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
