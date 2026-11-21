"""One logging configuration for the API (module 1, core).

Every log line, including uvicorn's own and exception tracebacks, goes through one handler whose
formatter redacts secrets and personal data from the final text. Code should still never log
request bodies or credentials; redaction is the second line of defence (ADR-006: no unnecessary
personal data in logs).
"""

import logging
import re
import sys
from typing import TextIO

# uvicorn's console layout ("INFO:     Application startup complete."), applied to every logger.
LOG_FORMAT = "%(levelprefix)s %(message)s"
REDACTED = "[REDACTED]"
# uvicorn installs its own handlers on these and stops propagation; route them through ours.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
_HANDLER_NAME = "app-redacting-handler"

_SECRET_KEYS = (
    r"password|passwd|new_password|secret|token|session_token|access_token|refresh_token"
    r"|authorization|api_key|apikey|audit_hmac_key|reset_code|verification_code|otp|signature"
)
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer <token>
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    # Credentials inside connection URLs: scheme://user:password@host -> scheme://user:***@host
    (re.compile(r"([a-z][a-z0-9+.-]*://[^\s:/@]*:)[^\s@/]+@", re.IGNORECASE), rf"\1{REDACTED}@"),
    # key=value / "key": "value" pairs whose key names a secret
    (
        re.compile(
            rf"""(?ix)
            (["']?\b(?:{_SECRET_KEYS})\b["']?\s*[:=]\s*)
            ("[^"]*"|'[^']*'|[^\s,&;}}\]]+)
            """
        ),
        rf"\1{REDACTED}",
    ),
    # Email addresses
    (re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), "[EMAIL]"),
    # Rwandan mobile numbers in any accepted format (+2507..., 2507..., 07...)
    (re.compile(r"(?<![0-9A-Za-z])(?:\+?250|0)7\d{8}(?![0-9A-Za-z])"), "[PHONE]"),
)


def redact(text: str) -> str:
    """Mask secrets and personal identifiers in already-formatted log text."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formats normally (message, arguments, traceback), then redacts the whole result."""

    def format(self, record: logging.LogRecord) -> str:
        # Level name and colon padded like uvicorn's default formatter: "INFO:    ", "WARNING: ".
        record.levelprefix = f"{record.levelname}:".ljust(9)
        return redact(super().format(record))


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> logging.Handler:
    """Install the single redacting handler on the root and uvicorn loggers.

    Safe to call more than once: the previously installed handler is replaced, never duplicated;
    handlers added by other tools are left alone.
    """
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))

    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == _HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False
    return handler
