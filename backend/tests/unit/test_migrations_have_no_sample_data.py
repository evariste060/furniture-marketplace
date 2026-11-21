"""No migration inserts sample content (checkpoint 1b, 2026-10-26).

Development data comes from the seed commands, never from migrations, so it cannot reach staging
or production unnoticed. A migration may only insert reference data (roles and permissions);
none does today, so any insert must be added to ALLOWED_INSERTS with a reason.
"""

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
# migration file name -> why its insert is reference data
ALLOWED_INSERTS: dict[str, str] = {
    "b3e8f1a6c4d2_brand_categories.py": (
        "INSERT ... SELECT backfill: each brand's existing menu categories become its categories "
        "(ADR-012 decision 9); it copies rows already in the database and adds no content."
    ),
}
INSERT = re.compile(r"\bbulk_insert\b|\bINSERT\s+INTO\b|\.insert\(\)", re.IGNORECASE)


def test_the_scan_sees_every_migration():
    files = sorted(VERSIONS.glob("*.py"))
    assert len(files) >= 20
    assert any(f.name.startswith("f8c3e7a9b4d5") for f in files)  # banners: no sample banners


def test_no_migration_inserts_rows():
    offenders = {
        path.name: [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if INSERT.search(line)
        ]
        for path in sorted(VERSIONS.glob("*.py"))
        if path.name not in ALLOWED_INSERTS
    }
    assert {name: lines for name, lines in offenders.items() if lines} == {}
