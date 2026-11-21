"""The Google OpenID Connect client (ADR-006 amendment 2026-11-11): ID token verification, the
code exchange and Google's key set, against a fake Google (tests/support/fake_google.py)."""

import hashlib
import time
from urllib.parse import parse_qs

import httpx
import jwt
import pytest

from app.integrations.oauth.google import (
    GoogleCodeRejected,
    GoogleKeyCache,
    GoogleTokenInvalid,
    GoogleUnavailable,
    pkce_challenge,
)
from tests.support.fake_google import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, FakeGoogle, new_key

NONCE = "nonce-value-0123456789"
NONCE_HASH = hashlib.sha256(NONCE.encode()).hexdigest()


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


def reason(google: FakeGoogle, token: str) -> str:
    with pytest.raises(GoogleTokenInvalid) as exc:
        google.client().verify_id_token(token, nonce_hash=NONCE_HASH)
    return exc.value.reason


# ---- authorization URL and PKCE ----------------------------------------------------------------
def test_authorization_url_carries_state_nonce_and_an_s256_challenge(google: FakeGoogle) -> None:
    verifier = "v" * 86
    url = google.client().authorization_url(state="s1", nonce="n1", code_verifier=verifier)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = {k: v[0] for k, v in parse_qs(url.split("?", 1)[1]).items()}
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["state"] == "s1" and query["nonce"] == "n1"
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == pkce_challenge(verifier)
    assert verifier not in url and CLIENT_SECRET not in url


def test_pkce_challenge_matches_rfc_7636_example() -> None:
    # RFC 7636 appendix B
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


# ---- ID token verification ---------------------------------------------------------------------
def test_a_valid_token_gives_the_identity(google: FakeGoogle) -> None:
    identity = google.client().verify_id_token(
        google.id_token(nonce=NONCE, email="Shopper@Gmail.com"), nonce_hash=NONCE_HASH
    )
    assert identity.subject == "1100000000000000001"
    assert identity.email == "shopper@gmail.com"
    assert identity.email_verified is True
    assert identity.name == "Shopper Example"


def test_the_issuer_without_scheme_is_accepted(google: FakeGoogle) -> None:
    token = google.id_token(nonce=NONCE, iss="accounts.google.com")
    assert google.client().verify_id_token(token, nonce_hash=NONCE_HASH).subject


@pytest.mark.parametrize(
    ("verified", "expected"), [(True, True), ("true", True), (False, False), ("false", False)]
)
def test_email_verified_is_read_strictly(google: FakeGoogle, verified: object, expected: bool):
    token = google.id_token(nonce=NONCE, email_verified=verified)
    assert google.client().verify_id_token(token, nonce_hash=NONCE_HASH).email_verified is expected


def test_a_token_signed_by_another_key_is_refused(google: FakeGoogle) -> None:
    forged = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "nonce": NONCE,
        },
        new_key(),
        algorithm="RS256",
        headers={"kid": google.kid},
    )
    assert reason(google, forged) == "signature"


def test_a_tampered_payload_is_refused(google: FakeGoogle) -> None:
    header, payload, signature = google.id_token(nonce=NONCE).split(".")
    other = google.id_token(nonce=NONCE, sub="999").split(".")[1]
    assert reason(google, f"{header}.{other}.{signature}") == "signature"
    assert payload != other


def test_wrong_issuer_audience_and_authorized_party_are_refused(google: FakeGoogle) -> None:
    assert reason(google, google.id_token(nonce=NONCE, iss="https://evil.example")) == "issuer"
    assert reason(google, google.id_token(nonce=NONCE, aud="other-client")) == "audience"
    token = google.id_token(nonce=NONCE, aud=[CLIENT_ID, "other"], azp="other")
    assert reason(google, token) == "authorized_party"


