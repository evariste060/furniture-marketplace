"""The furniture domain (ADR-014 decision 14, phase 6): the category taxonomy loaded as data, the
product attributes and the attribute set of each category.

No schema change: categories are ordinary category rows (created by
scripts/apply_category_taxonomy.py and the development seed), and attributes live in the
existing products.specifications JSONB under the keys below. An attribute set only guides the
product editor and the filters; no attribute is required on any product. Keys that are not
listed here are still accepted as free specifications (name -> text), as before.

The values of a known attribute are checked, so the storefront can translate them and filter on
them: a choice attribute holds one of its codes, a number attribute a positive number in its
unit, a yes/no attribute a boolean. Labels for the keys and codes live in the frontend messages
(English and Kinyarwanda), never here.

The taxonomy and the choice lists are DEVELOPMENT DRAFTS for the project owner to confirm
(ADR-014 "Phase 6 as built").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

AttributeKind = Literal["choice", "number", "boolean"]


@dataclass(frozen=True)
class Attribute:
    key: str
    kind: AttributeKind
    unit: str | None = None  # number attributes: "cm" or "kg"
    choices: tuple[str, ...] = ()  # choice attributes: the allowed codes, in display order
    filterable: bool = False  # offered as a storefront filter (facets)


MATERIALS = (
    "solid_wood",
    "engineered_wood",
    "bamboo",
    "rattan",
    "metal",
    "glass",
    "marble",
    "stone",
    "fabric",
    "leather",
    "faux_leather",
    "plastic",
    "foam",
)
COLORS = (
    "natural",
    "oak",
    "walnut",
    "white",
    "black",
    "grey",
    "beige",
    "brown",
    "blue",
    "green",
    "red",
    "yellow",
    "multicolour",
)
STYLES = (
    "modern",
    "contemporary",
    "classic",
    "rustic",
    "industrial",
    "scandinavian",
    "mid_century",
    "african",
)
FINISHES = ("natural", "matte", "satin", "gloss", "lacquered", "painted", "polished", "upholstered")
CONDITIONS = ("new", "refurbished", "used")

ATTRIBUTES: Mapping[str, Attribute] = {
    a.key: a
    for a in (
        Attribute("width_cm", "number", unit="cm"),
        Attribute("depth_cm", "number", unit="cm"),
        Attribute("height_cm", "number", unit="cm"),
        Attribute("seat_height_cm", "number", unit="cm"),
        Attribute("weight_kg", "number", unit="kg"),
        Attribute("material", "choice", choices=MATERIALS, filterable=True),
        Attribute("color", "choice", choices=COLORS, filterable=True),
        Attribute("style", "choice", choices=STYLES, filterable=True),
        Attribute("finish", "choice", choices=FINISHES),
        Attribute("condition", "choice", choices=CONDITIONS),
        Attribute("assembly_required", "boolean"),
    )
}
FILTER_ATTRIBUTES: tuple[str, ...] = tuple(k for k, a in ATTRIBUTES.items() if a.filterable)
NUMBER_MAX = 100_000  # cm or kg: anything above is a typing mistake

_DIMENSIONS = ("width_cm", "depth_cm", "height_cm")
_LOOKS = ("material", "color", "style", "finish")
_COMMON = (*_DIMENSIONS, "weight_kg", *_LOOKS, "condition", "assembly_required")
_SEATING = (*_DIMENSIONS, "seat_height_cm", "weight_kg", *_LOOKS, "condition", "assembly_required")

# The set of a category: its own entry, else its main category's, else DEFAULT_SET.
DEFAULT_SET: tuple[str, ...] = _COMMON
ATTRIBUTE_SETS: Mapping[str, tuple[str, ...]] = {
    "living-room": _COMMON,
    "sofas": _SEATING,
    "armchairs": _SEATING,
    "bedroom": _COMMON,
    "mattresses": (*_DIMENSIONS, "weight_kg", "material", "condition"),
    "dining": _COMMON,
    "dining-chairs": _SEATING,
    "bar-stools": _SEATING,
    "office": _COMMON,
    "office-chairs": _SEATING,
    "outdoor": _COMMON,
    "outdoor-seating": _SEATING,
    "kids": _COMMON,
}


@dataclass(frozen=True)
class TaxonomyCategory:
    slug: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class TaxonomyMain:
    slug: str
    name: str
    description: str
    children: tuple[TaxonomyCategory, ...]


# Main categories in menu order, each with its subcategories in order. Category names are the
# shop's data (staff rename them in the admin), so they are English here like the electronics
# categories were.
TAXONOMY: tuple[TaxonomyMain, ...] = (
    TaxonomyMain(
        "living-room",
        "Living Room",
        "Sofas, chairs & tables",
        (
            TaxonomyCategory("sofas", "Sofas"),
            TaxonomyCategory("armchairs", "Armchairs"),
            TaxonomyCategory("coffee-tables", "Coffee Tables"),
            TaxonomyCategory("tv-stands", "TV Stands"),
            TaxonomyCategory("shelves-bookcases", "Shelves & Bookcases"),
        ),
    ),
    TaxonomyMain(
        "bedroom",
        "Bedroom",
        "Beds, wardrobes & more",
        (
            TaxonomyCategory("beds", "Beds"),
            TaxonomyCategory("mattresses", "Mattresses"),
            TaxonomyCategory("wardrobes", "Wardrobes"),
            TaxonomyCategory("dressers", "Dressers & Chests"),
            TaxonomyCategory("bedside-tables", "Bedside Tables"),
        ),
    ),
    TaxonomyMain(
        "dining",
        "Dining",
        "Tables, chairs & storage",
        (
            TaxonomyCategory("dining-tables", "Dining Tables"),
            TaxonomyCategory("dining-chairs", "Dining Chairs"),
            TaxonomyCategory("dining-sets", "Dining Sets"),
            TaxonomyCategory("sideboards", "Sideboards & Cabinets"),
            TaxonomyCategory("bar-stools", "Bar Stools"),
        ),
    ),
    TaxonomyMain(
        "office",
        "Office",
        "Desks, chairs & storage",
        (
            TaxonomyCategory("desks", "Desks"),
            TaxonomyCategory("office-chairs", "Office Chairs"),
            TaxonomyCategory("office-storage", "Filing & Storage"),
            TaxonomyCategory("meeting-tables", "Meeting Tables"),
        ),
    ),
    TaxonomyMain(
        "outdoor",
        "Outdoor",
        "Garden & terrace furniture",
        (
            TaxonomyCategory("outdoor-seating", "Outdoor Seating"),
            TaxonomyCategory("outdoor-tables", "Outdoor Tables"),
            TaxonomyCategory("garden-sets", "Garden Sets"),
        ),
    ),
    TaxonomyMain(
        "kids",
        "Kids",
        "Beds, desks & storage",
        (
            TaxonomyCategory("kids-beds", "Kids' Beds"),
            TaxonomyCategory("kids-desks", "Kids' Desks & Chairs"),
            TaxonomyCategory("kids-storage", "Toy Storage"),
        ),
    ),
)

TAXONOMY_SLUGS: frozenset[str] = frozenset(
    {main.slug for main in TAXONOMY} | {c.slug for main in TAXONOMY for c in main.children}
)


def attribute_set(category_slug: str | None, main_slug: str | None = None) -> tuple[str, ...]:
    """The attribute keys the editor offers for a category (its own set, else its main
    category's, else the default)."""
    for slug in (category_slug, main_slug):
        if slug and slug in ATTRIBUTE_SETS:
            return ATTRIBUTE_SETS[slug]
    return DEFAULT_SET


def specification_problems(specifications: Mapping[str, Any]) -> list[str]:
    """What is wrong with the known attributes of a specifications object (empty when nothing).
    Unknown keys are free specifications and are not checked here."""
    problems: list[str] = []
    for key, value in specifications.items():
        attribute = ATTRIBUTES.get(key)
        if attribute is None:
            continue
        if attribute.kind == "choice":
            if not isinstance(value, str) or value not in attribute.choices:
                problems.append(f"{key} must be one of: {', '.join(attribute.choices)}.")
        elif attribute.kind == "number":
            number_ok = isinstance(value, int | float) and not isinstance(value, bool)
            if not number_ok or not 0 < value <= NUMBER_MAX:
                problems.append(f"{key} must be a number above 0 and at most {NUMBER_MAX}.")
        elif not isinstance(value, bool):
            problems.append(f"{key} must be true or false.")
    return problems


def check_specifications(specifications: dict[str, Any]) -> dict[str, Any]:
    """Pydantic after-validator for the product schemas' specifications."""
    problems = specification_problems(specifications)
    if problems:
        raise ValueError(" ".join(problems))
    return specifications
