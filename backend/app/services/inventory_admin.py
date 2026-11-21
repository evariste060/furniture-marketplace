"""Staff inventory operations behind the HTTP API (approved 2026-10-23: read by administrator,
sales and operations; adjust by administrator and sales).

Maps inventory rule errors to HTTP responses and commits each request's change together with its
audit record. The stock rules themselves live in app.services.inventory.
"""

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.request_context import RequestContext
from app.models import Brand, Category, Product, ProductVariant
from app.models.identity import User
from app.repositories.category_tree import category_visible
from app.schemas.inventory import (
    InventoryListItem,
    InventoryResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
    StockMovementResponse,
)
from app.schemas.pagination import page_offset
from app.services import inventory

SKU_NOT_FOUND = "No SKU with this code."


def _variant_by_sku(db: Session, sku: str) -> ProductVariant:
    variant = db.scalar(select(ProductVariant).where(func.lower(ProductVariant.sku) == sku.lower()))
    if variant is None:
        raise NotFound(SKU_NOT_FOUND, code="sku_not_found")
    return variant


def _sellable():
    """Variant active, product active, category visible (it and its main category active) and
    brand active (or none)."""
    return and_(
        ProductVariant.is_active.is_(True),
        Product.status == "active",
        Category.is_active.is_(True),
        category_visible(Product.category_id),
        or_(Product.brand_id.is_(None), Brand.is_active.is_(True)),
    )


def stock_list_query(variant_ids: list[uuid.UUID] | None = None):
    """One row per SKU with the shared stock figures (app.services.inventory.stock_figures)
    plus the product fields of the staff views. GET /inventory, GET /inventory/{sku} and the
    stock report (module 18, app.services.report_service) all read from this query, so they
    cannot disagree."""
    figures, columns = inventory.stock_figures(variant_ids)
    query = (
        figures.add_columns(
            ProductVariant.sku.label("sku"),
            ProductVariant.name.label("variant_name"),
            ProductVariant.low_stock_threshold.label("low_stock_threshold"),
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            _sellable().label("is_sellable"),
        )
        .join(Product, Product.id == ProductVariant.product_id)
        .join(Category, Category.id == Product.category_id)
        .outerjoin(Brand, Brand.id == Product.brand_id)
    )
    return query, columns


def _inventory_response(db: Session, variant: ProductVariant) -> InventoryResponse:
    query, _ = stock_list_query([variant.id])
    row = db.execute(query.where(ProductVariant.id == variant.id)).mappings().one()
    return InventoryResponse.model_validate(dict(row))


def _like(text: str) -> str:
    return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


class InventoryAdminService:
    @staticmethod
    def get(db: Session, sku: str) -> InventoryResponse:
        return _inventory_response(db, _variant_by_sku(db, sku))

    @staticmethod
    def list_stock(
        db: Session, *, low_stock: bool | None, q: str | None, page: int, size: int
    ) -> tuple[list[InventoryListItem], int]:
        """Every SKU (active or not), ordered by SKU. low_stock: true keeps low-stock SKUs,
        false the others, omitted all. q: case-insensitive substring of the SKU, variant name
        or product name. Two queries per page, whatever its size."""
        query, columns = stock_list_query()
        if low_stock is not None:
            query = query.where(columns.is_low_stock if low_stock else ~columns.is_low_stock)
        if q:
            pattern = _like(q)
            query = query.where(
                or_(
                    ProductVariant.sku.ilike(pattern, escape="!"),
                    ProductVariant.name.ilike(pattern, escape="!"),
                    Product.name.ilike(pattern, escape="!"),
                )
            )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.execute(
            query.order_by(ProductVariant.sku.asc()).offset(page_offset(page, size)).limit(size)
        ).mappings()
        return [InventoryListItem.model_validate(dict(row)) for row in rows], total

    @staticmethod
    def adjust(
        db: Session,
        actor: User,
        sku: str,
        req: StockAdjustmentRequest,
        idempotency_key: str,
        ctx: RequestContext,
    ) -> StockAdjustmentResponse:
        variant = _variant_by_sku(db, sku)
        try:
            result = inventory.adjust_stock(
                db,
                variant_id=variant.id,
                quantity_delta=req.quantity_delta,
                reason=req.reason,
                idempotency_key=idempotency_key,
                actor=actor,
                ctx=ctx,
                note=req.note,
            )
            db.commit()
        except inventory.InsufficientStock as exc:
            db.rollback()
            raise Conflict(
                (
                    "Insufficient stock: the change would leave less stock than is reserved, "
                    f"committed or unavailable (removable now: {exc.available})."
                ),
                code="insufficient_stock",
            ) from None
        except inventory.IdempotencyConflict as exc:
            db.rollback()
            raise Conflict(str(exc), code="idempotency_conflict") from None
        movement = result.movement
        return StockAdjustmentResponse(
            replayed=result.replayed,
            movement=StockMovementResponse(
                id=movement.id,
                reason=movement.reason,
                quantity_delta=movement.quantity_delta,
                note=movement.note,
                created_at=movement.created_at,
            ),
            inventory=_inventory_response(db, variant),
        )
