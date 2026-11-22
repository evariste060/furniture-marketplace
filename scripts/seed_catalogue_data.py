"""Content of the development catalogue seed (scripts/seed_development_catalogue.py).

Everything here is development sample data, not approved business content: names, prices, stock
levels, specifications, manufacturers and the Kinyarwanda banner text are placeholders for
building and testing the furniture marketplace (ADR-014 phase 6). The categories are the
furniture taxonomy of backend/app/core/furniture.py; product specifications use its attribute
codes (material, color, style, finish, condition, dimensions in cm, weight in kg, assembly), so
the storefront's filters and labels have data.

Seed keys (no is_seed column): a product is the seed's when its slug is listed here and it has a
variant whose SKU starts with DEV-. Categories and brands are matched by slug, banners by English
title, staff and customers by e-mail (domain seed.furnihub.local).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.furniture import TAXONOMY  # noqa: E402

SKU_PREFIX = "DEV-"
EMAIL_DOMAIN = "seed.furnihub.local"

# Stock levels: opening stock and low-stock threshold per variant.
LOW_STOCK_THRESHOLD = 3
OPENING_STOCK = {"in": 30, "best": 40, "low": 2, "out": 0}


@dataclass(frozen=True)
class SeedCategory:
    slug: str
    name: str
    description: str
    sort_order: int
    parent: str | None = None  # the main category's slug; None for a main category


@dataclass(frozen=True)
class SeedBrand:
    slug: str
    name: str


@dataclass(frozen=True)
class SeedVariant:
    code: str  # SKU = DEV-<code>
    name: str
    attributes: dict[str, str]
    price: int
    stock: str  # a key of OPENING_STOCK
    compare_at_price: int | None = None

    @property
    def sku(self) -> str:
        return SKU_PREFIX + self.code


@dataclass(frozen=True)
class SeedProduct:
    slug: str
    name: str
    category: str  # a subcategory slug of the taxonomy
    brand: str | None  # the manufacturer, optional (ADR-014 decision 14)
    model: str | None
    description: str
    specifications: dict[str, Any]
    variants: tuple[SeedVariant, ...]
    featured: bool = False
    warranty: str = "12-month warranty from the seller against manufacturing defects."


@dataclass(frozen=True)
class SeedBanner:
    title_en: str
    title_rw: str
    subtitle_en: str
    subtitle_rw: str
    cta_label_en: str
    cta_label_rw: str
    cta_url: str
    position: int
    overline_en: str | None = None
    overline_rw: str | None = None


@dataclass(frozen=True)
class SeedPerson:
    key: str  # local part of the e-mail address
    full_name: str
    phone: str | None = None
    role: str | None = None  # staff role; None for customers
    district: str = ""
    sector: str = ""
    street: str = ""

    @property
    def email(self) -> str:
        return f"{self.key}@{EMAIL_DOMAIN}"


@dataclass(frozen=True)
class SeedOrder:
    customer: str  # SeedPerson.key
    lines: tuple[tuple[str, int], ...]  # (variant code, quantity)
    status: str  # final status reached through the real transitions
    note: str | None = None


@dataclass(frozen=True)
class SeedReview:
    order: int  # 1-based position in ORDERS; the order must end delivered
    code: str  # variant code of the reviewed line
    rating: int
    status: str  # approved, pending or rejected (moderated through the review service)
    title: str | None = None
    body: str | None = None
    reason: str | None = None  # moderation reason


@dataclass(frozen=True)
class SeedPage:
    slug: str
    locale: str
    title: str
    body: str  # Markdown


@dataclass(frozen=True)
class SeedStore:
    """A demo seller store (ADR-014 phase 2): its owner is a verified customer account at the
    seed domain, and an administrator approves the application."""

    key: str  # local part of the owner's e-mail address
    owner_name: str
    phone: str
    name: str
    description: str
    district: str
    sector: str

    @property
    def email(self) -> str:
        return f"{self.key}@{EMAIL_DOMAIN}"


@dataclass(frozen=True)
class Catalogue:
    categories: tuple[SeedCategory, ...]
    brands: tuple[SeedBrand, ...]
    products: tuple[SeedProduct, ...]
    banners: tuple[SeedBanner, ...]
    staff: tuple[SeedPerson, ...]
    customers: tuple[SeedPerson, ...]
    orders: tuple[SeedOrder, ...]
    reviews: tuple[SeedReview, ...] = field(default=())
    notes: tuple[str, ...] = field(default=())
    pages: tuple[SeedPage, ...] = field(default=())
    contact: tuple[tuple[str, str], ...] = field(default=())  # (setting key, value)
    # ADR-014 phase 2: the seed products are shared out over these stores, in order.
    stores: tuple[SeedStore, ...] = field(default=())


# The furniture taxonomy (ADR-014 phase 6): each main category, then its subcategories.
CATEGORIES = tuple(
    category
    for position, main in enumerate(TAXONOMY, start=1)
    for category in (
        SeedCategory(main.slug, main.name, main.description, position),
        *(
            SeedCategory(child.slug, child.name, child.description, order, parent=main.slug)
            for order, child in enumerate(main.children, start=1)
        ),
    )
)

# Development manufacturers (invented names, not real companies). Most products have none.
BRANDS = (
    SeedBrand("imigongo-craft", "Imigongo Craft"),
    SeedBrand("akagera-living", "Akagera Living"),
    SeedBrand("nyungwe-timber", "Nyungwe Timber"),
    SeedBrand("umucyo-office", "Umucyo Office"),
    SeedBrand("kivu-outdoor", "Kivu Outdoor"),
)


def _v(
    code: str,
    name: str,
    price: int,
    stock: str = "in",
    compare: int | None = None,
    **attributes: str,
) -> SeedVariant:
    return SeedVariant(code, name, attributes, price, stock, compare)


def _specs(
    width: float,
    depth: float,
    height: float,
    material: str,
    color: str,
    style: str,
    *,
    weight: float | None = None,
    finish: str | None = None,
    assembly: bool = False,
    seat: float | None = None,
    **free: str,
) -> dict[str, Any]:
    """Furniture attributes by their codes (app/core/furniture.py), then free specifications."""
    specs: dict[str, Any] = {"width_cm": width, "depth_cm": depth, "height_cm": height}
    if seat is not None:
        specs["seat_height_cm"] = seat
    if weight is not None:
        specs["weight_kg"] = weight
    specs.update(material=material, color=color, style=style)
    if finish is not None:
        specs["finish"] = finish
    specs.update(condition="new", assembly_required=assembly)
    specs.update({name.replace("_", " ").capitalize(): value for name, value in free.items()})
    return specs


PRODUCTS = (
    # Living room
    SeedProduct(
        "kivu-three-seater-sofa",
        "Kivu Three-Seater Sofa",
        "sofas",
        "akagera-living",
        "KV-3S",
        "A deep, comfortable three-seater with a solid eucalyptus frame, high-density foam "
        "cushions and removable, washable covers.",
        _specs(
            210,
            92,
            85,
            "fabric",
            "grey",
            "modern",
            weight=58,
            finish="upholstered",
            seat=45,
            cushions="Removable, washable covers",
        ),
        (
            _v("KIV-SOFA3-GRY", "Grey linen", 685_000, "best", colour="Grey"),
            _v("KIV-SOFA3-BLU", "Navy blue", 685_000, "low", colour="Navy blue"),
            _v("KIV-SOFA3-BEI", "Sand beige", 720_000, "in", 790_000, colour="Sand beige"),
        ),
        featured=True,
    ),
    SeedProduct(
        "inyange-l-shaped-sofa",
        "Inyange L-Shaped Corner Sofa",
        "sofas",
        "akagera-living",
        "IN-L5",
        "A five-seat corner sofa for family living rooms, with a reversible chaise that fits "
        "either side.",
        _specs(
            280,
            180,
            88,
            "fabric",
            "beige",
            "contemporary",
            weight=96,
            finish="upholstered",
            seat=44,
            assembly=True,
        ),
        (_v("INY-LSOFA-BEI", "Sand beige", 1_250_000, "in", colour="Sand beige"),),
        featured=True,
    ),
    SeedProduct(
        "ubumwe-leather-armchair",
        "Ubumwe Leather Armchair",
        "armchairs",
        None,
        None,
        "A wide armchair in full-grain leather on solid wood legs: the reading corner's "
        "favourite seat.",
        _specs(82, 86, 92, "leather", "brown", "mid_century", weight=24, seat=43),
        (
            _v("UBU-ARM-BRN", "Cognac brown", 495_000, "in", colour="Cognac brown"),
            _v("UBU-ARM-BLK", "Black", 495_000, "out", colour="Black"),
        ),
    ),
    SeedProduct(
        "rattan-accent-chair",
        "Rattan Accent Chair",
        "armchairs",
        "imigongo-craft",
        None,
        "Hand-woven rattan on a light frame, made by a Huye cooperative. Cushion included.",
        _specs(70, 72, 80, "rattan", "natural", "african", weight=7, finish="natural", seat=42),
        (_v("RAT-ACC-NAT", "Natural", 185_000, "best"),),
        featured=True,
    ),
    SeedProduct(
        "imigongo-coffee-table",
        "Imigongo Coffee Table",
        "coffee-tables",
        "imigongo-craft",
        None,
        "A low coffee table with a hand-painted imigongo pattern top in black and terracotta.",
        _specs(110, 60, 42, "solid_wood", "black", "african", weight=18, finish="painted"),
        (_v("IMI-COF-BLK", "Black & terracotta", 240_000, "in", 275_000),),
        featured=True,
    ),
    SeedProduct(
        "glass-top-coffee-table",
        "Glass-Top Coffee Table",
        "coffee-tables",
        None,
        None,
        "Tempered glass on a black powder-coated steel frame, with a lower shelf for books.",
        _specs(120, 60, 45, "glass", "black", "industrial", weight=21, assembly=True),
        (_v("GLS-COF-BLK", "Black frame", 165_000, "in"),),
    ),
    SeedProduct(
        "oak-tv-stand-180",
        "Oak TV Stand 180 cm",
        "tv-stands",
        "nyungwe-timber",
        "NT-TV180",
        "A long, low TV stand in oak veneer with two soft-close doors and open shelves for "
        "speakers and consoles.",
        _specs(
            180,
            40,
            50,
            "engineered_wood",
            "oak",
            "scandinavian",
            weight=38,
            finish="matte",
            assembly=True,
            max_screen='Up to 75"',
        ),
        (_v("OAK-TV180-OAK", "Oak", 310_000, "in"),),
    ),
    SeedProduct(
        "ladder-bookshelf",
        "Ladder Bookshelf",
        "shelves-bookcases",
        None,
        None,
        "Five leaning shelves in pine: books, plants and photos without taking floor space.",
        _specs(
            60,
            35,
            180,
            "solid_wood",
            "natural",
            "rustic",
            weight=12,
            finish="natural",
            assembly=True,
        ),
        (_v("LAD-SHELF-NAT", "Natural pine", 95_000, "low"),),
    ),
    # Bedroom
    SeedProduct(
        "muhabura-queen-bed",
        "Muhabura Queen Bed",
        "beds",
        "nyungwe-timber",
        "MH-Q",
        "A solid mahogany bed frame with a slatted base and a tall headboard. Mattress not "
        "included.",
        _specs(
            170,
            215,
            120,
            "solid_wood",
            "walnut",
            "classic",
            weight=75,
            finish="lacquered",
            assembly=True,
            mattress_size="160 × 200 cm",
        ),
        (
            _v("MUH-BED-Q", "Queen, 160 × 200", 890_000, "best", size="Queen"),
            _v("MUH-BED-K", "King, 180 × 200", 1_050_000, "in", size="King"),
        ),
        featured=True,
    ),
    SeedProduct(
        "storage-double-bed",
        "Storage Double Bed",
        "beds",
        None,
        None,
        "An upholstered double bed whose base lifts on gas struts to reveal deep storage.",
        _specs(
            150,
            205,
            105,
            "fabric",
            "grey",
            "contemporary",
            weight=68,
            finish="upholstered",
            assembly=True,
        ),
        (_v("STO-BED-D", "Double, 140 × 190", 620_000, "in", 690_000),),
    ),
    SeedProduct(
        "orthopaedic-foam-mattress",
        "Orthopaedic Foam Mattress",
        "mattresses",
        "akagera-living",
        "AK-ORTHO",
        "Medium-firm high-density foam with a breathable quilted cover, made in Kigali.",
        {
            "width_cm": 160,
            "depth_cm": 200,
            "height_cm": 25,
            "weight_kg": 22,
            "material": "foam",
            "condition": "new",
            "Firmness": "Medium-firm",
        },
        (
            _v("ORT-MAT-140", "140 × 190 cm", 245_000, "in", size="140 × 190"),
            _v("ORT-MAT-160", "160 × 200 cm", 295_000, "best", size="160 × 200"),
        ),
    ),
    SeedProduct(
        "three-door-wardrobe",
        "Three-Door Wardrobe",
        "wardrobes",
        None,
        None,
        "A three-door wardrobe with a hanging rail, shelves and a mirrored centre door.",
        _specs(
            135,
            58,
            200,
            "engineered_wood",
            "white",
            "modern",
            weight=85,
            finish="matte",
            assembly=True,
        ),
        (_v("WAR-3D-WHT", "White", 540_000, "in"),),
    ),
    SeedProduct(
        "six-drawer-dresser",
        "Six-Drawer Dresser",
        "dressers",
        "nyungwe-timber",
        None,
        "Six deep drawers on metal runners in solid wood, with a wide top for a mirror.",
        _specs(
            140,
            45,
            80,
            "solid_wood",
            "walnut",
            "mid_century",
            weight=48,
            finish="satin",
            assembly=False,
        ),
        (_v("SIX-DRS-WAL", "Walnut", 410_000, "low"),),
    ),
    SeedProduct(
        "bedside-table-pair",
        "Bedside Tables (Pair)",
        "bedside-tables",
        None,
        None,
        "Two compact bedside tables, each with a drawer and an open shelf.",
        _specs(45, 35, 55, "engineered_wood", "oak", "scandinavian", weight=9, assembly=True),
        (_v("BED-TBL-OAK", "Oak, pair", 120_000, "in"),),
    ),
    # Dining
    SeedProduct(
        "gisenyi-dining-table-6",
        "Gisenyi Six-Seat Dining Table",
        "dining-tables",
        "nyungwe-timber",
        "GS-6",
        "A solid wood dining table for six with rounded corners and a natural oil finish.",
        _specs(
            180,
            90,
            76,
            "solid_wood",
            "natural",
            "rustic",
            weight=55,
            finish="natural",
            assembly=True,
            seats="6",
        ),
        (_v("GIS-DTBL-6", "180 × 90 cm", 580_000, "best"),),
        featured=True,
    ),
    SeedProduct(
        "marble-round-dining-table",
        "Marble Round Dining Table",
        "dining-tables",
        None,
        None,
        "A round white marble top on a black steel pedestal, seating four.",
        _specs(
            110,
            110,
            75,
            "marble",
            "white",
            "contemporary",
            weight=62,
            finish="polished",
            assembly=True,
            seats="4",
        ),
        (_v("MAR-RTBL-WHT", "White marble", 760_000, "in", 840_000),),
    ),
    SeedProduct(
        "upholstered-dining-chair",
        "Upholstered Dining Chair",
        "dining-chairs",
        None,
        None,
        "A padded dining chair with a curved back on solid wood legs. Sold individually.",
        _specs(48, 55, 88, "fabric", "beige", "classic", weight=6, finish="upholstered", seat=47),
        (
            _v("UPH-DCH-BEI", "Beige", 68_000, "best", colour="Beige"),
            _v("UPH-DCH-GRY", "Grey", 68_000, "in", colour="Grey"),
        ),
    ),
    SeedProduct(
        "sheesham-sideboard",
        "Sheesham Sideboard",
        "sideboards",
        None,
        None,
        "Four doors and two drawers for dinnerware, in solid sheesham with brass handles.",
        _specs(160, 45, 85, "solid_wood", "brown", "classic", weight=52, finish="lacquered"),
        (_v("SHE-SIDE-BRN", "Honey brown", 470_000, "in"),),
    ),
    SeedProduct(
        "industrial-bar-stool",
        "Industrial Bar Stool",
        "bar-stools",
        None,
        None,
        "A steel bar stool with a wooden seat and a footrest, for kitchen islands and counters.",
        _specs(40, 40, 75, "metal", "black", "industrial", weight=5, seat=75),
        (_v("IND-STOOL-BLK", "Black", 45_000, "in"),),
    ),
    # Office
    SeedProduct(
        "umucyo-executive-desk",
        "Umucyo Executive Desk",
        "desks",
        "umucyo-office",
        "UM-EX160",
        "A large executive desk with a lockable drawer unit and a cable tray.",
        _specs(
            160,
            80,
            75,
            "engineered_wood",
            "walnut",
            "contemporary",
            weight=64,
            finish="matte",
            assembly=True,
        ),
        (_v("UMU-DESK-160", "160 × 80 cm", 520_000, "in"),),
        featured=True,
    ),
    SeedProduct(
        "compact-study-desk",
        "Compact Study Desk",
        "desks",
        None,
        None,
        "A small desk with one drawer that fits a bedroom corner: for homework or a laptop.",
        _specs(100, 50, 75, "engineered_wood", "white", "scandinavian", weight=17, assembly=True),
        (_v("CMP-DESK-WHT", "White", 115_000, "best", 135_000),),
    ),
    SeedProduct(
        "ergonomic-mesh-office-chair",
        "Ergonomic Mesh Office Chair",
        "office-chairs",
        "umucyo-office",
        "UM-ERGO",
        "Breathable mesh, adjustable lumbar support, 3D armrests and a reclining back.",
        _specs(65, 65, 120, "fabric", "black", "modern", weight=16, seat=48, assembly=True),
        (
            _v("ERG-CHR-BLK", "Black", 195_000, "best", colour="Black"),
            _v("ERG-CHR-GRY", "Grey", 195_000, "low", colour="Grey"),
        ),
    ),
    SeedProduct(
        "steel-filing-cabinet",
        "Four-Drawer Steel Filing Cabinet",
        "office-storage",
        "umucyo-office",
        None,
        "A lockable steel cabinet with four full-extension drawers for A4 and foolscap files.",
        _specs(47, 62, 132, "metal", "grey", "industrial", weight=45, finish="painted"),
        (_v("STL-FILE-GRY", "Light grey", 260_000, "in"),),
    ),
    SeedProduct(
        "boardroom-table-10",
        "Boardroom Table for Ten",
        "meeting-tables",
        "umucyo-office",
        None,
        "A 3-metre meeting table with a central cable box, delivered and assembled on site.",
        _specs(
            300,
            120,
            75,
            "engineered_wood",
            "oak",
            "contemporary",
            weight=120,
            assembly=True,
            seats="10",
        ),
        (_v("BRD-TBL-10", "300 × 120 cm", 980_000, "low"),),
    ),
    # Outdoor
    SeedProduct(
        "kivu-garden-lounge-set",
        "Kivu Garden Lounge Set",
        "garden-sets",
        "kivu-outdoor",
        "KO-LOUNGE",
        "A weatherproof rattan-effect sofa, two chairs and a glass-top table, with "
        "water-repellent cushions.",
        _specs(
            190,
            75,
            80,
            "plastic",
            "brown",
            "contemporary",
            weight=42,
            seat=40,
            assembly=True,
            pieces="4",
        ),
        (_v("KIV-LNG-BRN", "Brown", 890_000, "in", 990_000),),
        featured=True,
    ),
    SeedProduct(
        "teak-folding-chair",
        "Teak Folding Garden Chair",
        "outdoor-seating",
        "kivu-outdoor",
        None,
        "A folding chair in oiled teak for balconies and gardens. Folds flat to store.",
        _specs(55, 60, 90, "solid_wood", "natural", "classic", weight=6, finish="natural", seat=45),
        (_v("TEK-FCH-NAT", "Natural teak", 75_000, "best"),),
    ),
    SeedProduct(
        "aluminium-outdoor-table",
        "Aluminium Outdoor Table",
        "outdoor-tables",
        "kivu-outdoor",
        None,
        "A rust-free aluminium table with a slatted top that drains rain, seating four.",
        _specs(120, 80, 74, "metal", "grey", "modern", weight=14, assembly=True),
        (_v("ALU-OTBL-GRY", "Grey", 210_000, "out"),),
    ),
    # Kids
    SeedProduct(
        "bunk-bed-with-ladder",
        "Bunk Bed with Ladder",
        "kids-beds",
        None,
        None,
        "A sturdy pine bunk bed with guard rails and a fixed ladder; splits into two single beds.",
        _specs(
            98,
            200,
            160,
            "solid_wood",
            "white",
            "scandinavian",
            weight=70,
            finish="painted",
            assembly=True,
            mattress_size="90 × 190 cm (two)",
        ),
        (_v("BNK-BED-WHT", "White", 430_000, "in"),),
    ),
    SeedProduct(
        "kids-desk-and-chair-set",
        "Kids' Desk and Chair Set",
        "kids-desks",
        None,
        None,
        "A height-adjustable desk and chair for ages 4 to 10, with rounded corners.",
        _specs(
            80, 50, 60, "engineered_wood", "blue", "modern", weight=15, assembly=True, ages="4–10"
        ),
        (_v("KID-DESK-BLU", "Blue", 98_000, "in"),),
    ),
    SeedProduct(
        "toy-storage-unit",
        "Toy Storage Unit",
        "kids-storage",
        None,
        None,
        "Nine open cubes with fabric bins for toys and books.",
        _specs(
            90, 30, 90, "engineered_wood", "multicolour", "contemporary", weight=20, assembly=True
        ),
        (_v("TOY-STOR-MLT", "White with coloured bins", 85_000, "low"),),
    ),
)

# The first banner is the home hero. Kinyarwanda text is draft test data, not approved copy.
BANNERS = (
    SeedBanner(
        title_en="Furniture From Rwanda's Best Makers",
        title_rw="Ibikoresho byo mu nzu by'abanyabukorikori beza bo mu Rwanda",
        subtitle_en=(
            "Sofas, beds, dining and office furniture from trusted local stores — delivered "
            "across Kigali and all of Rwanda."
        ),
        subtitle_rw=(
            "Intebe, ibitanda, ameza n'ibikoresho byo mu biro biva mu maduka yizewe — "
            "bikugezwaho i Kigali no mu Rwanda hose."
        ),
        cta_label_en="Shop Now",
        cta_label_rw="Gura ubu",
        cta_url="/category/living-room",
        position=0,
        overline_en="Many stores, one marketplace",
        overline_rw="Amaduka menshi, isoko rimwe",
    ),
    SeedBanner(
        title_en="Sleep Better",
        title_rw="Siinzira neza",
        subtitle_en="Solid wood beds, mattresses and wardrobes for every bedroom.",
        subtitle_rw="Ibitanda by'ibiti bikomeye, matela n'utubati tw'imyenda ku cyumba cyose.",
        cta_label_en="Shop Bedroom",
        cta_label_rw="Reba ibyo mu cyumba",
        cta_url="/category/bedroom",
        position=1,
    ),
    SeedBanner(
        title_en="Furnish Your Office",
        title_rw="Tegura ibiro byawe",
        subtitle_en="Desks, ergonomic chairs and storage, delivered and assembled.",
        subtitle_rw="Ameza, intebe zinogeye umubiri n'ububiko, bikugezwaho bigateranywa.",
        cta_label_en="Shop Office",
        cta_label_rw="Reba ibyo mu biro",
        cta_url="/category/office",
        position=2,
    ),
)

STAFF = (
    # The Marketplace Administrator is the only staff role (SC-05, 2026-11-21).
    SeedPerson("admin", "Seed Administrator", role="administrator"),
)

CUSTOMERS = (
    SeedPerson(
        "aline.uwase",
        "Aline Uwase",
        "+250780000101",
        district="Gasabo",
        sector="Kimironko",
        street="KG 11 Ave, house 24",
    ),
    SeedPerson(
        "jean.habimana",
        "Jean Bosco Habimana",
        "+250780000102",
        district="Kicukiro",
        sector="Niboye",
        street="KK 15 Rd, house 7",
    ),
    SeedPerson(
        "grace.mukamana",
        "Grace Mukamana",
        "+250780000103",
        district="Nyarugenge",
        sector="Nyamirambo",
        street="KN 2 St, near the market",
    ),
    SeedPerson(
        "eric.niyonzima",
        "Eric Niyonzima",
        "+250780000104",
        district="Gasabo",
        sector="Remera",
        street="KG 17 Ave, apartment 3B",
    ),
    SeedPerson(
        "diane.ingabire",
        "Diane Ingabire",
        "+250780000105",
        district="Kicukiro",
        sector="Gikondo",
        street="KK 31 Ave, house 12",
    ),
)

# Cash on delivery throughout. Delivered orders give `sort_by=bestselling` its data. Several
# orders hold products of more than one store, so they split into several seller orders.
ORDERS = (
    SeedOrder("aline.uwase", (("KIV-SOFA3-GRY", 1), ("IMI-COF-BLK", 1)), "delivered"),
    SeedOrder("jean.habimana", (("ERG-CHR-BLK", 1),), "delivered"),
    SeedOrder("grace.mukamana", (("MUH-BED-Q", 1),), "delivered"),
    SeedOrder("eric.niyonzima", (("RAT-ACC-NAT", 1), ("IMI-COF-BLK", 1)), "delivered"),
    SeedOrder("diane.ingabire", (("ERG-CHR-BLK", 1), ("UPH-DCH-BEI", 4)), "delivered"),
    SeedOrder("aline.uwase", (("MUH-BED-Q", 1),), "delivered"),
    SeedOrder("jean.habimana", (("KIV-SOFA3-GRY", 1),), "delivered"),
    SeedOrder("grace.mukamana", (("IMI-COF-BLK", 1), ("TEK-FCH-NAT", 2)), "delivered"),
    SeedOrder("eric.niyonzima", (("GIS-DTBL-6", 1),), "dispatched"),
    SeedOrder("diane.ingabire", (("UMU-DESK-160", 1),), "dispatched"),
    SeedOrder("aline.uwase", (("ORT-MAT-160", 1),), "processing"),
    SeedOrder("jean.habimana", (("WAR-3D-WHT", 1),), "confirmed"),
    SeedOrder("grace.mukamana", (("CMP-DESK-WHT", 1),), "received"),
    SeedOrder("eric.niyonzima", (("BED-TBL-OAK", 1),), "received"),
    SeedOrder(
        "diane.ingabire",
        (("GLS-COF-BLK", 1),),
        "cancelled",
        note="Seed order: cancelled by the customer before confirmation.",
    ),
)

# One review per item of the 8 delivered orders (module 20): 9 approved, 2 waiting for
# moderation and 1 rejected, so the product page, the rating filters and the admin queue all
# have data.
REVIEWS = (
    SeedReview(
        1,
        "KIV-SOFA3-GRY",
        5,
        "approved",
        "Comfortable and well made",
        "Delivered to Kimironko and carried upstairs. The covers wash well.",
    ),
    SeedReview(1, "IMI-COF-BLK", 4, "approved", "Beautiful pattern"),
    SeedReview(
        2,
        "ERG-CHR-BLK",
        4,
        "approved",
        "Good for long days",
        "My back is better. The armrests could be a little softer.",
    ),
    SeedReview(3, "MUH-BED-Q", 5, "approved", "Solid wood", "Heavy and very stable."),
    SeedReview(4, "RAT-ACC-NAT", 4, "approved", None, "Lovely chair, the cushion is thin."),
    SeedReview(4, "IMI-COF-BLK", 5, "approved", "Everyone asks about it"),
    SeedReview(5, "ERG-CHR-BLK", 3, "approved", "Fine for the price"),
    SeedReview(
        5, "UPH-DCH-BEI", 5, "pending", "Elegant chairs", "Four chairs, all arrived in one week."
    ),
    SeedReview(6, "MUH-BED-Q", 4, "approved", "Good bed for the guest room"),
    SeedReview(7, "KIV-SOFA3-GRY", 5, "approved", "Worth it", "The grey matches everything."),
    SeedReview(
        8,
        "IMI-COF-BLK",
        2,
        "rejected",
        "Call me for cheaper tables",
        "WhatsApp 0780000000 for a better deal.",
        reason="Advertising and a phone number",
    ),
    SeedReview(8, "TEK-FCH-NAT", 4, "pending", "Nice on the balcony", None),
)

# Policy pages (module 19, owner decision 2026-10-29): short drafts in both languages so the
# storefront pages can be built and tested. Each one says it is a draft: the business-approved
# text replaces it in the admin before go-live (QA checklist). Production gets no seed pages.
DRAFT_EN = "> Draft: replace this text with the approved policy before the store opens."
DRAFT_RW = "> Inyandiko y'agateganyo: isimbuze politiki yemejwe mbere y'uko iduka rifungura."
PAGES = (
    SeedPage(
        "about-us",
        "en",
        "About us",
        f"""{DRAFT_EN}