def test_expired_and_future_tokens_are_refused(google: FakeGoogle) -> None:
    now = int(time.time())
    assert reason(google, google.id_token(nonce=NONCE, iat=now - 7200, exp=now - 120)) == "expired"
    future = google.id_token(nonce=NONCE, iat=now + 600, exp=now + 4000)
    assert reason(google, future) == "not_yet_valid"


def test_a_token_within_the_clock_skew_is_accepted(google: FakeGoogle) -> None:
    now = int(time.time())
    token = google.id_token(nonce=NONCE, iat=now - 3600, exp=now - 30)
    assert google.client().verify_id_token(token, nonce_hash=NONCE_HASH).subject


def test_nonce_mismatch_and_missing_nonce_are_refused(google: FakeGoogle) -> None:
    assert reason(google, google.id_token(nonce="another-nonce")) == "nonce"
    assert reason(google, google.id_token()) == "nonce"


def test_missing_subject_is_refused(google: FakeGoogle) -> None:
    assert reason(google, google.id_token(nonce=NONCE, sub=None)) == "missing_claim"


def test_unsigned_and_hmac_tokens_are_refused(google: FakeGoogle) -> None:
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1", "nonce": NONCE}
    unsigned = jwt.encode(claims, "", algorithm="none", headers={"kid": google.kid})
    assert reason(google, unsigned) == "algorithm"
    hmac_token = jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": google.kid})
    assert reason(google, hmac_token) == "algorithm"


def test_garbage_and_unknown_key_ids_are_refused(google: FakeGoogle) -> None:
    assert reason(google, "not-a-jwt") == "malformed"
    google.kid = "rotated-away"
    token = google.id_token(nonce=NONCE)
    google.kid = "test-key-1"
    assert reason(google, token) == "unknown_key"


# ---- Google's key set --------------------------------------------------------------------------
def test_keys_are_cached_and_refreshed_for_a_new_key_id_at_most_once_a_minute() -> None:
    google = FakeGoogle()
    now = [1000.0]
    keys = GoogleKeyCache(clock=lambda: now[0])
    client = google.client(keys)
    client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)
    client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)
    assert google.jwks_requests == 1

    # Google rotates its key: an unknown key ID triggers one refresh...
    google.key, google.kid = new_key(), "test-key-2"
    now[0] += 61
    client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)
    assert google.jwks_requests == 2

    # ...but forged key IDs cannot make us call Google again within a minute.
    for _ in range(5):
        with pytest.raises(GoogleTokenInvalid):
            forged = jwt.encode({"sub": "1"}, new_key(), algorithm="RS256", headers={"kid": "x"})
            client.verify_id_token(forged, nonce_hash=NONCE_HASH)
    assert google.jwks_requests == 2

    # The cache expires with Google's max-age.
    now[0] += 3601
    client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)
    assert google.jwks_requests == 3


@pytest.mark.parametrize(
    "response",
    [
        lambda: httpx.Response(503),
        lambda: httpx.Response(200, text="<html>"),
        lambda: httpx.Response(200, json={"keys": []}),
    ],
)
def test_a_failing_key_endpoint_is_an_outage(response) -> None:
    google = FakeGoogle()
    google.jwks_response = response
    with pytest.raises(GoogleUnavailable):
        google.client().verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)


# ---- code exchange -----------------------------------------------------------------------------
def test_the_exchange_sends_the_verifier_and_secret_and_returns_the_id_token(
    google: FakeGoogle,
) -> None:
    url = google.client().authorization_url(state="s", nonce=NONCE, code_verifier="v" * 64)
    callback = google.authorize(url)
    id_token = google.client().exchange_code(code=callback["code"], code_verifier="v" * 64)
    assert google.client().verify_id_token(id_token, nonce_hash=NONCE_HASH).subject
    form = google.token_requests[-1]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code_verifier"] == ["v" * 64]
    assert form["redirect_uri"] == [REDIRECT_URI]
    assert form["client_id"] == [CLIENT_ID] and form["client_secret"] == [CLIENT_SECRET]


