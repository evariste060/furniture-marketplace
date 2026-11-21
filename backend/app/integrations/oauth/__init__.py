"""External sign-in providers (ADR-006 amendment 2026-11-11). Only Google exists."""

from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.integrations.oauth.google import GoogleKeyCache, GoogleOAuthClient


@lru_cache
def _shared_http() -> httpx.Client:
    # Certificates are verified (httpx default); redirects are not followed.
    return httpx.Client(follow_redirects=False)


@lru_cache
def _shared_keys() -> GoogleKeyCache:
    return GoogleKeyCache()


def get_google_oauth_client() -> GoogleOAuthClient | None:
    """FastAPI dependency: the Google client, or None while GOOGLE_OAUTH_* is not configured
    (the endpoints then answer 503 google_auth_unavailable). Overridden in tests."""
    settings = get_settings()
    if not settings.google_oauth_enabled:
        return None
    assert settings.google_oauth_client_id and settings.google_oauth_client_secret
    assert settings.google_oauth_redirect_uri
    return GoogleOAuthClient(
        client_id=settings.google_oauth_client_id.strip(),
        client_secret=settings.google_oauth_client_secret.get_secret_value().strip(),
        redirect_uri=settings.google_oauth_redirect_uri.strip(),
        http=_shared_http(),
        keys=_shared_keys(),
    )