FurniHub is a marketplace of furniture stores in Rwanda: sofas, beds, dining, office and
outdoor furniture from approved local sellers, delivered to every district.

## What we promise

- Every store is reviewed and approved before it sells.
- Clear prices in Rwandan francs, with VAT included.
- Help before and after you buy, on WhatsApp or by phone.""",
    ),
    SeedPage(
        "about-us",
        "rw",
        "Abo turi bo",
        f"""{DRAFT_RW}

FurniHub ni isoko ry'amaduka y'ibikoresho byo mu nzu mu Rwanda: intebe, ibitanda, ameza,
ibikoresho byo mu biro n'ibyo hanze biva ku bacuruzi bemewe, bikagezwa mu turere twose.

## Ibyo tubasezeranya

- Buri iduka risuzumwa kandi rikemezwa mbere yo gucuruza.
- Ibiciro bigaragara neza mu mafaranga y'u Rwanda, TVA irimo.
- Ubufasha mbere na nyuma yo kugura, kuri WhatsApp cyangwa kuri telefoni.""",
    ),
    SeedPage(
        "delivery-information",
        "en",
        "Delivery information",
        f"""{DRAFT_EN}

We deliver to every district in Rwanda. You see the exact delivery fee at checkout before you
place your order.

## Delivery zones

