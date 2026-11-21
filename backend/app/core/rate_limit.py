"""Rate limiting backed by a shared store (Redis), so limits hold across all workers.

Approved policy (2026-10-21): fixed window of LOGIN_WINDOW_SECONDS (900 s) starting at the first
failed attempt; at most LOGIN_MAX_FAILURES_PER_IDENTIFIER (5) failures per normalised identifier
and LOGIN_MAX_FAILURES_PER_IP (20) failures per source IP. Further attempts get HTTP 429 until the
window expires. Blocks are always temporary. A successful login clears the identifier counter.
Counters are keyed by the HMAC pseudonym of the identifier, so the store never holds raw emails
or phone numbers, and unknown identifiers are counted exactly like real ones (no enumeration).
"""

import ipaddress
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import redis

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.rate_limit")


class RateLimitStoreUnavailable(Exception):
    """The shared counter store could not be reached."""


class RateLimitStore(Protocol):
    def get(self, key: str) -> tuple[int, int]:
        """Return (count, seconds_until_reset) for key; (0, 0) when absent."""

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Atomically increment key; start its window if new. Return (count, ttl)."""

    def reset(self, key: str) -> None: ...


class RedisRateLimitStore:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def get(self, key: str) -> tuple[int, int]:
        try:
            pipe = self._client.pipeline(transaction=True)
            pipe.get(key)
            pipe.ttl(key)
            raw, ttl = pipe.execute()
        except redis.RedisError as exc:
            raise RateLimitStoreUnavailable from exc
        if raw is None:
            return 0, 0
        return int(raw), max(int(ttl), 0)

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        try:
            pipe = self._client.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)  # window starts at first failure only
            pipe.ttl(key)
            count, _, ttl = pipe.execute()
        except redis.RedisError as exc:
            raise RateLimitStoreUnavailable from exc
        return int(count), max(int(ttl), 0)

    def reset(self, key: str) -> None:
        try:
            self._client.delete(key)
        except redis.RedisError as exc:
            raise RateLimitStoreUnavailable from exc


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0
    scope: str | None = None  # "identifier" or "ip"


class LoginRateLimiter:
    """Fixed-window limiter per identifier and per IP. `prefix` keeps separate counters per flow
    (login, password reset, guest order lookup); the values are the approved login policy unless
    a flow passes its own (guest order lookup, ADR-008 S6)."""

    def __init__(
        self,
        store: RateLimitStore,
        settings: Settings,
        prefix: str = "login",
        *,
        max_identifier: int | None = None,
        max_ip: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        self._store = store
        self._prefix = prefix
        self._window = window_seconds or settings.login_window_seconds
        self._max_identifier = max_identifier or settings.login_max_failures_per_identifier
        self._max_ip = max_ip or settings.login_max_failures_per_ip

    def _identifier_key(self, identifier_pseudonym: str) -> str:
        return f"rl:{self._prefix}:id:{identifier_pseudonym}"

    def _ip_key(self, ip_address: str | None) -> str:
        return f"rl:{self._prefix}:ip:{ip_address or 'unknown'}"

    def check(self, identifier_pseudonym: str, ip_address: str | None) -> RateLimitDecision:
        count, ttl = self._store.get(self._identifier_key(identifier_pseudonym))
        if count >= self._max_identifier:
            return RateLimitDecision(False, max(ttl, 1), "identifier")
        count, ttl = self._store.get(self._ip_key(ip_address))
        if count >= self._max_ip:
            return RateLimitDecision(False, max(ttl, 1), "ip")
        return RateLimitDecision(True)

    def record_failure(self, identifier_pseudonym: str, ip_address: str | None) -> None:
        self._store.hit(self._identifier_key(identifier_pseudonym), self._window)
        self._store.hit(self._ip_key(ip_address), self._window)

    def record_success(self, identifier_pseudonym: str) -> None:
        self._store.reset(self._identifier_key(identifier_pseudonym))


@lru_cache
def _redis_client(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url, socket_timeout=1.0, socket_connect_timeout=1.0, decode_responses=True
    )


def get_login_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency. Overridden in tests with an in-memory store."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(store, settings)


def get_order_lookup_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: guest order lookups (module 14, ADR-008 S6) on their own
    `order_lookup` counters and values; every failed lookup counts, per order number and per IP."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="order_lookup",
        max_identifier=settings.order_lookup_max_failures_per_order,
        max_ip=settings.order_lookup_max_failures_per_ip,
        window_seconds=settings.order_lookup_window_seconds,
    )


def get_review_submit_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: review submissions (module 20) on their own `review_submit` counters;
    every attempt counts, per review link (its hash) and per client network."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="review_submit",
        max_identifier=settings.review_submit_max_per_token,
        max_ip=settings.review_submit_max_per_ip,
        window_seconds=settings.review_submit_window_seconds,
    )


def get_quote_request_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: business quote requests (module 19) on their own `quote_request`
    counters; every attempt counts, per phone number (pseudonym) and per client network."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="quote_request",
        max_identifier=settings.quote_request_max_per_phone,
        max_ip=settings.quote_request_max_per_ip,
        window_seconds=settings.quote_request_window_seconds,
    )


def get_service_request_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: service requests (ADR-013) on their own `service_request` counters;
    every attempt counts, per phone number (pseudonym) and per client network."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="service_request",
        max_identifier=settings.service_request_max_per_phone,
        max_ip=settings.service_request_max_per_ip,
        window_seconds=settings.service_request_window_seconds,
    )


def get_support_message_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: support messages on their own `support_message` counters; every
    message counts, per sender (pseudonym) and per client network."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="support_message",
        max_identifier=settings.support_message_max_per_sender,
        max_ip=settings.support_message_max_per_ip,
        window_seconds=settings.support_message_window_seconds,
    )


def get_password_reset_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: the login policy on `reset` counters; every code request counts."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(store, settings, prefix="reset")


def get_reset_code_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: the login policy on `reset_code` counters; every failed code counts.

    Kept apart from code requests so that asking for a code never uses up the attempts allowed
    for entering it.
    """
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(store, settings, prefix="reset_code")


