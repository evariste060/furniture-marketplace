"""Content of the development catalogue seed (scripts/seed_development_catalogue.py).

Everything here is development sample data, not approved business content: names, prices, stock
levels, specifications and the Kinyarwanda banner text are placeholders for building and testing
the frontend. Categories follow the category nav of frontend/design/screens/Header.dc.html; the
category subtitles and the first banner come from frontend/design/screens/Main.dc.html.

Seed keys (no is_seed column): a product is the seed's when its slug is listed here and it has a
variant whose SKU starts with DEV-. Categories and brands are matched by slug, banners by English
title, staff and customers by e-mail (domain seed.3sixty.local).
"""

from __future__ import annotations

from dataclasses import dataclass, field

SKU_PREFIX = "DEV-"
EMAIL_DOMAIN = "seed.3sixty.local"

# Stock levels: opening stock and low-stock threshold per variant.
LOW_STOCK_THRESHOLD = 3
OPENING_STOCK = {"in": 30, "best": 40, "low": 2, "out": 0}


@dataclass(frozen=True)
class SeedCategory:
    slug: str
    name: str
    description: str
    sort_order: int


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
    category: str
    brand: str
    model: str
    description: str
    specifications: dict[str, str]
    variants: tuple[SeedVariant, ...]
    featured: bool = False
    warranty: str = "12-month warranty from 3 Sixty Technologies."


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


# Header.dc.html nav: Phones, Laptops, TVs & Audio, Home Appliances, Accessories, then "Brands"
# and "Deals" (not categories). Subtitles from the "Shop by Category" tiles of Main.dc.html.
CATEGORIES = (
    SeedCategory("phones", "Phones", "Smartphones & accessories", 1),
    SeedCategory("laptops", "Laptops", "For work, study & gaming", 2),
    SeedCategory("tvs-audio", "TVs & Audio", "TVs, soundbars & more", 3),
    SeedCategory("home-appliances", "Home Appliances", "For a smarter home", 4),
    SeedCategory("accessories", "Accessories", "Audio, chargers & more", 5),
)