| Where | Arrives |
| --- | --- |
| Kigali | 1–2 working days |
| Rest of Rwanda | 2–4 working days |

## On delivery day

- We call or send an SMS before the rider comes.
- Check the box is sealed before you accept it.
- Cash on delivery is available where the checkout offers it.

Address outside our zones? [Contact us](/contact) and we will arrange delivery.""",
    ),
    SeedPage(
        "delivery-information",
        "rw",
        "Amakuru ku igezwa ry'ibicuruzwa",
        f"""{DRAFT_RW}

Tugeza ibicuruzwa mu turere twose tw'u Rwanda. Ubona igiciro nyacyo cyo kugeza igicuruzwa mbere
yo kwemeza itumiza.

## Aho tugeza

| Aho | Igihe bigerayo |
| --- | --- |
| Kigali | Iminsi 1–2 y'akazi |
| Ahandi mu Rwanda | Iminsi 2–4 y'akazi |

## Umunsi wo kubigeza

- Turaguhamagara cyangwa tukoherereza SMS mbere y'uko umumotari aza.
- Reba ko agasanduku gafunze neza mbere yo kukakira.
- Kwishyura ubigejejweho birashoboka aho ahishyurirwa abigaragaza.

Aderesi yawe iri hanze y'aho tugeza? [Twandikire](/contact) tuzabitegura.""",
    ),
    SeedPage(
        "returns-and-refunds",
        "en",
        "Returns & refunds",
        f"""{DRAFT_EN}

You can return a product within 7 days of delivery if it is faulty or not what you ordered.

## How to return

1. Contact us with your order number.
2. Keep the product, its box and accessories together.
3. We inspect it and refund or replace it.

Refunds go back to the way you paid.""",
    ),
    SeedPage(
        "returns-and-refunds",
        "rw",
        "Gusubiza no gusubizwa amafaranga",
        f"""{DRAFT_RW}

Ushobora gusubiza igicuruzwa mu minsi 7 nyuma yo kukigezwaho niba gifite ikibazo cyangwa atari
icyo watumije.

## Uko wasubiza

1. Twandikire uduhe nimero y'itumiza ryawe.
2. Bika igicuruzwa, agasanduku kacyo n'ibikoresho byacyo hamwe.
3. Turakigenzura tukagusubiza amafaranga cyangwa tukaguha ikindi.

Amafaranga asubizwa hakoreshejwe uburyo wishyuyemo.""",
    ),
    SeedPage(
        "warranty",
        "en",
        "Warranty",
        f"""{DRAFT_EN}

Every product comes with the warranty shown on its page.

## What the warranty covers

- Manufacturing faults under normal use.
- Repair or replacement at our store.

It does not cover drops, liquid damage or repairs by others.""",
    ),
    SeedPage(
        "warranty",
        "rw",
        "Garanti",
        f"""{DRAFT_RW}

Buri gicuruzwa gifite garanti igaragara ku rupapuro rwacyo.

## Ibyo garanti ikubiyemo

- Ibibazo byo mu ikorwa ry'igicuruzwa gikoreshejwe neza.
- Gukorwa cyangwa gusimbuzwa mu iduka ryacu.

Ntikubiyemo kugwa, kwangizwa n'amazi cyangwa gukorwa n'abandi.""",
    ),
    SeedPage(
        "privacy-policy",
        "en",
        "Privacy policy",
        f"""{DRAFT_EN}

We use your name, phone, email and address only to deliver your orders, support you and keep
the records the law requires.

## Your choices

- You can update your details in your account.
- You can ask us to delete your account at any time.

We never sell your personal data.""",
    ),
    SeedPage(
        "privacy-policy",
        "rw",
        "Politiki y'ibanga",
        f"""{DRAFT_RW}

Dukoresha izina, telefoni, imeli na aderesi byawe gusa mu kukugezaho ibyo watumije, kugufasha
no kubika inyandiko itegeko risaba.

## Uburenganzira bwawe

- Ushobora guhindura amakuru yawe muri konti yawe.
- Ushobora kudusaba gusiba konti yawe igihe icyo ari cyo cyose.

Ntitugurisha amakuru yawe bwite.""",
    ),
    SeedPage(
        "terms-and-conditions",
        "en",
        "Terms & conditions",
        f"""{DRAFT_EN}

By ordering on FurniHub you agree to these terms.

## Orders and prices

- Prices are in Rwandan francs and include VAT.
- An order is confirmed once we accept it.
- We may cancel an order that cannot be fulfilled and refund any payment.""",
    ),
    SeedPage(
        "terms-and-conditions",
        "rw",
        "Amategeko n'amabwiriza",
        f"""{DRAFT_RW}

Iyo utumije kuri FurniHub uba wemeye aya mabwiriza.

## Amatumiza n'ibiciro

- Ibiciro biri mu mafaranga y'u Rwanda kandi birimo TVA.
- Itumiza ryemezwa iyo turyakiriye.
- Dushobora guhagarika itumiza ridashobora kubahirizwa tugasubiza amafaranga yishyuwe.""",
    ),
)

