"""Random credentials for disposable test accounts.

Privileged test accounts never use fixed passwords: each one is generated per test run, kept in
memory only, and never printed or written to a file.
"""

import secrets


def random_password() -> str:
    """A fresh password that satisfies the password policy (upper, lower, digit, symbol)."""
    return secrets.token_urlsafe(24) + "aA1!"
