"""Development seed data must never reach production (checkpoint 2, 2026-10-26).

The development catalogue seed (scripts/seed_development_catalogue.py) marks every variant it
creates with a SKU starting with DEV-. With APP_ENV=production such a SKU is logged as an error at
startup, and GET /health reports checks.catalogue as degraded for as long as one exists. In
development and staging seed data is expected, so the check reports ok without a query.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ProductVariant
from app.schemas.health import CheckStatus

DEV_SKU_PREFIX = "DEV-"
logger = logging.getLogger("app.dev_data_guard")


def dev_sku_count(db: Session) -> int:
    """Variants whose SKU starts with DEV- (ignoring case, as SKUs are unique ignoring case)."""
    pattern = DEV_SKU_PREFIX.lower() + "%"
    return (
        db.scalar(
            select(func.count(ProductVariant.id)).where(
                func.lower(ProductVariant.sku).like(pattern)
            )
        )
        or 0
    )


def catalogue_status(db: Session) -> CheckStatus:
    if get_settings().app_env != "production":
        return "ok"
    count = dev_sku_count(db)
    if count:
        logger.error(
            "Production catalogue contains %d development seed SKU(s) (prefix %s); remove them",
            count,
            DEV_SKU_PREFIX,
        )
        return "degraded"
    return "ok"


def check_at_startup() -> None:
    """Log an error at startup when production holds seed data. Never stops the API."""
    if get_settings().app_env != "production":
        return
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            catalogue_status(db)
    except Exception as exc:  # noqa: BLE001 - a startup check must not stop the API
        logger.warning("Development seed check skipped at startup: %s", type(exc).__name__)