# Store contact for development (module 19): sample values, set only while the setting is unset;
# the cleanup removes them only while they still hold these values.
CONTACT = (
    ("store.name", "FurniHub"),
    ("contact.phone", "+250 788 123 456"),
    ("contact.whatsapp", "+250 788 123 456"),
    ("contact.email", "hello@furnihub.example"),
    ("contact.address", "KN 5 Ave, Kigali, Rwanda"),
    ("contact.hours", "Mon – Sat: 8:00 AM – 6:00 PM"),
)

STORES = (
    SeedStore(
        "seller.kigali-oak",
        "Claudine Mukamana",
        "+250780000201",
        "Kigali Oak Works",
        "Development seed store: solid wood furniture made in Kigali.",
        "Gasabo",
        "Kimironko",
    ),
    SeedStore(
        "seller.nyamirambo-living",
        "Eric Nshimiyimana",
        "+250780000202",
        "Nyamirambo Living",
        "Development seed store: sofas, chairs and living-room pieces.",
        "Nyarugenge",
        "Nyamirambo",
    ),
    SeedStore(
        "seller.kicukiro-office",
        "Grace Uwimana",
        "+250780000203",
        "Kicukiro Office Supply",
        "Development seed store: desks, office chairs and storage.",
        "Kicukiro",
        "Niboye",
    ),
)

CATALOGUE = Catalogue(
    CATEGORIES,
    BRANDS,
    PRODUCTS,
    BANNERS,
    STAFF,
    CUSTOMERS,
    ORDERS,
    REVIEWS,
    pages=PAGES,
    contact=CONTACT,
    stores=STORES,
)
