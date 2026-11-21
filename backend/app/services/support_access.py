"""The private link to a support conversation (2026-11-11), for senders without an account.

The key is an HMAC of the conversation's ID under AUDIT_HMAC_KEY, with its own label so it can
never equal another use of that key. Nothing is stored: the link shown after sending and the one
in the reply email are recomputed from the ID, and a request's key is checked in constant time.
Anyone holding the link can read and answer the conversation, as with the review links.
"""

import base64
import hashlib
import hmac
from uuid import UUID

from app.core.config import get_settings

KEY_LENGTH = 32  # base64url characters (192 bits)
_LABEL = b"support-thread-access:v1:"


def access_key(thread_id: UUID) -> str:
    secret = get_settings().audit_hmac_key.get_secret_value().encode()
    digest = hmac.new(secret, _LABEL + str(thread_id).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:KEY_LENGTH]


def key_matches(thread_id: UUID, key: str) -> bool:
    return hmac.compare_digest(access_key(thread_id), key)


def guest_path(reference: str, thread_id: UUID) -> str:
    """The storefront path of the private link (no locale prefix)."""
    return f"/support/{reference}/{access_key(thread_id)}"
