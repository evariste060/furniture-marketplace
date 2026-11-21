"""Delivery zones (module 12; RE-026 B1, B6; TC-17). Rules are in app.services.delivery_service.

Public: GET /delivery/zones. Staff: GET /staff/delivery/zones ('delivery:read': administrator,
management); POST and PATCH ('delivery:manage': administrator only).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.delivery import (
    DeliveryZoneCreateRequest,
    DeliveryZoneUpdateRequest,
    PublicDeliveryZonesResponse,
    StaffDeliveryZone,
    StaffDeliveryZonesResponse,
)
from app.services.delivery_service import DeliveryService

public_router = APIRouter(prefix="/delivery", tags=["Delivery"])
staff_router = APIRouter(prefix="/staff/delivery", tags=["Staff Delivery"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
DeliveryReader = Annotated[User, Depends(require_permission(Permission.DELIVERY_READ))]
DeliveryManager = Annotated[User, Depends(require_permission(Permission.DELIVERY_MANAGE))]

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
ZONE_404: ResponseMap = {404: {**ERR, "description": "delivery_zone_not_found"}}
SAVE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "zone_code_taken or zone_district_taken: another zone has this code or "
        "district; zone_fee_missing: an active zone needs a fee; fee_change_conflict: a "
        "concurrent fee change won, try again",
    }
}
MANAGE_NOTE = "Requires 'delivery:manage' (administrator)."


@public_router.get(
    "/zones",
    response_model=PublicDeliveryZonesResponse,
    summary="Delivery zones, fees and the free-delivery threshold",
    description=(
        "Active zones that have a current fee, in display order, with cash-on-delivery "
        "availability, and the free-delivery threshold (null while not configured). Delivery is "
        "free when the merchandise subtotal after discount is at least the threshold. Fees are "
        "whole RWF, VAT-inclusive. No authentication."
    ),
)
def public_zones(db: Db) -> PublicDeliveryZonesResponse:
    return DeliveryService.public_zones(db)


@staff_router.get(
    "/zones",
    response_model=StaffDeliveryZonesResponse,
    summary="All delivery zones with fee history",
    description=(
        "Requires 'delivery:read' (administrator, operations, management). Includes inactive zones."
    ),
    responses=GUARDED,
)
def staff_zones(_: DeliveryReader, db: Db) -> StaffDeliveryZonesResponse:
    return DeliveryService.staff_zones(db)


@staff_router.post(
    "/zones",
    response_model=StaffDeliveryZone,
    status_code=status.HTTP_201_CREATED,
    summary="Create a delivery zone",
    description=(
        f"{MANAGE_NOTE} One zone per district (Gasabo, Kicukiro, Nyarugenge); the code and "
        "district cannot be changed later. `fee` becomes the zone's first fee rule. Audited as "
        "'delivery.zone_create'."
    ),
    responses={**GUARDED, **SAVE_409, **VALIDATION_422},
)
def create_zone(
    req: DeliveryZoneCreateRequest, current_user: DeliveryManager, db: Db, ctx: Ctx
) -> StaffDeliveryZone:
    return DeliveryService.create_zone(db, current_user, req, ctx)


@staff_router.patch(
    "/zones/{zone_id}",
    response_model=StaffDeliveryZone,
    summary="Update a delivery zone or change its fee",
    description=(
        f"{MANAGE_NOTE} Partial update of name, fee, cod_available, sort_order and is_active. "
        "A new fee closes the current fee rule and starts a new one in the same transaction, "
        "so the history is kept. Audited as 'delivery.zone_update' with the old and new values; "
        "a request that changes nothing is not audited."
    ),
    responses={**GUARDED, **ZONE_404, **SAVE_409, **VALIDATION_422},
)
def update_zone(
    zone_id: uuid.UUID,
    req: DeliveryZoneUpdateRequest,
    current_user: DeliveryManager,
    db: Db,
    ctx: Ctx,
) -> StaffDeliveryZone:
    return DeliveryService.update_zone(db, current_user, zone_id, req, ctx)
