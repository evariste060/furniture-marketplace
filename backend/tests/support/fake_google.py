"""A stand-in for Google's OAuth endpoints, served through httpx.MockTransport.

It signs real RS256 ID tokens with a key generated per test, publishes the matching JWKS, and
records the token requests it receives, so tests exercise the real verification code without
network access or Google credentials.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.integrations.oauth.google import (
    JWKS_URI,
    TOKEN_ENDPOINT,
    GoogleKeyCache,
    GoogleOAuthClient,
)

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-only-google-client-secret"
REDIRECT_URI = "http://localhost:3000/api/auth/google/callback"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**data, "kid": kid, "alg": "RS256", "use": "sig"}


@dataclass
class FakeGoogle:
    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = "test-key-1"
    # The next token response: replaced by tests to simulate failures.
    token_response: Callable[[dict[str, list[str]]], httpx.Response] | None = None
    jwks_response: Callable[[], httpx.Response] | None = None
    # Claims for the next ID token; `nonce` is filled from the authorization URL when unset.
    claims: dict[str, Any] = field(default_factory=dict)
    token_requests: list[dict[str, list[str]]] = field(default_factory=list)
    jwks_requests: int = 0
    # code -> nonce, registered by `authorize`
    codes: dict[str, str] = field(default_factory=dict)

    # ---- what Google would do at the consent screen ----------------------------------------
    def authorize(self, authorization_url: str, code: str = "good-code") -> dict[str, str]:
        """The user agrees: returns the query Google sends to the redirect URI."""
        query = {k: v[0] for k, v in parse_qs(authorization_url.split("?", 1)[1]).items()}
        self.codes[code] = query["nonce"]
        return {"state": query["state"], "code": code}

    def id_token(self, nonce: str | None = None, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "sub": "1100000000000000001",
            "email": "shopper@gmail.com",
            "email_verified": True,
            "name": "Shopper Example",
            "iat": now,
            "exp": now + 3600,
        }
        if nonce is not None:
            claims["nonce"] = nonce
        claims.update(self.claims)
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    # ---- the HTTP side ---------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == TOKEN_ENDPOINT and request.method == "POST":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            if self.token_response is not None:
                return self.token_response(form)
            code = form.get("code", [""])[0]
            if code not in self.codes:
                return httpx.Response(400, json={"error": "invalid_grant"})
            nonce = self.codes.pop(code)  # a code works once
            return httpx.Response(
                200,
                json={
                    "access_token": "ya29.test-access-token",
                    "expires_in": 3599,
                    "token_type": "Bearer",
                    "id_token": self.id_token(nonce=nonce),
                },
            )
        if url == JWKS_URI and request.method == "GET":
            self.jwks_requests += 1
            if self.jwks_response is not None:
                return self.jwks_response()
            return httpx.Response(
                200,
                json={"keys": [jwk_for(self.key, self.kid)]},
                headers={"cache-control": "public, max-age=3600"},
            )
        return httpx.Response(404)

    def client(self, keys: GoogleKeyCache | None = None) -> GoogleOAuthClient:
        return GoogleOAuthClient(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            http=httpx.Client(transport=httpx.MockTransport(self.handler)),
            keys=keys or GoogleKeyCache(),
        )
