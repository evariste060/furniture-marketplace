import pytest

from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    validate_password_strength,
    verify_password,
)
from app.schemas.auth import validate_email_format, validate_rwanda_phone
from app.services.audit_service import sanitize_audit_details


def test_password_hashing_and_verification():
    raw_pass = "P@ssword2026!"
    hashed = hash_password(raw_pass)
    assert hashed.startswith("scrypt$16384$8$1$")
    assert verify_password(raw_pass, hashed)
    assert not verify_password("WrongPassword123!", hashed)
    assert not verify_password(raw_pass, "invalid-hash-string")


def test_password_strength_validation():
    # Valid passwords
    assert validate_password_strength("ValidPassword1!")[0]
    assert validate_password_strength("RwandaTech2026_")[0]

    # Invalid passwords
    assert not validate_password_strength("short1!")[0]
    assert not validate_password_strength("nouppercase123!")[0]
    assert not validate_password_strength("NOLOWERCASE123!")[0]
    assert not validate_password_strength("NoDigitsOrSpecial")[0]


def test_session_token_generation_and_hashing():
    t1 = generate_session_token()
    t2 = generate_session_token()
    assert len(t1) >= 40
    assert t1 != t2

    h1 = hash_session_token(t1)
    assert len(h1) == 64
    assert hash_session_token(t1) == h1
    assert hash_session_token(t2) != h1


def test_rwanda_phone_validation():
    # Valid formats normalized to +2507XXXXXXXX
    assert validate_rwanda_phone("+250788123456") == "+250788123456"
    assert validate_rwanda_phone("250788123456") == "+250788123456"
    assert validate_rwanda_phone("0788123456") == "+250788123456"
    assert validate_rwanda_phone("+250 788 123 456") == "+250788123456"

    # Invalid formats
    with pytest.raises(ValueError):
        validate_rwanda_phone("+250688123456")  # Non-7 prefix
    with pytest.raises(ValueError):
        validate_rwanda_phone("12345")


def test_email_validation():
    assert validate_email_format("user@example.com") == "user@example.com"
    assert validate_email_format("  USER@EXAMPLE.COM ") == "user@example.com"

    with pytest.raises(ValueError):
        validate_email_format("invalid-email")
    with pytest.raises(ValueError):
        validate_email_format("@missingusername.com")


def test_audit_sanitization():
    raw_details = {
        "user_id": "123",
        "email": "test@example.com",
        "password": "SuperSecretPassword123!",
        "token": "secret_session_token",
        "nested": {
            "credit_card": "4111222233334444",
            "safe_field": "ok",
        },
    }
    sanitized = sanitize_audit_details(raw_details)
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["nested"]["credit_card"] == "[REDACTED]"
    assert sanitized["nested"]["safe_field"] == "ok"
    # Raw personal identifiers are never stored; callers must pass an identifier_ref pseudonym.
    assert sanitized["email"] == "[PSEUDONYMISE]"
