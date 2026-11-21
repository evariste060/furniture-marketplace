"""URL slugs for catalogue records (module 5): lowercase ASCII words joined by single hyphens.

Generated slugs come from the name: accents are folded to ASCII, anything else that is not a
letter or digit becomes a hyphen. A collision gets the smallest free numeric suffix (-2, -3, ...).
"""

import re
import unicodedata
from collections.abc import Callable

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


def slugify(text: str, max_length: int) -> str:
    """The slug for a name; empty when the name has no ASCII letters or digits."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def with_suffix(base: str, number: int, max_length: int) -> str:
    """base-number, shortening base so the whole slug fits max_length."""
    suffix = f"-{number}"
    return base[: max_length - len(suffix)].rstrip("-") + suffix


def first_free_slug(base: str, is_taken: Callable[[str], bool], max_length: int) -> str:
    """base itself, or the first base-N (N >= 2) that is not taken."""
    if not is_taken(base):
        return base
    number = 2
    while is_taken(candidate := with_suffix(base, number, max_length)):
        number += 1
    return candidate
