"""GOOGLE_OAUTH_* settings (ADR-006 amendment 2026-11-11): all or nothing, and the redirect URI
must be an absolute URL, https:// outside development."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {
    "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/x",
    "audit_hmac_key": "k" * 32,
    "image_public_base_url": "https://img.example.rw/media",
}
GOOGLE = {
    "google_oauth_client_id": "id.apps.googleusercontent.com",
    "google_oauth_client_secret": "secret",
    "google_oauth_redirect_uri": "https://shop.example.rw/api/auth/google/callback",
}


def make(**values: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **values})  # type: ignore[arg-type,call-arg]


def test_google_sign_in_is_off_without_settings() -> None:
    assert make().google_oauth_enabled is False


def test_google_sign_in_is_on_with_all_three() -> None:
    on = make(**GOOGLE, app_env="production", payment_mock_webhook_secret=None)
    assert on.google_oauth_enabled is True


@pytest.mark.parametrize("missing", list(GOOGLE))
def test_a_partial_configuration_is_refused(missing: str) -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        make(**{k: v for k, v in GOOGLE.items() if k != missing})


def test_the_secret_never_appears_in_a_refusal() -> None:
    with pytest.raises(ValidationError) as exc:
        make(google_oauth_client_secret="super-secret-value")
    assert "super-secret-value" not in str(exc.value)


@pytest.mark.parametrize(
    "uri",
    [
        "/api/auth/google/callback",
        "ftp://shop.example.rw/cb",
        "https://shop.example.rw/cb?x=1",
        "https://shop.example.rw/cb#frag",
    ],
)
def test_the_redirect_uri_must_be_an_absolute_url(uri: str) -> None:
    with pytest.raises(ValidationError, match="GOOGLE_OAUTH_REDIRECT_URI"):
        make(**{**GOOGLE, "google_oauth_redirect_uri": uri})


def test_http_redirect_uris_are_allowed_only_in_development() -> None:
    local = {
        **GOOGLE,
        "google_oauth_redirect_uri": "http://localhost:3000/api/auth/google/callback",
    }
    assert make(**local, app_env="development").google_oauth_enabled
    with pytest.raises(ValidationError, match="https"):
        make(**local, app_env="staging")


def test_the_real_dependency_is_off_without_settings_and_on_with_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    from app.integrations.oauth import get_google_oauth_client

    for name in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
    ):
        # Empty, not deleted: a deleted variable would let backend/.env supply a real client.
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    try:
        assert get_google_oauth_client() is None  # the endpoints answer 503
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", " id.apps.googleusercontent.com ")
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-only-secret")
        monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:3000/api/auth/google/cb")
        get_settings.cache_clear()
        client = get_google_oauth_client()
        assert client is not None and client.client_id == "id.apps.googleusercontent.com"
        assert client.redirect_uri == "http://localhost:3000/api/auth/google/cb"
    finally:
        get_settings.cache_clear()