def test_a_refused_code_is_reported_as_such(google: FakeGoogle) -> None:
    with pytest.raises(GoogleCodeRejected):
        google.client().exchange_code(code="unknown", code_verifier="v" * 64)


@pytest.mark.parametrize(
    "response",
    [
        lambda form: httpx.Response(500),
        lambda form: httpx.Response(502, text="Bad Gateway"),
        lambda form: httpx.Response(401, json={"error": "invalid_client"}),
        lambda form: httpx.Response(400, json={"error": "redirect_uri_mismatch"}),
        lambda form: httpx.Response(200, json={"access_token": "x"}),
        lambda form: httpx.Response(200, text="not json"),
    ],
)
def test_google_failures_and_bad_configuration_are_outages(google: FakeGoogle, response) -> None:
    google.token_response = response
    with pytest.raises(GoogleUnavailable):
        google.client().exchange_code(code="c", code_verifier="v" * 64)


def test_network_errors_and_timeouts_are_outages(google: FakeGoogle) -> None:
    def boom(form):
        raise httpx.ConnectTimeout("timed out")

    google.token_response = boom
    with pytest.raises(GoogleUnavailable) as exc:
        google.client().exchange_code(code="c", code_verifier="v" * 64)
    # Nothing secret in what callers log or audit.
    assert CLIENT_SECRET not in str(exc.value) and "v" * 64 not in str(exc.value)


def test_refusal_messages_never_echo_googles_text(google: FakeGoogle) -> None:
    google.token_response = lambda form: httpx.Response(
        401, json={"error": "invalid_client <script>secret-ish detail</script>"}
    )
    with pytest.raises(GoogleUnavailable) as exc:
        google.client().exchange_code(code="c", code_verifier="v" * 64)
    assert "<" not in str(exc.value) and " " not in str(exc.value)


# ---- review fixes (2026-11-11) -----------------------------------------------------------------
def test_several_audiences_require_this_client_as_authorized_party(google: FakeGoogle) -> None:
    token = google.id_token(nonce=NONCE, aud=[CLIENT_ID, "other"], azp=None)
    assert reason(google, token) == "authorized_party"
    ok = google.id_token(nonce=NONCE, aud=[CLIENT_ID, "other"], azp=CLIENT_ID)
    assert google.client().verify_id_token(ok, nonce_hash=NONCE_HASH).subject
    single = google.id_token(nonce=NONCE, azp=None)  # one audience: azp may be absent
    assert google.client().verify_id_token(single, nonce_hash=NONCE_HASH).subject


def test_after_a_failed_key_fetch_requests_fail_fast_then_retry() -> None:
    google = FakeGoogle()
    now = [1000.0]
    client = google.client(GoogleKeyCache(clock=lambda: now[0]))
    google.jwks_response = lambda: httpx.Response(503)
    for _ in range(5):
        with pytest.raises(GoogleUnavailable):
            client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)
    assert google.jwks_requests == 1  # the other four were refused without calling Google
    google.jwks_response = None
    now[0] += 11
    assert client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH).subject
    assert google.jwks_requests == 2


def test_unknown_key_ids_during_an_outage_still_call_google_at_most_once_a_minute() -> None:
    google = FakeGoogle()
    now = [1000.0]
    client = google.client(GoogleKeyCache(clock=lambda: now[0]))
    client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH)
    google.jwks_response = lambda: httpx.Response(503)
    now[0] += 61
    for i in range(5):
        forged = jwt.encode({"sub": "1"}, new_key(), algorithm="RS256", headers={"kid": f"k{i}"})
        with pytest.raises((GoogleUnavailable, GoogleTokenInvalid)):
            client.verify_id_token(forged, nonce_hash=NONCE_HASH)
    assert google.jwks_requests == 2  # one failed attempt, then no more within the minute
    # The cached keys still verify genuine tokens meanwhile.
    assert client.verify_id_token(google.id_token(nonce=NONCE), nonce_hash=NONCE_HASH).subject
