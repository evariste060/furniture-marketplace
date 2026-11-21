"""Send due order notifications and retry failed ones (module 17; plan §5 "17 — notifications").

Run from backend/ on a schedule (cron, a systemd timer or Windows Task Scheduler), e.g. every
minute:

    uv run python ../scripts/retry_notifications.py

- Uses DATABASE_URL (the least-privilege runtime account) and NOTIFICATION_PROVIDER from
  backend/.env or the environment. With NOTIFICATION_PROVIDER=none it sends nothing and exits 0.
- Sends every due notification: first attempts that the API did not send (the process stopped,
  or the expiry job cancelled the order) and retries whose time has come. At most 3 attempts per
  notification, 5 then 30 minutes apart (app/services/notification_service.py).
- Several copies may run at once and the script may be retried at any time: each row is
  claimed (FOR UPDATE SKIP LOCKED) only just before its provider call, with a 2-minute lease
  renewed while the call runs, so no notification is sent by two workers at once while the
  sending worker can reach the database. A row whose worker stopped is picked up again when its
  lease ends (outcome_unknown); one that had used its last attempt is closed as failed
  (outcome_unknown). A database error stops the run (exit 1) before any further row is claimed,
  so no attempt is counted for a row that was not sent.
- Prints counts only: never recipients or message text.
- Exit codes: 0 done, 1 database error.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.integrations.notifications import get_notification_provider  # noqa: E402
from app.services.notification_service import (  # noqa: E402
    DeliveryResult,
    SessionFactory,
    close_abandoned,
    deliver,
)


def run(
    session_factory: SessionFactory, *, batch_size: int, max_batches: int
) -> tuple[DeliveryResult, int] | None:
    """Close abandoned rows, then deliver batches until none is full. None: no provider."""
    provider = get_notification_provider()
    if provider is None:
        return None
    with session_factory() as session:
        closed = close_abandoned(session)
    total = DeliveryResult()
    for _ in range(max_batches):
        result = deliver(session_factory, provider, limit=batch_size)
        total.sent += result.sent
        total.retry_scheduled += result.retry_scheduled
        total.failed += result.failed
        total.lost_claims += result.lost_claims
        if result.claimed < batch_size:
            break
    return total, closed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send due order notifications.")
    parser.add_argument(
        "--batch-size", type=int, default=50, help="notifications per batch (1-500)"
    )
    parser.add_argument("--max-batches", type=int, default=20, help="stop after this many")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 500 or args.max_batches < 1:
        parser.error("--batch-size must be 1-500 and --max-batches at least 1")
    configure_logging(get_settings().log_level)  # IDs and codes only (notification_service)

    try:
        outcome = run(SessionLocal, batch_size=args.batch_size, max_batches=args.max_batches)
    except SQLAlchemyError as exc:
        print(f"Database error: {type(exc).__name__}", file=sys.stderr)
        return 1
    if outcome is None:
        print("NOTIFICATION_PROVIDER=none: notifications are off; nothing sent.")
        return 0
    result, closed = outcome
    print(
        f"Sent {result.sent}; retry scheduled {result.retry_scheduled}; failed {result.failed}; "
        f"lost claims {result.lost_claims}; abandoned closed {closed}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
