"""Google as an OpenID Connect provider (ADR-006 amendment 2026-11-11): the Authorization Code
flow with PKCE (S256), for "Continue with Google".

This module only talks to Google: it builds the authorization URL, exchanges an authorization
code for tokens at Google's token endpoint, and verifies the ID token (RS256 signature against
Google's published keys, issuer, audience, authorized party, expiry, issued-at and nonce). What a
verified identity may do in the shop is decided by app.services.google_auth_service.

Security rules kept here:
- Every call to Google has a timeout; network errors, timeouts, 5xx answers and a refused client
  configuration raise GoogleUnavailable (the API answers 503).
- A refused authorization code (`invalid_grant`) raises GoogleCodeRejected.
- An ID token that fails any check raises GoogleTokenInvalid with a short reason for the audit
  log. Exceptions, logs and audit details never contain tokens, codes, the client secret or the
  response bodies of Google's endpoints.
- Only the RS256 algorithm is accepted (no `none`, no HMAC with a public key).
- Google's signing keys are cached for the max-age Google sends (at most a day). An unknown key
  ID triggers one refresh, at most once a minute (counting failed attempts), so forged key IDs
  cannot make us hammer Google; after a failed fetch of expired keys, requests are refused with
  GoogleUnavailable for 10 seconds instead of each retrying.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

logger = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = "openid email profile"

HTTP_TIMEOUT_SECONDS = 10.0
CLOCK_SKEW_SECONDS = 60
JWKS_DEFAULT_MAX_AGE = 3600
JWKS_MAX_AGE_CAP = 86400
JWKS_MIN_REFRESH_INTERVAL = 60
JWKS_FAILURE_BACKOFF = 10
SUBJECT_MAX_LENGTH = 255


class GoogleUnavailable(Exception):
    """Google could not be reached, failed, or refused our client configuration."""


class GoogleCodeRejected(Exception):
    """Google refused the authorization code (invalid, expired, already used, or not ours)."""


class GoogleTokenInvalid(Exception):
    """The ID token failed verification. `reason` is safe to log and audit."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str | None
    email_verified: bool
    name: str | None


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge for a PKCE code verifier (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


_MAX_AGE = re.compile(r"max-age=(\d+)")


class GoogleKeyCache:
    """Google's ID-token signing keys (JWKS), shared by every request in the process."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires_at = 0.0
        # Successful or not: limits how often an unknown key ID can make us call Google.
        self._attempted_at: float | None = None
        # After a failed fetch of an expired key set, refuse at once until then (no retry storm
        # while Google is down; every request still gets 503).
        self._retry_at = 0.0

    def key_for(self, kid: str, http: httpx.Client) -> jwt.PyJWK | None:
        with self._lock:
            now = self._clock()
            if now >= self._expires_at:
                if now < self._retry_at:
                    raise GoogleUnavailable("jwks_backoff")
                self._refresh(http, now)
            elif kid not in self._keys and (
                self._attempted_at is None or now - self._attempted_at >= JWKS_MIN_REFRESH_INTERVAL
            ):
                self._refresh(http, now)  # Google may have rotated its keys
            return self._keys.get(kid)

    def _refresh(self, http: httpx.Client, now: float) -> None:
        self._attempted_at = now
        try:
            self._fetch(http, now)
        except GoogleUnavailable:
            self._retry_at = now + JWKS_FAILURE_BACKOFF
            raise

    def _fetch(self, http: httpx.Client, now: float) -> None:
        try:
            response = http.get(JWKS_URI, timeout=HTTP_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise GoogleUnavailable("jwks_unreachable") from exc
        if response.status_code != 200:
            raise GoogleUnavailable(f"jwks_status_{response.status_code}")
        try:
            keyset = jwt.PyJWKSet.from_dict(response.json())
        except (ValueError, jwt.PyJWTError) as exc:
            raise GoogleUnavailable("jwks_malformed") from exc
        keys = {key.key_id: key for key in keyset.keys if key.key_id}
        if not keys:
            raise GoogleUnavailable("jwks_empty")
        match = _MAX_AGE.search(response.headers.get("cache-control", ""))
        max_age = int(match.group(1)) if match else JWKS_DEFAULT_MAX_AGE
        self._keys = keys
        self._expires_at = now + min(max_age, JWKS_MAX_AGE_CAP)


class GoogleOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.Client,
        keys: GoogleKeyCache,
    ) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http
        self._keys = keys

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        query = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
            "include_granted_scopes": "false",
        }
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(query)}"

    def exchange_code(self, *, code: str, code_verifier: str) -> str:
        """Exchange the authorization code at Google's token endpoint; return the ID token.

        The access token is never used or kept: this feature only needs the user's identity.
        """
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }
        try:
            response = self._http.post(
                TOKEN_ENDPOINT,
                data=form,
                headers={"Accept": "application/json"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GoogleUnavailable("token_endpoint_unreachable") from exc
        body = _json_object(response)
        if response.status_code in (400, 401):
            raw_error = body.get("error")
            error = raw_error if isinstance(raw_error, str) else "unknown"
            if error == "invalid_grant":
                raise GoogleCodeRejected()
            # invalid_client, unauthorized_client, redirect_uri_mismatch...: our configuration.
            logger.error("google_token_exchange_refused error=%s", _safe_code(error))
            raise GoogleUnavailable(f"token_endpoint_refused_{_safe_code(error)}")
        if response.status_code != 200:
            raise GoogleUnavailable(f"token_endpoint_status_{response.status_code}")
        id_token = body.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise GoogleUnavailable("token_endpoint_no_id_token")
        return id_token

    def verify_id_token(self, id_token: str, *, nonce_hash: str) -> GoogleIdentity:
        """Verify the ID token; `nonce_hash` is the SHA-256 hex digest of the nonce sent in the
        authorization request (only the digest is stored)."""
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise GoogleTokenInvalid("malformed") from None
        if header.get("alg") != "RS256":
            raise GoogleTokenInvalid("algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise GoogleTokenInvalid("key_id")
        key = self._keys.key_for(kid, self._http)
        if key is None:
            raise GoogleTokenInvalid("unknown_key")
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=ISSUERS,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise GoogleTokenInvalid("expired") from None
        except jwt.InvalidAudienceError:
            raise GoogleTokenInvalid("audience") from None
        except jwt.InvalidIssuerError:
            raise GoogleTokenInvalid("issuer") from None
        except jwt.InvalidSignatureError:
            raise GoogleTokenInvalid("signature") from None
        except jwt.ImmatureSignatureError:
            raise GoogleTokenInvalid("not_yet_valid") from None
        except jwt.MissingRequiredClaimError:
            raise GoogleTokenInvalid("missing_claim") from None
        except jwt.PyJWTError:
            raise GoogleTokenInvalid("invalid") from None

        # The authorized party, when present, must be this client; with several audiences it must
        # be present (OIDC Core 3.1.3.7), so a token issued to another client is never accepted.
        azp = claims.get("azp")
        audiences = claims.get("aud")
        several = isinstance(audiences, list) and len(audiences) > 1
        if (azp is not None and azp != self.client_id) or (several and azp is None):
            raise GoogleTokenInvalid("authorized_party")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not hmac.compare_digest(
            hashlib.sha256(token_nonce.encode("utf-8")).hexdigest(), nonce_hash
        ):
            raise GoogleTokenInvalid("nonce")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > SUBJECT_MAX_LENGTH:
            raise GoogleTokenInvalid("subject")

        email = claims.get("email")
        verified = claims.get("email_verified")
        name = claims.get("name")
        return GoogleIdentity(
            subject=subject,
            email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
            email_verified=verified is True or verified == "true",
            name=name.strip() if isinstance(name, str) and name.strip() else None,
        )


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _safe_code(value: str) -> str:
    """An OAuth error code as a short token fit for logs (never free text from the response)."""
    return re.sub(r"[^a-z_]", "", value.lower())[:40] or "unknown"
