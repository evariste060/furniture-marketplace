"""Settings (module 12; plan §5; RE-026 B1, B6). Rules are in app.services.settings_service.
Module 12 manages delivery.free_delivery_threshold; module 16 the seller details printed on
invoices (seller.legal_name, seller.tin, seller.address); module 19 the public store contact and
announcement bar, served without signing in by GET /settings."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1.responses import FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.settings import (
    PublicSettingsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/staff/settings", tags=["Staff Settings"])
public_router = APIRouter(prefix="/settings", tags=["Storefront Content"])
PUBLIC_CACHE = "public, max-age=60"

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
SettingsReader = Annotated[User, Depends(require_permission(Permission.SETTINGS_READ))]
SettingsManager = Annotated[User, Depends(require_permission(Permission.SETTINGS_MANAGE))]
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}


@public_router.get(
    "",
    response_model=PublicSettingsResponse,
    summary="Store contact and announcement",
    description=(
        "Public (module 19). The store name, phone, WhatsApp number, email, address and opening "
        "hours, and the announcement bar message while it is switched on. Unset values are null. "
        "No other setting is ever served here. Cached for 60 seconds."
    ),
)
def read_public_settings(response: Response, db: Db) -> PublicSettingsResponse:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return SettingsService.read_public(db)


@router.get(
    "",
    response_model=SettingsResponse,
    summary="Read settings",
    description=(
        "Requires 'settings:read' (administrator). Every setting this API manages; "
        "a setting never set has value null."
    ),
    responses=GUARDED,
)
def read_settings(_: SettingsReader, db: Db) -> SettingsResponse:
    return SettingsService.read(db)


@router.patch(
    "",
    response_model=SettingsResponse,
    summary="Change settings",
    description=(
        "Requires 'settings:manage' (administrator). Send only the keys to change, e.g. "
        '`{"delivery.free_delivery_threshold": 200000}` (whole RWF, 0 to the largest storable '
        "amount), or the seller details printed on invoices (`seller.legal_name`, "
        "`seller.tin`, `seller.address`: text without surrounding spaces or control characters; "
        "an invoice is never issued while any of them is unset), or the public store contact "
        "(`store.name`; `contact.phone` and `contact.whatsapp` in international form such as "
        "'+250 788 123 456'; `contact.email`; `contact.address`; `contact.hours`) and the "
        "announcement bar (`announcement.enabled`, `announcement.text_en`, "
        "`announcement.text_rw`; switching it on needs both messages). Unknown keys, null and "
        "values of the wrong type or shape are refused (422). Audited as 'settings.update' "
        "with the old and new values; a request that changes nothing is not audited."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def update_settings(
    req: SettingsUpdateRequest, current_user: SettingsManager, db: Db, ctx: Ctx
) -> SettingsResponse:
    return SettingsService.update(db, current_user, req.changes(), ctx)
