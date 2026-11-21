import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import text

from app.db.session import engine

with engine.connect() as connection:
    assert connection.scalar(text("SELECT 1")) == 1
    print("Database connection: PASS")
engine.dispose()
