"""Catalogue slug rules (module 5, RE-018): lowercase ASCII, hyphens, numeric suffixes."""

import re

import pytest

from app.core.slugs import SLUG_PATTERN, first_free_slug, slugify, with_suffix


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Smart Phones", "smart-phones"),
        ("  TVs & Audio!  ", "tvs-audio"),
        ("Écouteurs sans fil", "ecouteurs-sans-fil"),
        ("Laptops/Notebooks -- 2026", "laptops-notebooks-2026"),
        ("Samsung", "samsung"),
        ("ÀÉÎÕÜ ñ ç", "aeiou-n-c"),
        ("株式会社", ""),
        ("---", ""),
    ],
)
def test_slugify_normalises_to_lowercase_ascii_and_single_hyphens(name, slug):
    assert slugify(name, 180) == slug
    if slug:
        assert re.fullmatch(SLUG_PATTERN, slug)


def test_slugify_truncates_without_a_trailing_hyphen():
    assert slugify("abc def", 4) == "abc"
    assert len(slugify("x" * 300, 180)) == 180


def test_suffix_keeps_the_slug_within_the_maximum_length():
    assert with_suffix("phones", 2, 180) == "phones-2"
    long_base = "a" * 180
    suffixed = with_suffix(long_base, 12, 180)
    assert len(suffixed) == 180 and suffixed.endswith("-12")
    assert with_suffix("ab-cd", 2, 5) == "ab-2"  # no double hyphen after truncation


def test_first_free_slug_uses_the_smallest_free_suffix_deterministically():
    taken = {"phones", "phones-2", "phones-4"}
    assert first_free_slug("phones", taken.__contains__, 180) == "phones-3"
    assert first_free_slug("tablets", taken.__contains__, 180) == "tablets"
    assert first_free_slug("phones", taken.__contains__, 180) == "phones-3"
