import hashlib
import hmac
import re
import secrets
from functools import lru_cache

# Scrypt parameters recommended by OWASP / Python defaults
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEYLEN = 64


def hash_password(password: str) -> str:
    """Hash a plaintext password using memory-hard scrypt with cryptographic salt."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=0,
        dklen=SCRYPT_KEYLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored scrypt hash using constant-time comparison."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        stored_hash = bytes.fromhex(parts[5])

        recomputed = hashlib.scrypt(
            plain_password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=0,
            dklen=len(stored_hash),
        )
        return secrets.compare_digest(stored_hash, recomputed)
    except Exception:
        return False


@lru_cache
def _dummy_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def burn_password_check(plain_password: str) -> None:
    """Spend the same scrypt work as a real check when no account matches (anti-enumeration)."""
    verify_password(plain_password, _dummy_password_hash())


def pseudonymize_identifier(identifier: str, key: str) -> str:
    """Keyed HMAC-SHA256 of a normalised identifier.

    Lets authorised investigators who hold the key match a known email/phone to audit records
    and rate-limit buckets, without storing the identifier itself.
    """
    digest = hmac.new(key.encode("utf-8"), identifier.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


PASSWORD_MAX_LENGTH = 256


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate that password meets security requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit or special character
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if len(password) > PASSWORD_MAX_LENGTH:
        return False, f"Password must be at most {PASSWORD_MAX_LENGTH} characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[\d\W_]", password):
        return False, "Password must contain at least one digit or special character."
    return True, ""


def generate_session_token() -> str:
    """Generate a high-entropy cryptographically secure random session token."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Compute SHA-256 digest of session token to store in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_verification_token() -> str:
    """An email verification token (ADR-006 amendment 2026-11-12): 256 random bits, URL-safe,
    43 characters. Sent only in the verification link; never stored or logged."""
    return secrets.token_urlsafe(32)


def hash_verification_token(token: str) -> str:
    """SHA-256 of a verification token, the only form stored. The token has 256 bits of entropy,
    so an unkeyed digest cannot be reversed or guessed; lookups match the digest exactly."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_cart_token() -> str:
    """A guest cart token (module 11; RE-026 B7): 256 random bits, URL-safe, 43 characters."""
    return secrets.token_urlsafe(32)


def hash_cart_token(token: str) -> str:
    """SHA-256 of a guest cart token; only this is stored (carts.guest_token_hash). A keyed
    hash is not needed: the token is random, so its digest cannot be reversed or guessed."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


RESET_CODE_DIGITS = 6


def generate_reset_code() -> str:
    """Uniformly random 6-digit code from the OS CSPRNG (leading zeros kept)."""
    return f"{secrets.randbelow(10**RESET_CODE_DIGITS):0{RESET_CODE_DIGITS}d}"


def hash_reset_code(user_id: str, code: str, key: str) -> str:
    """Keyed HMAC-SHA256 of a reset code, bound to one user.

    A 6-digit code has only a million values, so a plain hash could be reversed from a database
    copy; the server key prevents that, and the user ID stops a code being valid for anyone else.
    """
    message = f"password-reset:{user_id}:{code}".encode()
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
