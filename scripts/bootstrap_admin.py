"""Create the first administrator account (operator-only; ADR-006, approved 2026-10-22).

Run from backend/ after `alembic upgrade head`:

    uv run python ../scripts/bootstrap_admin.py --email admin@example.rw --full-name "A. Admin"
    uv run python ../scripts/bootstrap_admin.py --phone 0788000000 --full-name "A. Admin"

- Operator-only: connects with MIGRATION_DATABASE_URL (the schema-owner account) and refuses if
  it is unset or is the same account as the application's DATABASE_URL. There is no fallback to
  the application account and no HTTP route.
- The password is read from a hidden prompt (entered twice), or as one line from stdin with
  --password-stdin. It is never accepted as an argument, printed or logged. There is no default.
- Refuses while any active administrator exists; later staff are created through the API.
  If every administrator has been disabled, it can be used again to recover access.
- A database lock serialises runs, so concurrent runs cannot create two administrators.
- Writes a 'staff.bootstrap_administrator' audit record in the same transaction, noting whether
  it was a first setup or a recovery, and the database and OS accounts that ran it.
"""

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.schemas.staff import StaffCreateRequest  # noqa: E402
from app.services.staff_service import StaffBootstrapError, StaffService  # noqa: E402


def _read_password(from_stdin: bool) -> str | None:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Administrator password: ")
    if first != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return None
    return first


def _os_user() -> str | None:
    try:
        return getpass.getuser()[:80]
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the first administrator account.")
    parser.add_argument("--email")
    parser.add_argument("--phone")
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    owner = settings.migration_database_url
    owner_url = owner.get_secret_value().strip() if owner else ""
    if not owner_url:
        print("Set MIGRATION_DATABASE_URL to the schema-owner account.", file=sys.stderr)
        return 2
    if make_url(owner_url).username == make_url(settings.database_url.get_secret_value()).username:
        print(
            "MIGRATION_DATABASE_URL uses the application account; use the schema-owner account.",
            file=sys.stderr,
        )
        return 2

    password = _read_password(args.password_stdin)
    if password is None:
        return 2
    try:
        req = StaffCreateRequest(
            email=args.email,
            phone=args.phone,
            full_name=args.full_name,
            password=password,
            role="administrator",
        )
    except ValidationError as exc:
        # Print messages only: error input values could contain the password.
        for err in exc.errors(include_input=False):
            print(f"Invalid input: {err['msg']}", file=sys.stderr)
        return 2

    engine = create_engine(owner_url, pool_pre_ping=True, hide_parameters=True)
    try:
        with sessionmaker(bind=engine, expire_on_commit=False)() as db:
            user = StaffService.bootstrap_administrator(db, req, os_user=_os_user())
    except StaffBootstrapError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Administrator created: {user.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
