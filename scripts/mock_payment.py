"""Approve or fail a mock mobile-money payment in development (frontend phase 4, 2026-10-27).

Mobile money uses the `mock` provider until ADR-003 (§7 Q21). It settles only when a signed
webhook arrives, which nothing sends in development. This script plays the provider for one
order: it finds the order's open mock request, signs an event with PAYMENT_MOCK_WEBHOOK_SECRET
(from the environment or backend/.env) and hands it to the same webhook handler the API uses,
so the signature check and every payment rule run as for a real callback.

Refuses to run unless APP_ENV=development is set explicitly (environment or backend/.env), like
seed_dev.py. Run from backend/ after starting the payment on the storefront:

    uv run python ../scripts/mock_payment.py ORD-261027-ABC123 --succeed
    uv run python ../scripts/mock_payment.py ORD-261027-ABC123 --fail [--reason insufficient_funds]

Prints only the order number and the outcome, never the secret, a phone number or a signature.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_dev import explicit_app_env  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.payments import WebhookRequest  # noqa: E402
from app.integrations.payments.mock import REASON_CODES, sign  # noqa: E402
from app.models import Order, PaymentAttempt  # noqa: E402
from app.services.payment_service import PaymentService  # noqa: E402

REFUSED = (
    "mock_payment.py runs only when APP_ENV=development is set explicitly (environment or .env)."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Settle a mock mobile-money payment (development)."
    )
    parser.add_argument("order_number", help="e.g. ORD-261027-ABC123")
    outcome = parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--succeed", action="store_true", help="the customer approved it")
    outcome.add_argument("--fail", action="store_true", help="the request failed or was declined")
    parser.add_argument(
        "--reason", choices=sorted(REASON_CODES), default="declined", help="with --fail"
    )
    return parser.parse_args(argv)


def settle(db: Session, order_number: str, *, succeed: bool, reason: str, secret: str) -> str:
    """Send one signed mock event for the order's open request; returns the line to print."""
    number = order_number.strip().upper()
    attempt = db.scalar(
        select(PaymentAttempt)
        .join(Order, Order.id == PaymentAttempt.order_id)
        .where(Order.order_number == number)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc())
        .limit(1)
    )
    if attempt is None or attempt.provider != "mock" or not attempt.provider_reference:
        raise LookupError(
            f"{number}: no mock mobile-money request has been started for this order."
        )
    event: dict[str, object] = {
        "event_id": f"dev-{uuid.uuid4().hex}",
        "reference": attempt.provider_reference,
        "status": "succeeded" if succeed else "failed",
        "amount": attempt.amount,
        "currency": attempt.currency_code,
    }
    if not succeed:
        event["reason"] = reason
    body = json.dumps(event).encode("utf8")
    timestamp = int(time.time())
    headers = {
        "content-type": "application/json",
        "x-mock-timestamp": str(timestamp),
        "x-mock-signature": sign(body, timestamp, secret),
    }
    ack = PaymentService.webhook(db, "mock", WebhookRequest(headers=headers, body=body))
    db.refresh(attempt)
    return f"{number}: event {ack.status}; payment {attempt.status}."


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if explicit_app_env() != "development":  # checked before settings or any connection
        print(REFUSED, file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.app_env != "development":
        print(REFUSED, file=sys.stderr)
        return 2
    secret = settings.payment_mock_webhook_secret
    if secret is None or not secret.get_secret_value():
        print("PAYMENT_MOCK_WEBHOOK_SECRET is not set (see backend/.env.example).", file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
            print(
                settle(
                    db,
                    args.order_number,
                    succeed=args.succeed,
                    reason=args.reason,
                    secret=secret.get_secret_value(),
                )
            )
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