BRANDS = (
    SeedBrand("samsung", "Samsung"),
    SeedBrand("apple", "Apple"),
    SeedBrand("tecno", "Tecno"),
    SeedBrand("infinix", "Infinix"),
    SeedBrand("xiaomi", "Xiaomi"),
    SeedBrand("hp", "HP"),
    SeedBrand("dell", "Dell"),
    SeedBrand("lenovo", "Lenovo"),
    SeedBrand("lg", "LG"),
    SeedBrand("hisense", "Hisense"),
    SeedBrand("jbl", "JBL"),
    SeedBrand("anker", "Anker"),
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


def _phone(screen: str, camera: str, battery: str, os: str) -> dict[str, str]:
    return {"Display": screen, "Main camera": camera, "Battery": battery, "Operating system": os}


def _laptop(cpu: str, screen: str, graphics: str, os: str = "Windows 11 Home") -> dict[str, str]:
    return {"Processor": cpu, "Display": screen, "Graphics": graphics, "Operating system": os}


PRODUCTS = (
    # Phones
    SeedProduct(
        "samsung-galaxy-a55-5g",
        "Samsung Galaxy A55 5G",
        "phones",
        "samsung",
        "SM-A556E",
        "A premium mid-range 5G phone with a bright Super AMOLED display, a 50 MP camera with "
        "night mode and an all-day battery.",
        _phone('6.6" Super AMOLED, 120 Hz', "50 MP + 12 MP + 5 MP", "5,000 mAh", "Android 14"),
        (
            _v(
                "SAM-A55-128-NVY",
                "8GB · 128GB · Awesome Navy",
                495_000,
                "best",
                storage="128 GB",
                ram="8 GB",
                colour="Awesome Navy",
            ),
            _v(
                "SAM-A55-256-ICE",
                "8GB · 256GB · Awesome Iceblue",
                560_000,
                "low",
                storage="256 GB",
                ram="8 GB",
                colour="Awesome Iceblue",
            ),
        ),
        featured=True,
    ),
    SeedProduct(
        "samsung-galaxy-a35-5g",
        "Samsung Galaxy A35 5G",
        "phones",
        "samsung",
        "SM-A356E",
        "Smooth 5G performance, a 50 MP OIS camera and a durable glass design.",
        _phone('6.6" Super AMOLED, 120 Hz', "50 MP + 8 MP + 5 MP", "5,000 mAh", "Android 14"),
        (
            _v(
                "SAM-A35-128-LIL",
                "8GB · 128GB · Awesome Lilac",
                450_000,
                compare=500_000,
                storage="128 GB",
                ram="8 GB",
                colour="Awesome Lilac",
            ),
        ),
    ),
    SeedProduct(
        "samsung-galaxy-s24",
        "Samsung Galaxy S24",
        "phones",
        "samsung",
        "SM-S921B",
        "Samsung's compact flagship with Galaxy AI, a ProVisual camera and seven years of updates.",
        _phone(
            '6.2" Dynamic AMOLED 2X, 120 Hz', "50 MP + 12 MP + 10 MP", "4,000 mAh", "Android 14"
        ),
        (
            _v(
                "SAM-S24-256-BLK",
                "8GB · 256GB · Onyx Black",
                1_220_000,
                storage="256 GB",
                ram="8 GB",
                colour="Onyx Black",
            ),
            _v(
                "SAM-S24-512-VIO",
                "8GB · 512GB · Cobalt Violet",
                1_380_000,
                "out",
                storage="512 GB",
                ram="8 GB",
                colour="Cobalt Violet",
            ),
        ),
        featured=True,
    ),
    SeedProduct(
        "samsung-galaxy-a15",
        "Samsung Galaxy A15",
        "phones",
        "samsung",
        "SM-A155F",
        "An affordable everyday phone with a large display and long battery life.",
        _phone('6.5" Super AMOLED, 90 Hz', "50 MP + 5 MP + 2 MP", "5,000 mAh", "Android 14"),
        (
            _v(
                "SAM-A15-128-BLU",
                "6GB · 128GB · Blue Black",
                320_000,
                storage="128 GB",
                ram="6 GB",
                colour="Blue Black",
            ),
        ),
    ),
    SeedProduct(
        "apple-iphone-15",
        "iPhone 15",
        "phones",
        "apple",
        "A3090",
        "Dynamic Island, a 48 MP main camera and USB-C in a colour-infused glass design.",
        _phone('6.1" Super Retina XDR', "48 MP + 12 MP", "Up to 20 h video", "iOS 17"),
        (
            _v(
                "APL-IP15-128-BLK",
                "128GB · Black",
                1_450_000,
                "best",
                storage="128 GB",
                colour="Black",
            ),
            _v(
                "APL-IP15-256-BLU",
                "256GB · Blue",
                1_650_000,
                "low",
                storage="256 GB",
                colour="Blue",
            ),
        ),
        featured=True,
    ),
    SeedProduct(
        "apple-iphone-13",
        "iPhone 13",
        "phones",
        "apple",
        "A2633",
        "A dependable iPhone with the A15 Bionic chip and a dual-camera system.",
        _phone('6.1" Super Retina XDR', "12 MP + 12 MP", "Up to 19 h video", "iOS 17"),
        (
            _v(
                "APL-IP13-128-MID",
                "128GB · Midnight",
                950_000,
                "low",
                storage="128 GB",
                colour="Midnight",
            ),
        ),
    ),
    SeedProduct(
        "tecno-spark-20",
        "Tecno Spark 20",
        "phones",
        "tecno",
        "KJ5",
        "A stylish budget phone with a 50 MP camera, dual speakers and fast charging.",
        _phone('6.56" IPS LCD, 90 Hz', "50 MP", "5,000 mAh", "Android 13"),
        (
            _v(
                "TEC-SPK20-128-BLK",
                "8GB · 128GB · Gravity Black",
                295_000,
                "best",
                storage="128 GB",
                ram="8 GB",
                colour="Gravity Black",
            ),
        ),
    ),
    SeedProduct(
        "tecno-camon-30",
        "Tecno Camon 30",
        "phones",
        "tecno",
        "CL6",
        "Portrait-focused cameras and a 120 Hz AMOLED display.",
        _phone('6.78" AMOLED, 120 Hz', "50 MP + 2 MP", "5,000 mAh", "Android 14"),
        (
            _v(
                "TEC-CAM30-256-WHT",
                "8GB · 256GB · Serenity White",
                340_000,
                storage="256 GB",
                ram="8 GB",
                colour="Serenity White",
            ),
        ),
    ),
    SeedProduct(
        "infinix-hot-40i",
        "Infinix Hot 40i",
        "phones",
        "infinix",
        "X6528B",
        "Big screen, big battery and a 50 MP camera at an entry-level price.",
        _phone('6.56" IPS LCD, 90 Hz', "50 MP", "5,000 mAh", "Android 13"),
        (
            _v(
                "INF-HOT40I-128-BLK",
                "4GB · 128GB · Starlit Black",
                185_000,
                compare=199_000,
                storage="128 GB",
                ram="4 GB",
                colour="Starlit Black",
            ),
        ),
    ),
    SeedProduct(
        "infinix-zero-30-5g",
        "Infinix Zero 30 5G",
        "phones",
        "infinix",
        "X6731",
        "A 4K selfie camera and a curved AMOLED display.",
        _phone('6.78" AMOLED, 144 Hz', "108 MP + 13 MP + 2 MP", "5,000 mAh", "Android 13"),
        (
            _v(
                "INF-ZERO30-256-GLD",
                "12GB · 256GB · Golden Hour",
                480_000,
                "out",
                storage="256 GB",
                ram="12 GB",
                colour="Golden Hour",
            ),
        ),
    ),
    SeedProduct(
        "xiaomi-redmi-note-13-pro",
        "Xiaomi Redmi Note 13 Pro",
        "phones",
        "xiaomi",
        "2312DRA50G",
        "A 200 MP camera and a 1.5K AMOLED display with 67 W fast charging.",
        _phone('6.67" AMOLED, 120 Hz', "200 MP + 8 MP + 2 MP", "5,100 mAh", "Android 13"),
        (
            _v(
                "XIA-RN13P-256-BLK",
                "8GB · 256GB · Midnight Black",
                420_000,
                compare=450_000,
                storage="256 GB",
                ram="8 GB",
                colour="Midnight Black",
            ),
        ),
    ),
    SeedProduct(
        "xiaomi-redmi-13c",
        "Xiaomi Redmi 13C",
        "phones",
        "xiaomi",
        "23100RN82L",
        "An easy first smartphone with a large display and a 50 MP camera.",
        _phone('6.74" IPS LCD, 90 Hz', "50 MP + 2 MP", "5,000 mAh", "Android 13"),
        (
            _v(
                "XIA-R13C-128-GRN",
                "4GB · 128GB · Clover Green",
                165_000,
                storage="128 GB",
                ram="4 GB",
                colour="Clover Green",
            ),
        ),
    ),
    # Laptops
    SeedProduct(
        "hp-pavilion-15",
        "HP Pavilion 15 Laptop",
        "laptops",
        "hp",
        "15-eg3000",
        "A thin and light laptop for work and study with a Full HD display and fast SSD.",
        _laptop("Intel Core i5-1335U", '15.6" Full HD IPS', "Intel Iris Xe"),
        (
            _v(
                "HP-PAV15-I5-512",
                "Intel i5 · 8GB · 512GB SSD",
                820_000,
                processor="Core i5",
                ram="8 GB",
                storage="512 GB SSD",
            ),
            _v(
                "HP-PAV15-I7-1TB",
                "Intel i7 · 16GB · 1TB SSD",
                1_090_000,
                "low",
                processor="Core i7",
                ram="16 GB",
                storage="1 TB SSD",
            ),
        ),
        featured=True,
    ),
    SeedProduct(
        "hp-250-g9",
        "HP 250 G9 Laptop",
        "laptops",
        "hp",
        "250 G9",
        "A reliable business laptop for everyday office work.",
        _laptop("Intel Core i3-1215U", '15.6" Full HD', "Intel UHD"),
        (
            _v(
                "HP-250G9-I3-256",
                "Intel i3 · 8GB · 256GB SSD",
                520_000,
                processor="Core i3",
                ram="8 GB",
                storage="256 GB SSD",
            ),
        ),
    ),
    SeedProduct(
        "dell-inspiron-15",
        "Dell Inspiron 15",
        "laptops",
        "dell",
        "3530",
        "Everyday performance with a narrow-border Full HD display.",
        _laptop("Intel Core i5-1335U", '15.6" Full HD, 120 Hz', "Intel Iris Xe"),
        (
            _v(
                "DEL-INS15-I5-512",
                "Intel i5 · 8GB · 512GB SSD",
                780_000,
                processor="Core i5",
                ram="8 GB",
                storage="512 GB SSD",
            ),
        ),
    ),
    SeedProduct(
        "dell-latitude-5440",
        "Dell Latitude 5440",
        "laptops",
        "dell",
        "5440",
        "A secure, durable business laptop with all-day battery life.",
        _laptop("Intel Core i7-1355U", '14" Full HD', "Intel Iris Xe", "Windows 11 Pro"),
        (
            _v(
                "DEL-LAT5440-I7-512",
                "Intel i7 · 16GB · 512GB SSD",
                1_350_000,
                processor="Core i7",
                ram="16 GB",
                storage="512 GB SSD",
            ),
        ),
    ),
    SeedProduct(
        "lenovo-ideapad-slim-3",
        "Lenovo IdeaPad Slim 3",
        "laptops",
        "lenovo",
        "15ABR8",
        "A slim laptop with AMD Ryzen performance for study and entertainment.",
        _laptop("AMD Ryzen 5 7530U", '15.6" Full HD IPS', "AMD Radeon"),
        (
            _v(
                "LEN-IPS3-R5-512",
                "Ryzen 5 · 8GB · 512GB SSD",
                650_000,
                compare=699_000,
                processor="Ryzen 5",
                ram="8 GB",
                storage="512 GB SSD",
            ),
        ),
    ),
    SeedProduct(
        "lenovo-thinkpad-e14",
        "Lenovo ThinkPad E14",
        "laptops",
        "lenovo",
        "E14 Gen 5",
        "The ThinkPad keyboard and build quality for small businesses.",
        _laptop("Intel Core i5-1335U", '14" WUXGA IPS', "Intel Iris Xe", "Windows 11 Pro"),
        (
            _v(
                "LEN-TPE14-I5-512",
                "Intel i5 · 16GB · 512GB SSD",
                1_050_000,
                "low",
                processor="Core i5",
                ram="16 GB",
                storage="512 GB SSD",
            ),
        ),
    ),
    SeedProduct(
        "apple-macbook-air-13-m2",
        'MacBook Air 13" M2',
        "laptops",
        "apple",
        "MLY33",
        "Strikingly thin and fast, with the M2 chip and up to 18 hours of battery life.",
        _laptop("Apple M2", '13.6" Liquid Retina', "8-core GPU", "macOS"),
        (
            _v(
                "APL-MBA13-M2-256",
                "M2 · 8GB · 256GB SSD",
                1_550_000,
                processor="Apple M2",
                ram="8 GB",
                storage="256 GB SSD",
            ),
        ),
        featured=True,
    ),
    SeedProduct(
        "hp-victus-15",
        "HP Victus 15 Gaming Laptop",
        "laptops",
        "hp",
        "15-fa1000",
        "A gaming laptop with NVIDIA GeForce RTX graphics and a 144 Hz display.",
        _laptop("Intel Core i5-12450H", '15.6" Full HD, 144 Hz', "NVIDIA GeForce RTX 3050"),
        (
            _v(
                "HP-VIC15-I5-512",
                "Intel i5 · 16GB · 512GB SSD",
                1_250_000,
                "out",
                processor="Core i5",
                ram="16 GB",
                storage="512 GB SSD",
            ),
        ),
    ),
    # TVs & Audio
    SeedProduct(
        "lg-55-4k-smart-tv",
        'LG 55" 4K Smart TV',
        "tvs-audio",
        "lg",
        "55UR78006LK",
        "UHD picture with ThinQ AI, webOS apps and HDR10 Pro.",
        {
            "Screen size": '55"',
            "Resolution": "4K UHD",
            "Smart platform": "webOS",
            "HDMI ports": "3",
        },
        (_v("LG-55UR78-55", '55"', 890_000, screen_size='55"'),),
        featured=True,
    ),
    SeedProduct(
        "hisense-43-smart-tv",
        'Hisense 43" Smart TV',
        "tvs-audio",
        "hisense",
        "43A4K",
        "A Full HD smart TV with built-in apps and Dolby Audio.",
        {
            "Screen size": '43"',
            "Resolution": "Full HD",
            "Smart platform": "VIDAA",
            "HDMI ports": "2",
        },
        (_v("HIS-43A4K-43", '43"', 520_000, "best", screen_size='43"'),),
    ),
    SeedProduct(
        "samsung-65-crystal-uhd-tv",
        'Samsung 65" Crystal UHD TV',
        "tvs-audio",
        "samsung",
        "UA65CU7000",
        "Crystal Processor 4K for vivid colour on a big screen.",
        {
            "Screen size": '65"',
            "Resolution": "4K UHD",
            "Smart platform": "Tizen",
            "HDMI ports": "3",
        },
        (_v("SAM-CU7000-65", '65"', 1_150_000, compare=1_250_000, screen_size='65"'),),
    ),
    SeedProduct(
        "lg-32-hd-smart-tv",
        'LG 32" HD Smart TV',
        "tvs-audio",
        "lg",
        "32LQ630B6LA",
        "A compact smart TV for bedrooms and small living rooms.",
        {"Screen size": '32"', "Resolution": "HD", "Smart platform": "webOS", "HDMI ports": "2"},
        (_v("LG-32LQ63-32", '32"', 280_000, screen_size='32"'),),
    ),
    SeedProduct(
        "hisense-hs218-soundbar",
        "Hisense HS218 Soundbar",
        "tvs-audio",
        "hisense",
        "HS218",
        "A 2.1-channel soundbar with a built-in subwoofer and Bluetooth.",
        {"Channels": "2.1", "Power": "200 W", "Connectivity": "Bluetooth, HDMI ARC, optical"},
        (_v("HIS-HS218", "Black", 145_000, colour="Black"),),
    ),
    SeedProduct(
        "jbl-flip-6",
        "JBL Flip 6 Bluetooth Speaker",
        "tvs-audio",
        "jbl",
        "Flip 6",
        "Bold JBL Pro Sound in a waterproof, dustproof portable speaker.",
        {"Battery": "Up to 12 h", "Water resistance": "IP67", "Connectivity": "Bluetooth 5.1"},
        (
            _v("JBL-FLIP6-BLK", "Black", 180_000, compare=200_000, colour="Black"),
            _v("JBL-FLIP6-BLU", "Blue", 180_000, "low", compare=200_000, colour="Blue"),
        ),
        featured=True,
    ),
    SeedProduct(
        "jbl-charge-5",
        "JBL Charge 5 Bluetooth Speaker",
        "tvs-audio",
        "jbl",
        "Charge 5",
        "Powerful sound and a built-in power bank to charge your phone.",
        {"Battery": "Up to 20 h", "Water resistance": "IP67", "Connectivity": "Bluetooth 5.1"},
        (_v("JBL-CHG5-BLK", "Black", 245_000, colour="Black"),),
    ),
    SeedProduct(
        "samsung-hw-b550-soundbar",
        "Samsung HW-B550 Soundbar",
        "tvs-audio",
        "samsung",
        "HW-B550",
        "Dolby Audio and DTS Virtual:X with a wireless subwoofer.",
        {"Channels": "2.1", "Power": "410 W", "Connectivity": "Bluetooth, HDMI, optical"},
        (_v("SAM-HWB550", "Black", 310_000, "out", colour="Black"),),
    ),
    # Home Appliances
    SeedProduct(
        "hisense-205l-refrigerator",
        "Hisense 205 L Refrigerator",
        "home-appliances",
        "hisense",
        "RD-27DR4SA",
        "A double-door refrigerator with low energy use for small families.",
        {"Capacity": "205 L", "Type": "Double door", "Energy rating": "A+"},
        (_v("HIS-RD27-205", "Silver", 395_000, colour="Silver"),),
    ),
    SeedProduct(
        "lg-8kg-front-load-washer",
        "LG 8 kg Front Load Washing Machine",
        "home-appliances",
        "lg",
        "F4R3TYG6P",
        "AI Direct Drive washing with steam and an inverter motor.",
        {"Capacity": "8 kg", "Type": "Front load", "Spin speed": "1,400 rpm"},
        (_v("LG-F4R3-8KG", "White", 690_000, colour="White"),),
    ),
    SeedProduct(
        "samsung-20l-microwave",
        "Samsung 20 L Solo Microwave",
        "home-appliances",
        "samsung",
        "MS20A3010AL",
        "A compact microwave with a ceramic enamel interior that is easy to clean.",
        {"Capacity": "20 L", "Power": "700 W", "Type": "Solo"},
        (_v("SAM-MS20-20L", "Black", 135_000, compare=150_000, colour="Black"),),
    ),
    SeedProduct(
        "hisense-1-5hp-split-ac",
        "Hisense 1.5 HP Split Air Conditioner",
        "home-appliances",
        "hisense",
        "AS-12TR4",
        "Quiet inverter cooling for bedrooms and offices.",
        {"Capacity": "12,000 BTU", "Type": "Split, inverter", "Energy rating": "A++"},
        (_v("HIS-AS12-15HP", "White", 620_000, "low", colour="White"),),
    ),
    SeedProduct(
        "lg-inverter-refrigerator-420l",
        "LG 420 L Inverter Refrigerator",
        "home-appliances",
        "lg",
        "GN-B422SQCL",
        "Linear cooling and DoorCooling+ keep food fresh for longer.",
        {"Capacity": "420 L", "Type": "Top freezer", "Energy rating": "A++"},
        (_v("LG-GNB422-420L", "Platinum Silver", 1_180_000, colour="Platinum Silver"),),
    ),
    SeedProduct(
        "hisense-5l-air-fryer",
        "Hisense 5 L Air Fryer",
        "home-appliances",
        "hisense",
        "HAF1500D",
        "Crispy results with little or no oil, with a digital touch panel.",
        {"Capacity": "5 L", "Power": "1,500 W", "Controls": "Digital touch"},
        (_v("HIS-HAF1500-5L", "Black", 95_000, colour="Black"),),
    ),
    # Accessories
    SeedProduct(
        "anker-powercore-20000",
        "Anker Power Bank 20,000mAh",
        "accessories",
        "anker",
        "A1384",
        "High-capacity portable charger with USB-C Power Delivery.",
        {"Capacity": "20,000 mAh", "Output": "20 W USB-C PD", "Ports": "USB-C, USB-A"},
        (_v("ANK-PC20K-BLK", "Black", 85_000, "best", colour="Black"),),
    ),
    SeedProduct(
        "anker-nano-20w-charger",
        "Anker Nano 20W USB-C Charger",
        "accessories",
        "anker",
        "A2633",
        "A compact fast charger for phones and earbuds.",
        {"Output": "20 W", "Port": "USB-C", "Plug": "UK type G"},
        (_v("ANK-NANO20-WHT", "White", 28_000, colour="White"),),
    ),
    SeedProduct(
        "apple-airpods-pro-2",
        "AirPods Pro (2nd generation)",
        "accessories",
        "apple",
        "MTJV3",
        "Active noise cancellation, Adaptive Audio and a USB-C MagSafe case.",
        {
            "Battery": "Up to 6 h (30 h with case)",
            "Noise cancellation": "Active",
            "Charging": "USB-C, MagSafe",
        },
        (_v("APL-APP2-WHT", "White", 395_000, colour="White"),),
    ),
    SeedProduct(
        "samsung-galaxy-buds-fe",
        "Samsung Galaxy Buds FE",
        "accessories",
        "samsung",
        "SM-R400N",
        "Comfortable earbuds with active noise cancelling and rich bass.",
        {
            "Battery": "Up to 6 h (21 h with case)",
            "Noise cancellation": "Active",
            "Connectivity": "Bluetooth 5.2",
        },
        (_v("SAM-BUDSFE-GRY", "Graphite", 115_000, colour="Graphite"),),
    ),
    SeedProduct(
        "jbl-tune-520bt",
        "JBL Tune 520BT Headphones",
        "accessories",
        "jbl",
        "Tune 520BT",
        "Lightweight wireless on-ear headphones with JBL Pure Bass.",
        {"Battery": "Up to 57 h", "Connectivity": "Bluetooth 5.3", "Weight": "157 g"},
        (_v("JBL-T520-BLK", "Black", 65_000, compare=75_000, colour="Black"),),
    ),
    SeedProduct(
        "xiaomi-redmi-buds-5",
        "Xiaomi Redmi Buds 5",
        "accessories",
        "xiaomi",
        "M2316E1",
        "Affordable earbuds with 46 dB noise cancellation.",
        {
            "Battery": "Up to 10 h (40 h with case)",
            "Noise cancellation": "Active",
            "Connectivity": "Bluetooth 5.3",
        },
        (_v("XIA-RBUDS5-WHT", "Fantasy White", 45_000, colour="Fantasy White"),),
    ),
    SeedProduct(
        "anker-usb-c-cable-2m",
        "Anker USB-C to USB-C Cable 2 m",
        "accessories",
        "anker",
        "A81F6",
        "A braided, durable cable for fast charging and data transfer.",
        {"Length": "2 m", "Power": "100 W", "Connectors": "USB-C to USB-C"},
        (_v("ANK-USBC-2M", "Black", 15_000, colour="Black"),),
    ),
    SeedProduct(
        "samsung-galaxy-watch-6",
        "Samsung Galaxy Watch 6",
        "accessories",
        "samsung",
        "SM-R930",
        "Advanced health tracking and sleep coaching on a sapphire crystal display.",
        {"Display": '1.3" Super AMOLED', "Battery": "Up to 40 h", "Water resistance": "5ATM"},
        (
            _v(
                "SAM-GW6-40-GRA",
                "40 mm · Graphite",
                480_000,
                "low",
                case_size="40 mm",
                colour="Graphite",
            ),
        ),
    ),
)

# The first banner is the Main.dc.html hero. The other two reuse the hero's trust points; the
# design has a single hero; only the first has an overline. Kinyarwanda text is draft test data,
# not approved copy.
BANNERS = (
    SeedBanner(
        title_en="Power Your World With the Latest Tech",
        title_rw="Ikoranabuhanga rigezweho ku buzima bwawe",
        subtitle_en=(
            "Smartphones, laptops, TVs, home appliances and accessories from trusted brands — "
            "delivered fast across Kigali and all of Rwanda."
        ),
        subtitle_rw=(
            "Telefoni, mudasobwa, televiziyo, ibikoresho byo mu rugo n'ibindi biva mu bakora "
            "bizewe, bikugezwaho vuba i Kigali no mu Rwanda hose."
        ),
        cta_label_en="Shop Now",
        cta_label_rw="Gura ubu",
        cta_url="/category/phones",
        position=0,
        overline_en="Latest electronics, better everyday life",
        overline_rw="Ikoranabuhanga rigezweho, ubuzima bwiza",
    ),
    SeedBanner(
        title_en="Genuine Products With Warranty",
        title_rw="Ibicuruzwa by'umwimerere bifite garanti",
        subtitle_en="Laptops for work, study and gaming from HP, Dell, Lenovo and Apple.",
        subtitle_rw="Mudasobwa zo gukoresha mu kazi, kwiga no gukina za HP, Dell, Lenovo na Apple.",
        cta_label_en="Shop Laptops",
        cta_label_rw="Reba mudasobwa",
        cta_url="/category/laptops",
        position=1,
    ),
    SeedBanner(
        title_en="Fast & Reliable Delivery",
        title_rw="Kugeza ibicuruzwa vuba kandi neza",
        subtitle_en="TVs, soundbars and speakers delivered to your door in Kigali.",
        subtitle_rw="Televiziyo n'indangururamajwi bikugezwaho mu rugo i Kigali.",
        cta_label_en="Shop TVs & Audio",
        cta_label_rw="Reba televiziyo",
        cta_url="/category/tvs-audio",
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

# Cash on delivery throughout. Delivered orders give `sort_by=bestselling` its data.
ORDERS = (
    SeedOrder("aline.uwase", (("APL-IP15-128-BLK", 1), ("ANK-PC20K-BLK", 1)), "delivered"),
    SeedOrder("jean.habimana", (("TEC-SPK20-128-BLK", 2),), "delivered"),
    SeedOrder("grace.mukamana", (("HIS-43A4K-43", 1),), "delivered"),
    SeedOrder("eric.niyonzima", (("SAM-A55-128-NVY", 1), ("ANK-PC20K-BLK", 1)), "delivered"),
    SeedOrder("diane.ingabire", (("TEC-SPK20-128-BLK", 1), ("ANK-NANO20-WHT", 2)), "delivered"),
    SeedOrder("aline.uwase", (("HIS-43A4K-43", 1),), "delivered"),
    SeedOrder("jean.habimana", (("APL-IP15-128-BLK", 1),), "delivered"),
    SeedOrder("grace.mukamana", (("ANK-PC20K-BLK", 2), ("XIA-RBUDS5-WHT", 1)), "delivered"),
    SeedOrder("eric.niyonzima", (("JBL-FLIP6-BLK", 1),), "dispatched"),
    SeedOrder("diane.ingabire", (("HP-PAV15-I5-512", 1),), "dispatched"),
    SeedOrder("aline.uwase", (("SAM-MS20-20L", 1),), "processing"),
    SeedOrder("jean.habimana", (("DEL-INS15-I5-512", 1),), "confirmed"),
    SeedOrder("grace.mukamana", (("SAM-A15-128-BLU", 1),), "received"),
    SeedOrder("eric.niyonzima", (("APL-APP2-WHT", 1),), "received"),
    SeedOrder(
        "diane.ingabire",
        (("JBL-T520-BLK", 1),),
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
        "APL-IP15-128-BLK",
        5,
        "approved",
        "Fast and the camera is excellent",
        "Delivered in Kicukiro the next morning. Battery lasts a full day.",
    ),
    SeedReview(1, "ANK-PC20K-BLK", 4, "approved", "Charges my phone four times"),
    SeedReview(
        2,
        "TEC-SPK20-128-BLK",
        4,
        "approved",
        "Good value",
        "Big screen and good battery for the price. The camera is average in low light.",
    ),
    SeedReview(3, "HIS-43A4K-43", 5, "approved", "Sharp picture", "Easy to set up with Netflix."),
    SeedReview(4, "SAM-A55-128-NVY", 4, "approved", None, "Smooth screen, a little heavy."),
    SeedReview(4, "ANK-PC20K-BLK", 5, "approved", "Reliable"),
    SeedReview(5, "TEC-SPK20-128-BLK", 3, "approved", "Fine for everyday use"),
    SeedReview(
        5, "ANK-NANO20-WHT", 5, "pending", "Small and quick", "Charges my iPhone to half fast."
    ),
    SeedReview(6, "HIS-43A4K-43", 4, "approved", "Good TV for the bedroom"),
    SeedReview(7, "APL-IP15-128-BLK", 5, "approved", "Worth it", "Original, sealed box."),
    SeedReview(
        8,
        "ANK-PC20K-BLK",
        2,
        "rejected",
        "Call me for cheaper prices",
        "WhatsApp 0780000000 for a better deal.",
        reason="Advertising and a phone number",
    ),
    SeedReview(8, "XIA-RBUDS5-WHT", 4, "pending", "Good sound", None),
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

3 Sixty Technologies sells original phones, laptops, TVs and accessories in Rwanda, with
warranty and delivery to every district.

## What we promise

- Genuine products from authorised suppliers.
- Clear prices in Rwandan francs, with VAT included.
- Help before and after you buy, on WhatsApp, by phone or in our store.""",
    ),
    SeedPage(
        "about-us",
        "rw",
        "Abo turi bo",
        f"""{DRAFT_RW}

3 Sixty Technologies icuruza telefoni, mudasobwa, televiziyo n'ibikoresho by'umwimerere mu
Rwanda, bifite garanti kandi tukabigeza mu turere twose.

## Ibyo tubasezeranya

- Ibicuruzwa by'umwimerere biva ku batanga bemewe.
- Ibiciro bigaragara neza mu mafaranga y'u Rwanda, TVA irimo.
- Ubufasha mbere na nyuma yo kugura, kuri WhatsApp, kuri telefoni cyangwa mu iduka.""",
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

By ordering from 3 Sixty Technologies you agree to these terms.

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

Iyo utumije kuri 3 Sixty Technologies uba wemeye aya mabwiriza.

## Amatumiza n'ibiciro

- Ibiciro biri mu mafaranga y'u Rwanda kandi birimo TVA.
- Itumiza ryemezwa iyo turyakiriye.
- Dushobora guhagarika itumiza ridashobora kubahirizwa tugasubiza amafaranga yishyuwe.""",
    ),
)

# Store contact for development (module 19): sample values, set only while the setting is unset;
# the cleanup removes them only while they still hold these values.
CONTACT = (
    ("store.name", "3 Sixty Technologies"),
    ("contact.phone", "+250 788 123 456"),
    ("contact.whatsapp", "+250 788 123 456"),
    ("contact.email", "info@3sixtytech.rw"),
    ("contact.address", "KN 5 Ave, Kigali, Rwanda"),
    ("contact.hours", "Mon – Sat: 8:00 AM – 6:00 PM"),
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
)
