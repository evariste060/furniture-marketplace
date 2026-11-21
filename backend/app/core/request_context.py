"""Bounded, validated request metadata for sessions and audit records.

Header-derived values are untrusted: they are validated and truncated here so that oversized or
malformed metadata can never make a database write fail.
"""

import hashlib
import hmac
import ipaddress
import logging
import re
import time
from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings

USER_AGENT_MAX_LENGTH = 512  # matches user_sessions.user_agent and audit_records.user_agent
IP_ADDRESS_MAX_LENGTH = 45


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None
    user_agent: str | None


def sanitize_user_agent(value: str | None) -> str | None:
    if not value:
        return None
    # Drop control characters (including NUL, which PostgreSQL text cannot store).
    cleaned = "".join(ch for ch in value if ch.isprintable())
    cleaned = cleaned.strip()[:USER_AGENT_MAX_LENGTH]
    return cleaned or None


def sanitize_ip_address(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))[:IP_ADDRESS_MAX_LENGTH]
    except ValueError:
        return None


# ---- the client IP vouched for by the storefront (ADR-006, client IP, 2026-11-13) --------------
# Shoppers reach the API through the storefront's server (the BFF on Vercel), so the transport
# peer is that server or the host's load balancer, never the shopper. With CLIENT_IP_SOURCE=signed
# the BFF sends the shopper's address with an HMAC over it, a timestamp, the method and the path.
# The address is used only when the signature verifies with a configured secret and the timestamp
# is fresh; anything else (missing, malformed, oversized, stale, wrong signature) falls back to the
# transport peer. X-Forwarded-For is never read here, and uvicorn runs with --no-proxy-headers, so
# nothing a caller writes in a header can choose the address used for rate limits or audit.
CLIENT_IP_HEADER = "x-sixty-client-ip"
CLIENT_IP_SIGNATURE_HEADER = "x-sixty-client-ip-signature"
CLIENT_IP_TIMESTAMP_HEADER = "x-sixty-client-ip-timestamp"
CLIENT_IP_SIGNATURE_VERSION = "sixty-client-ip-v1"
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")  # hex HMAC-SHA256
_TIMESTAMP = re.compile(r"^[0-9]{1,12}$")  # Unix seconds

logger = logging.getLogger(__name__)


def client_ip_message(timestamp: str, ip: str, method: str, path: str) -> bytes:
    """What the BFF signs (frontend/src/lib/client-ip.ts builds the same bytes)."""
    return "\n".join((CLIENT_IP_SIGNATURE_VERSION, timestamp, ip, method.upper(), path)).encode()


def _single(request: Request, name: str, max_length: int) -> str | None:
    """The header's only value, or None when absent, repeated or too long."""
    values = request.headers.getlist(name)
    if len(values) != 1 or len(values[0]) > max_length:
        return None
    return values[0]


def signed_client_ip(request: Request, now: float | None = None) -> str | None:
    """The shopper's address from a valid signature, or None (the caller then uses the peer)."""
    settings = get_settings()
    if settings.client_ip_source != "signed":
        return None
    ip = _single(request, CLIENT_IP_HEADER, IP_ADDRESS_MAX_LENGTH)
    signature = _single(request, CLIENT_IP_SIGNATURE_HEADER, 64)
    timestamp = _single(request, CLIENT_IP_TIMESTAMP_HEADER, 12)
    if ip is None and signature is None and timestamp is None:
        return None  # a direct caller: nothing was vouched for
    reason = None
    if ip is None or signature is None or timestamp is None:
        reason = "incomplete"
    elif not _SIGNATURE.match(signature) or not _TIMESTAMP.match(timestamp):
        reason = "malformed"
    elif abs((time.time() if now is None else now) - int(timestamp)) > (
        settings.client_ip_signature_max_age_seconds
    ):
        reason = "stale"
    if reason is None:
        assert ip is not None and signature is not None and timestamp is not None
        message = client_ip_message(timestamp, ip, request.method, request.url.path)
        valid = False
        for secret in settings.client_ip_signing_secrets:
            expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
            # Every configured secret is compared, in constant time, whatever the first gave.
            valid = hmac.compare_digest(expected, signature) or valid
        if not valid:
            reason = "bad_signature"
        else:
            address = sanitize_ip_address(ip)  # exactly one IPv4 or IPv6 address, normalised
            if address is None:
                reason = "invalid_ip"
            else:
                return address
    # The reason only: never the address, signature, timestamp or secret.
    logger.info("Client IP signature refused (%s); using the transport peer", reason)
    return None


def build_request_context(request: Request) -> RequestContext:
    # The transport peer (uvicorn runs with --no-proxy-headers), unless the storefront's server
    # vouched for the shopper's address with a valid signature (see signed_client_ip).
    peer = request.client.host if request.client else None
    return RequestContext(
        ip_address=signed_client_ip(request) or sanitize_ip_address(peer),
        user_agent=sanitize_user_agent(request.headers.get("user-agent")),
    )


def get_request_context(request: Request) -> RequestContext:
    """FastAPI dependency."""
    return build_request_context(request)


def warn_if_peer_client_ip_in_production() -> None:
    """At API startup: behind the storefront's server, the transport peer is that server or the
    host's load balancer, so every shopper would share one rate-limit bucket (ADR-006)."""
    settings = get_settings()
    if settings.app_env == "production" and settings.client_ip_source == "peer":
        logger.warning(
            "CLIENT_IP_SOURCE=peer with APP_ENV=production: rate limits and audit records use "
            "the transport peer. Behind the storefront, set CLIENT_IP_SOURCE=signed."
        )
