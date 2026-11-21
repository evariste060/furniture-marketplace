"""Single normalisation policy for login identifiers (email and Rwandan mobile numbers).

Registration, login, profile updates and saved addresses all use these functions, so the
canonical stored value is always the value looked up at login.
"""

import re

EMAIL_MAX_LENGTH = 254  # RFC 5321 path limit; also fits users.email VARCHAR(255)
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
CANONICAL_PHONE_REGEX = r"^\+2507[0-9]{8}$"  # also enforced by a PostgreSQL CHECK constraint
PHONE_SEPARATORS = re.compile(r"[\s\-\(\)]")
PHONE_INPUT_MAX_LENGTH = 32


def validate_email_format(email: str) -> str:
    cleaned = email.strip()
    if len(cleaned) > EMAIL_MAX_LENGTH:
        raise ValueError(f"Email address must be at most {EMAIL_MAX_LENGTH} characters.")
    if not EMAIL_REGEX.match(cleaned):
        raise ValueError("Invalid email address format.")
    return cleaned.lower()


def validate_rwanda_phone(phone: str) -> str:
    """Return the canonical +2507XXXXXXXX form of an approved Rwandan mobile number.

    Accepted inputs: +2507XXXXXXXX, 2507XXXXXXXX, 07XXXXXXXX (spaces, dashes, brackets ignored).
    """
    if len(phone) > PHONE_INPUT_MAX_LENGTH:
        raise ValueError("Phone number is too long.")
    cleaned = PHONE_SEPARATORS.sub("", phone)
    if re.match(r"^\+2507\d{8}$", cleaned):
        return cleaned
    if re.match(r"^2507\d{8}$", cleaned):
        return f"+{cleaned}"
    if re.match(r"^07\d{8}$", cleaned):
        return f"+250{cleaned[1:]}"
    raise ValueError(
        "Phone number must be a valid Rwandan mobile number (e.g., +250788123456 or 0788123456)."
    )


def normalize_login_identifier(identifier: str) -> str:
    """Normalise a login identifier with the same rules used at registration.

    Values containing '@' are treated as email; everything else must be an approved phone format.
    Raises ValueError for anything else, so invalid formats are rejected consistently.
    """
    value = identifier.strip()
    if "@" in value:
        return validate_email_format(value)
    return validate_rwanda_phone(value)
