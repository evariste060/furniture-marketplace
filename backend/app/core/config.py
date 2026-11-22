import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only SMTP server the temporary production test route accepts (see Settings).
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        # A refused setting must not print the raw inputs: they include passwords and API keys.
        hide_input_in_errors=True,
    )
    app_name: str = "Rwanda Electronics E-Commerce API"
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Runtime role: least-privilege application account (no UPDATE/DELETE on audit_records).
    database_url: SecretStr
    # Migration/owner role used only by Alembic. Falls back to DATABASE_URL when unset.
    migration_database_url: SecretStr | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Shared store for login rate-limit counters (must be shared by all backend workers).
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    # Server secret for pseudonymising identifiers in audit records and rate-limit keys.
    audit_hmac_key: SecretStr = Field(min_length=32)

    # Approved login rate-limit policy (2026-10-21): fixed 15-minute window,
    # 5 failed attempts per identifier, 20 failed attempts per source IP.
    login_window_seconds: int = Field(default=900, ge=1)
    login_max_failures_per_identifier: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=20, ge=1)

    # Client IP (ADR-006, 2026-11-13). "peer": the transport peer (local development, direct
    # deployments). "signed": the address the storefront's server vouches for with an HMAC
    # (X-Sixty-Client-IP, -Signature, -Timestamp), verified with CLIENT_IP_SIGNING_SECRET or, during
    # a rotation, CLIENT_IP_SIGNING_SECRET_NEXT; anything unverifiable falls back to the peer.
    # Signatures older or newer than CLIENT_IP_SIGNATURE_MAX_AGE_SECONDS are refused.
    client_ip_source: Literal["peer", "signed"] = "peer"
    client_ip_signing_secret: SecretStr | None = None
    client_ip_signing_secret_next: SecretStr | None = None
    client_ip_signature_max_age_seconds: int = Field(default=60, ge=5, le=300)

    # Email verification of new customer accounts (ADR-006 amendment 2026-11-12). A link is valid
    # for EMAIL_VERIFICATION_TTL_HOURS; a new one can be requested once per cooldown, within the
    # resend limits per address and per IP. Failed verification attempts count per IP.
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=168)
    email_verification_resend_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    email_verification_resend_max_per_email: int = Field(default=5, ge=1)
    email_verification_resend_max_per_ip: int = Field(default=20, ge=1)
    email_verification_resend_window_seconds: int = Field(default=3600, ge=60)
    email_verification_max_failures_per_ip: int = Field(default=30, ge=1)
    email_verification_failure_window_seconds: int = Field(default=900, ge=60)

    # Cart abuse limits (module 11; docs/architecture/ADR-008-cart-security-controls.md). S1 was
    # approved by the project owner on 2026-10-24; the S3 values are retained under an approved
    # direction whose details are pending. They are settings, so a later decision can change them
    # without a code change.
    # S1: new guest carts per client network (IPv4 address, including IPv4-mapped IPv6, or IPv6
    # /64) per window.
    cart_guest_creations_per_ip: int = Field(default=10, ge=1)
    cart_guest_creation_window_seconds: int = Field(default=3600, ge=1)
    # S3: refused stock requests (409 insufficient_stock) per client network and per cart owner
    # per window; beyond it, adding units or raising a quantity answers 429.
    cart_stock_refusals_per_window: int = Field(default=20, ge=1)
    cart_stock_refusal_window_seconds: int = Field(default=900, ge=1)
    # S5 (module 13; ADR-008, approved by the project owner on 2026-10-25): refused promotion
    # codes (422 promotion_unavailable or promotion_not_applicable) per client network and per
    # cart owner per window; beyond it, POST /cart/apply-code answers 429.
    cart_code_refusals_per_window: int = Field(default=20, ge=1)
    cart_code_refusal_window_seconds: int = Field(default=900, ge=1)
    # Guest order lookup (module 14, D-O3; ADR-008 S6, approved by the project owner on
    # 2026-10-25): failed lookups per order number and per IP in a fixed window; beyond it
    # POST /orders/lookup answers 429. Separate from the login values, which may change alone.
    order_lookup_max_failures_per_order: int = Field(default=5, ge=1)
    order_lookup_max_failures_per_ip: int = Field(default=20, ge=1)
    order_lookup_window_seconds: int = Field(default=900, ge=1)
    # Review submissions (module 20, SC-01, 2026-10-27): every POST /reviews/{token} counts, per
    # link and per client network in a fixed window; beyond it the request answers 429.
    review_submit_max_per_token: int = Field(default=5, ge=1)
    review_submit_max_per_ip: int = Field(default=20, ge=1)
    review_submit_window_seconds: int = Field(default=3600, ge=1)
    # Business quote requests (module 19, 2026-10-29): every POST /quote-requests counts, per
    # phone number (its keyed pseudonym) and per client network in a fixed window; beyond it the
    # request answers 429.
    quote_request_max_per_phone: int = Field(default=3, ge=1)
    quote_request_max_per_ip: int = Field(default=10, ge=1)
    quote_request_window_seconds: int = Field(default=3600, ge=1)
    # Service requests (ADR-013, 2026-11-17): every POST /services/{slug}/requests counts,
    # per phone number (keyed pseudonym) and per client network, as quote requests.
    service_request_max_per_phone: int = Field(default=3, ge=1)
    service_request_max_per_ip: int = Field(default=10, ge=1)
    service_request_window_seconds: int = Field(default=3600, ge=1)
    # Support messages (2026-11-11): every new message and every customer reply counts, per
    # sender (keyed pseudonym of the phone, email or account) and per client network.
    support_message_max_per_sender: int = Field(default=5, ge=1)
    support_message_max_per_ip: int = Field(default=15, ge=1)
    support_message_window_seconds: int = Field(default=3600, ge=1)

    # Payments (module 15; §7 Q21): until ADR-003 chooses real providers and sandbox credentials
    # exist, mobile money goes through the `mock` provider, whose webhooks are HMAC-SHA256 signed
    # with this secret. Unset: mobile-money initiation and mock webhooks answer 503. The mock is
    # refused in production (it moves no money). Webhooks older than the tolerance are refused.
    payment_mock_webhook_secret: SecretStr | None = None
    payment_webhook_tolerance_seconds: int = Field(default=300, ge=30, le=3600)

    # "Continue with Google" (OAuth 2.0 / OpenID Connect, Authorization Code flow with PKCE;
    # ADR-006 amendment 2026-11-11). Off unless all three are set: the client ID and secret of a
    # Google Cloud "Web application" OAuth client, and the redirect URI registered on it (the
    # storefront's callback route, which forwards Google's answer to POST /auth/google/callback).
    # The redirect URI must be https:// outside development. A sign-in must finish within
    # GOOGLE_OAUTH_FLOW_TTL_SECONDS of its start. GOOGLE_AUTH_MAX_PER_NETWORK limits starts and
    # failed callbacks per client network within GOOGLE_AUTH_WINDOW_SECONDS.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_oauth_flow_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    google_auth_max_per_network: int = Field(default=30, ge=1)
    google_auth_window_seconds: int = Field(default=900, ge=1)

    # Message delivery (module 2 password-reset codes, module 17 order notifications). No real
    # SMS or email provider exists until ADR-005 is decided (§7 Q22).
    # - "none": order notifications are off (nothing recorded or sent); reset endpoints answer 503.
    # - "console": messages are printed to the process's terminal; development only.
    # - "mock": order notifications are recorded and "sent" to a stand-in that delivers nothing;
    #   password reset still answers 503 (a code must reach the person). Refused in production.
    # - "smtp": real email through the SMTP_* settings (Gmail-compatible), for development and
    #   staging tests. Email only: no SMS. Refused in production until ADR-005 is decided,
    #   except the temporary Gmail test route (TEMPORARY_GMAIL_SMTP_ENABLED below).
    # The marketplace's name (ADR-014 decision 16): the API's name and the emails' brand. FurniHub
    # is provisional; a rename is this setting (MARKETPLACE_NAME) and the frontend's
    # NEXT_PUBLIC_MARKETPLACE_NAME, never a code change.
    marketplace_name: str = Field(default="FurniHub", min_length=1, max_length=60)
    notification_provider: Literal["none", "console", "mock", "smtp"] = "none"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_use_tls: bool = True  # STARTTLS with a verified certificate, never a plain-text fallback
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str | None = None
    # The sender name inboxes show beside SMTP_FROM_EMAIL, e.g. "FurniHub". Unset:
    # the bare address.
    smtp_from_name: str | None = None
    smtp_timeout_seconds: float = Field(default=10, gt=0, le=60)  # each network operation
    # Temporary (owner approval 2026-11-01): lets the Render test deployment, which runs with
    # APP_ENV=production, send through Gmail until Resend replaces it. Off by default; it changes
    # nothing else, and only with NOTIFICATION_PROVIDER=smtp. Remove it with the Gmail route.
    temporary_gmail_smtp_enabled: bool = False
    # Transactional email (docs/deployment/email.md).
    # EMAIL_ALLOWED_RECIPIENTS: comma-separated addresses; when set, email goes to these only and
    # every other recipient is recorded as refused ("recipient_not_allowed") without a provider
    # call. Required with NOTIFICATION_PROVIDER=smtp in development, so real Gmail tests reach
    # approved test inboxes only. Empty elsewhere: everyone.
    email_allowed_recipients: str = ""
    # STAFF_ORDER_ALERT_EMAILS: comma-separated staff addresses told about every new order.
    # Empty: no staff alerts.
    staff_order_alert_emails: str = ""
    # SITE_URL: the storefront's public origin, for the links in emails. Unset: emails carry no
    # links (never a localhost link in production).
    site_url: str | None = None

    # Images (module 7; ADR-009). STORAGE_BACKEND selects the storage behind
    # app.integrations.media; "local" (the only backend) writes under MEDIA_ROOT: exact originals in
    # private/ (never served) and sanitised public sources in public/. Public URLs are
    # IMAGE_PUBLIC_BASE_URL + key (MEDIA_BASE_URL, the module 7 name, is still accepted). In
    # development the API itself serves MEDIA_ROOT/public at /media; elsewhere a web server or CDN
    # must serve it (docs/deployment/media.md; hosting is still open, ADR-004), and the URL must
    # be a public https:// URL.
    storage_backend: Literal["local", "r2"] = "local"
    media_root: Path = Path(__file__).resolve().parents[2] / "media"
    # STORAGE_BACKEND=r2: Cloudflare R2 through its S3 API, two buckets (ADR-009): the public one
    # holds the sanitised sources and is served at IMAGE_PUBLIC_BASE_URL (an r2.dev URL or a
    # custom domain); the private one holds the exact originals and incoming bulk uploads and is
    # never made public. R2_ENDPOINT_URL overrides https://<account id>.r2.cloudflarestorage.com
    # (an EU-jurisdiction bucket, or tests). MEDIA_ROOT is unused with R2.
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_public_bucket: str | None = None
    r2_private_bucket: str | None = None
    r2_endpoint_url: str | None = None
    image_public_base_url: str = Field(
        default="http://localhost:8000/media",
        validation_alias=AliasChoices("image_public_base_url", "media_base_url"),
    )
    # Uploads decoded and re-encoded with Pillow at the same time, per API process; the rest wait.
    image_processing_concurrency: int = Field(default=2, ge=1, le=16)
    # Job items (bulk image upload) the worker process (python -m app.worker) runs at once.
    job_worker_concurrency: int = Field(default=2, ge=1, le=16)

    @field_validator("media_root")
    @classmethod
    def _media_root_relative_to_backend(cls, value: Path) -> Path:
        """A relative MEDIA_ROOT means backend/<value>, wherever the process was started."""
        return value if value.is_absolute() else Path(__file__).resolve().parents[2] / value

    @model_validator(mode="after")
    def _client_ip_settings_valid(self) -> "Settings":
        """CLIENT_IP_SOURCE=signed needs a current secret and may have a next one (rotation),
        each of at least 32 characters and different; secrets without it are a mistake. Refused
        in every environment, so a misconfigured deployment never starts (ADR-006)."""
        secrets = self.client_ip_signing_secrets
        if self.client_ip_source != "signed":
            if secrets:
                raise ValueError(
                    "CLIENT_IP_SIGNING_SECRET(_NEXT) are set but CLIENT_IP_SOURCE is not 'signed'"
                )
            return self
        current = self.client_ip_signing_secret
        if current is None or not current.get_secret_value():
            raise ValueError("CLIENT_IP_SOURCE=signed requires CLIENT_IP_SIGNING_SECRET")
        if any(len(s) < 32 or s != s.strip() for s in secrets):
            raise ValueError(
                "CLIENT_IP_SIGNING_SECRET and CLIENT_IP_SIGNING_SECRET_NEXT must be at least 32 "
                "characters, without surrounding spaces"
            )
        if len(set(secrets)) != len(secrets):
            raise ValueError("CLIENT_IP_SIGNING_SECRET_NEXT must differ from the current secret")
        return self

    def _client_ip_secret_values(self) -> list[SecretStr | None]:
        return [self.client_ip_signing_secret, self.client_ip_signing_secret_next]

    @property
    def client_ip_signing_secrets(self) -> list[str]:
        """The secrets a client-IP signature may be made with: current, then next. An empty
        value counts as unset."""
        values = (s.get_secret_value() for s in self._client_ip_secret_values() if s is not None)
        return [value for value in values if value]

    @model_validator(mode="after")
    def _no_wildcard_cors_origin(self) -> "Settings":
        """CORS allows credentials, so every origin must be listed explicitly; '*' is refused."""
        if any(origin == "*" or "*" in origin for origin in self.allowed_origins):
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return self

    @model_validator(mode="after")
    def _mock_payments_never_in_production(self) -> "Settings":
        secret = self.payment_mock_webhook_secret
        if secret is None or not secret.get_secret_value():
            return self
        if self.app_env == "production":
            raise ValueError(
                "PAYMENT_MOCK_WEBHOOK_SECRET must not be set when APP_ENV=production: the mock "
                "payment provider moves no money"
            )
        if len(secret.get_secret_value()) < 32:
            raise ValueError("PAYMENT_MOCK_WEBHOOK_SECRET must be at least 32 characters")
        return self

    @model_validator(mode="after")
    def _console_provider_only_in_development(self) -> "Settings":
        if self.notification_provider == "console" and self.app_env != "development":
            raise ValueError(
                "NOTIFICATION_PROVIDER=console is allowed only when APP_ENV=development"
            )
        if self.notification_provider == "mock" and self.app_env == "production":
            raise ValueError(
                "NOTIFICATION_PROVIDER=mock must not be used when APP_ENV=production: the mock "
                "notification provider delivers nothing"
            )
        return self

    @model_validator(mode="after")
    def _smtp_settings_complete(self) -> "Settings":
        if self.notification_provider != "smtp":
            return self
        if self.app_env == "production" and not self.temporary_gmail_smtp_enabled:
            raise ValueError(
                "NOTIFICATION_PROVIDER=smtp must not be used when APP_ENV=production: the "
                "provider decision (ADR-005) is still open"
            )
        if not self.smtp_host:
            raise ValueError("SMTP_HOST is required when NOTIFICATION_PROVIDER=smtp")
        sender = self.smtp_from_email or ""
        if sender.count("@") != 1 or any(c.isspace() for c in sender):
            raise ValueError("SMTP_FROM_EMAIL must be an email address")
        name = self.smtp_from_name or ""
        if len(name) > 64 or any(not c.isprintable() for c in name):
            raise ValueError("SMTP_FROM_NAME must be one line of at most 64 characters")
        password = self.smtp_password.get_secret_value() if self.smtp_password else ""
        if bool(self.smtp_username) != bool(password):
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
        if password and not self.smtp_use_tls:
            raise ValueError("SMTP_USE_TLS must be true when SMTP credentials are set")
        if self.app_env == "production":  # only the temporary Gmail route gets this far
            if self.smtp_host != GMAIL_SMTP_HOST:
                raise ValueError(
                    f"TEMPORARY_GMAIL_SMTP_ENABLED requires SMTP_HOST={GMAIL_SMTP_HOST}"
                )
            if self.smtp_port != GMAIL_SMTP_PORT:
                raise ValueError(
                    f"TEMPORARY_GMAIL_SMTP_ENABLED requires SMTP_PORT={GMAIL_SMTP_PORT}"
                )
            if not self.smtp_use_tls:
                raise ValueError("TEMPORARY_GMAIL_SMTP_ENABLED requires SMTP_USE_TLS=true")
            if not password:
                raise ValueError(
                    "TEMPORARY_GMAIL_SMTP_ENABLED requires SMTP_USERNAME and SMTP_PASSWORD"
                )
        return self

    @model_validator(mode="after")
    def _google_oauth_settings_valid(self) -> "Settings":
        secret = (
            self.google_oauth_client_secret.get_secret_value().strip()
            if self.google_oauth_client_secret
            else ""
        )
        values = (
            (self.google_oauth_client_id or "").strip(),
            secret,
            (self.google_oauth_redirect_uri or "").strip(),
        )
        if not any(values):
            return self
        if not all(values):
            raise ValueError(
                "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI "
                "must be set together"
            )
        url = urlsplit(values[2])
        host = (url.hostname or "").lower()
        if url.scheme not in ("http", "https") or not host or url.fragment or url.query:
            raise ValueError(
                "GOOGLE_OAUTH_REDIRECT_URI must be an absolute URL without a query or fragment"
            )
        if self.app_env != "development" and url.scheme != "https":
            raise ValueError(
                "GOOGLE_OAUTH_REDIRECT_URI must use https:// when APP_ENV is not development"
            )
        return self

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret
            and self.google_oauth_client_secret.get_secret_value().strip()
            and self.google_oauth_redirect_uri
        )

    @model_validator(mode="after")
    def _r2_settings_complete(self) -> "Settings":
        if self.storage_backend != "r2":
            return self
        secret = self.r2_secret_access_key.get_secret_value() if self.r2_secret_access_key else ""
        if not (self.r2_account_id or self.r2_endpoint_url):
            raise ValueError("R2_ACCOUNT_ID is required when STORAGE_BACKEND=r2")
        if not (self.r2_access_key_id and secret):
            raise ValueError(
                "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are required when STORAGE_BACKEND=r2"
            )
        if not (self.r2_public_bucket and self.r2_private_bucket):
            raise ValueError(
                "R2_PUBLIC_BUCKET and R2_PRIVATE_BUCKET are required when STORAGE_BACKEND=r2"
            )
        if self.r2_public_bucket == self.r2_private_bucket:
            # The public bucket is readable by anyone: originals must never land in it.
            raise ValueError("R2_PRIVATE_BUCKET must be a different bucket from R2_PUBLIC_BUCKET")
        return self

    @model_validator(mode="after")
    def _public_media_url_outside_development(self) -> "Settings":
        """Outside development every image URL is published to customers, so
        IMAGE_PUBLIC_BASE_URL must be a public HTTPS URL; the loopback default would hand out
        broken links."""
        if self.app_env == "development":
            return self
        url = urlsplit(self.image_public_base_url)
        host = (url.hostname or "").lower()
        if (
            url.scheme != "https"
            or not host
            or host == "localhost"
            or host.endswith(".localhost")
            or _is_loopback(host)
        ):
            raise ValueError(
                "IMAGE_PUBLIC_BASE_URL must be a public https:// URL when APP_ENV is not "
                "development"
            )
        return self

    @model_validator(mode="after")
    def _email_settings_valid(self) -> "Settings":
        for name, addresses in (
            ("EMAIL_ALLOWED_RECIPIENTS", self.allowed_email_recipients),
            ("STAFF_ORDER_ALERT_EMAILS", self.staff_order_alert_recipients),
        ):
            for address in addresses:
                if (
                    address.count("@") != 1
                    or any(c.isspace() for c in address)
                    or len(address) > 320
                ):
                    raise ValueError(f"{name} must list email addresses separated by commas")
        if (
            self.notification_provider == "smtp"
            and self.app_env == "development"
            and not self.allowed_email_recipients
        ):
            raise ValueError(
                "EMAIL_ALLOWED_RECIPIENTS is required with NOTIFICATION_PROVIDER=smtp in "
                "development: list the test inboxes real email may reach"
            )
        if self.site_url:
            url = urlsplit(self.site_url)
            if url.scheme not in ("http", "https") or not url.hostname or url.path not in ("", "/"):
                raise ValueError("SITE_URL must be an origin such as https://shop.example.rw")
            if self.app_env != "development" and url.scheme != "https":
                raise ValueError("SITE_URL must use https:// when APP_ENV is not development")
        return self

    @staticmethod
    def _address_list(value: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip())
        )

    @property
    def allowed_email_recipients(self) -> tuple[str, ...]:
        return self._address_list(self.email_allowed_recipients)

    @property
    def staff_order_alert_recipients(self) -> tuple[str, ...]:
        return self._address_list(self.staff_order_alert_emails)

    @property
    def public_site_url(self) -> str | None:
        return self.site_url.rstrip("/") if self.site_url else None

    @property
    def temporary_gmail_smtp_active(self) -> bool:
        return (
            self.app_env == "production"
            and self.notification_provider == "smtp"
            and self.temporary_gmail_smtp_enabled
        )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def alembic_database_url(self) -> str:
        # An empty MIGRATION_DATABASE_URL counts as unset (tests rely on this to keep Alembic
        # on the DATABASE_URL they set, never on a value read from .env).
        migration = self.migration_database_url
        if migration is not None and migration.get_secret_value().strip():
            return migration.get_secret_value()
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings resolves required values from environment and .env sources.
    return Settings()  # type: ignore[call-arg]