def get_verification_resend_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: email verification resends (ADR-006 amendment 2026-11-12) on their own
    `verify_resend` counters. Every request counts, per address and per IP, whether or not an
    account matches, so the limit itself reveals nothing about accounts."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="verify_resend",
        max_identifier=settings.email_verification_resend_max_per_email,
        max_ip=settings.email_verification_resend_max_per_ip,
        window_seconds=settings.email_verification_resend_window_seconds,
    )


def get_email_verify_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: failed email verification attempts on `verify_email` counters, per
    client network (callers pass the network as both the identifier and the IP)."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="verify_email",
        max_identifier=settings.email_verification_max_failures_per_ip,
        max_ip=settings.email_verification_max_failures_per_ip,
        window_seconds=settings.email_verification_failure_window_seconds,
    )


def get_google_auth_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency: Continue with Google (ADR-006 amendment 2026-11-11) on its own
    `google_auth` counters. Every start and every failed callback counts, per client network
    (callers pass the network as both the identifier and the IP)."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return LoginRateLimiter(
        store,
        settings,
        prefix="google_auth",
        max_identifier=settings.google_auth_max_per_network,
        max_ip=settings.google_auth_max_per_network,
        window_seconds=settings.google_auth_window_seconds,
    )


# ---- cart abuse limits (module 11; security decisions S1 and S3) -------------------------------
def client_network(ip_address: str | None) -> str:
    """The bucket for per-client limits: the IPv4 address, or the IPv6 /64 network (one
    subscriber usually holds a whole /64, so per-address IPv6 keys are trivially rotated).
    An IPv4 client seen through a dual-stack IPv6 socket (::ffff:a.b.c.d) is bucketed by its
    IPv4 address, like any IPv4 client. Requests without a usable address share one 'unknown'
    bucket. The address is the direct peer (app.core.request_context): uvicorn rewrites it from
    X-Forwarded-For only for connections from --forwarded-allow-ips (default 127.0.0.1)."""
    if not ip_address:
        return "unknown"
    try:
        address = ipaddress.ip_address(ip_address)
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


class CartRateLimiter:
    """Fixed-window limits for anonymous cart abuse, on the shared store of the login limiter.

    - Guest-cart creation (S1): every guest request that would create a cart counts; beyond the
      limit it answers 429. If the store is unreachable, creation is refused (fail closed, like
      login): existing carts keep working because only creation is limited.
    - Stock probing (S3): each 409 insufficient_stock counts, per client network and per cart
      owner; beyond the limit, requests that add units or raise a quantity answer 429 (lowering
      or removing a line always works). If the store is unreachable the probe limit is skipped,
      with a warning on every occurrence: refusing all quantity changes during a Redis outage
      would break every existing cart.
    - Promotion-code guessing (S5, module 13): each refused code (422 promotion_unavailable or
      promotion_not_applicable) counts, per client network and per cart owner; beyond the limit
      POST /cart/apply-code answers 429. Successful applies are not counted and removing a code
      is never limited. If the store is unreachable the limit is skipped with a warning, as S3.
    """

    def __init__(self, store: RateLimitStore, settings: Settings) -> None:
        self._store = store
        self._creations = settings.cart_guest_creations_per_ip
        self._creation_window = settings.cart_guest_creation_window_seconds
        self._refusals = settings.cart_stock_refusals_per_window
        self._refusal_window = settings.cart_stock_refusal_window_seconds
        self._code_refusals = settings.cart_code_refusals_per_window
        self._code_refusal_window = settings.cart_code_refusal_window_seconds

    def hit_guest_creation(self, ip_address: str | None) -> RateLimitDecision:
        """Count one guest-cart creation attempt. Raises RateLimitStoreUnavailable."""
        count, ttl = self._store.hit(
            f"rl:cart_new:{client_network(ip_address)}", self._creation_window
        )
        if count > self._creations:
            return RateLimitDecision(False, max(ttl, 1), "ip")
        return RateLimitDecision(True)

    @staticmethod
    def _refusal_keys(kind: str, ip_address: str | None, owner_key: str | None) -> list[str]:
        keys = [f"rl:{kind}:ip:{client_network(ip_address)}"]
        if owner_key:
            keys.append(f"rl:{kind}:owner:{owner_key}")
        return keys

    def _check(self, kind: str, limit: int, ip: str | None, owner: str | None) -> RateLimitDecision:
        """Refuse once any key has reached the limit; raises RateLimitStoreUnavailable."""
        for key in self._refusal_keys(kind, ip, owner):
            count, ttl = self._store.get(key)
            if count >= limit:
                return RateLimitDecision(False, max(ttl, 1), key.split(":")[2])
        return RateLimitDecision(True)

    def check_stock_probe(self, ip_address: str | None, owner_key: str | None) -> RateLimitDecision:
        try:
            return self._check("cart_stock", self._refusals, ip_address, owner_key)
        except RateLimitStoreUnavailable:
            logger.warning("Cart stock-probe limit skipped: the rate-limit store is unavailable")
        return RateLimitDecision(True)

    def record_stock_refusal(self, ip_address: str | None, owner_key: str | None) -> None:
        try:
            for key in self._refusal_keys("cart_stock", ip_address, owner_key):
                self._store.hit(key, self._refusal_window)
        except RateLimitStoreUnavailable:
            logger.warning("Cart stock refusal not counted: the rate-limit store is unavailable")

    def check_code_attempt(
        self, ip_address: str | None, owner_key: str | None
    ) -> RateLimitDecision:
        try:
            return self._check("cart_code", self._code_refusals, ip_address, owner_key)
        except RateLimitStoreUnavailable:
            logger.warning("Promotion-code limit skipped: the rate-limit store is unavailable")
        return RateLimitDecision(True)

    def record_code_refusal(self, ip_address: str | None, owner_key: str | None) -> None:
        try:
            for key in self._refusal_keys("cart_code", ip_address, owner_key):
                self._store.hit(key, self._code_refusal_window)
        except RateLimitStoreUnavailable:
            logger.warning(
                "Promotion-code refusal not counted: the rate-limit store is unavailable"
            )


def get_cart_rate_limiter() -> CartRateLimiter:
    """FastAPI dependency. Overridden in tests with an in-memory store."""
    settings = get_settings()
    store = RedisRateLimitStore(_redis_client(settings.redis_url.get_secret_value()))
    return CartRateLimiter(store, settings)
