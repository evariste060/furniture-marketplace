"""Technical services (ADR-013, SC-02, approved 2026-11-17). Rules are in
app.services.technical_services.

Public: GET /services, GET /services/{slug} and POST /services/{slug}/requests (rate limited,
with a honeypot field). Staff: /staff/services (read: 'services:read', changes:
'services:manage') and /staff/service-requests (the same permissions).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.image_admin import TOO_LARGE_413, UPLOAD_422
from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.rate_limit import LoginRateLimiter, get_service_request_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.integrations.media import MediaStorage, get_media_storage
from app.models.identity import User
from app.models.services import ServiceCategory, ServiceRequest
from app.schemas.images import PublicImage
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.services import (
    Locale,
    PublicService,
    PublicServiceItem,
    PublicServiceWithItems,
    RequestStatus,
    ServiceCreateRequest,
    ServiceItemCreateRequest,
    ServiceItemOrderRequest,
    ServiceItemUpdateRequest,
    ServiceOrderRequest,
    ServiceRef,
    ServiceRequestCreate,
    ServiceRequestCreated,
    ServiceRequestUpdate,
    ServiceUpdateRequest,
    StaffRef,
    StaffService,
    StaffServiceItem,
    StaffServiceRequest,
)
from app.services.image_admin import processed_upload, read_upload
from app.services.media_registry import public_image
from app.services.technical_services import (
    PublicServices,
    RequestFilters,
    ServiceAdmin,
    ServiceRequestAdmin,
    localized,
    request_counts,
)

public_router = APIRouter(prefix="/services", tags=["Storefront Services"])
staff_router = APIRouter(prefix="/staff", tags=["Staff Services"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Storage = Annotated[MediaStorage, Depends(get_media_storage)]
Reader = Annotated[User, Depends(require_permission(Permission.SERVICES_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.SERVICES_MANAGE))]
ImageFile = Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")]
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
SERVICE_404: ResponseMap = {404: {**ERR, "description": "service_not_found"}}
ITEM_404: ResponseMap = {404: {**ERR, "description": "service_not_found, service_item_not_found"}}
REQUEST_404: ResponseMap = {404: {**ERR, "description": "service_request_not_found"}}
READ_NOTE = "Requires 'services:read' (administrator, sales, management)."
MANAGE_NOTE = "Requires 'services:manage' (administrator, sales)."
LocaleQuery = Annotated[Locale, Query(description="Texts in this language (English fallback)")]


def _image(service: ServiceCategory, storage: MediaStorage, alt: str) -> PublicImage | None:
    if service.image_media is None:
        return None
    return PublicImage.model_validate(public_image(storage, service.image_media, alt, 0))


def _items(service: ServiceCategory, locale: str) -> list[PublicServiceItem]:
    return [
        PublicServiceItem(id=i.id, title=localized(i.title_en, i.title_rw, locale))
        for i in service.items
    ]


def _summary_fields(service: ServiceCategory, storage: MediaStorage, locale: str) -> dict:
    name = localized(service.name_en, service.name_rw, locale)
    return {
        "slug": service.slug,
        "name": name,
        "short_description": localized(
            service.short_description_en, service.short_description_rw, locale
        ),
        "icon": service.icon,
        "image": _image(service, storage, name),
    }


def _staff_service(service: ServiceCategory, storage: MediaStorage, requests: int) -> StaffService:
    return StaffService(
        id=service.id,
        slug=service.slug,
        name_en=service.name_en,
        name_rw=service.name_rw,
        short_description_en=service.short_description_en,
        short_description_rw=service.short_description_rw,
        intro_en=service.intro_en,
        intro_rw=service.intro_rw,
        icon=service.icon,  # type: ignore[arg-type]
        image=_image(service, storage, service.name_en),
        sort_order=service.sort_order,
        is_active=service.is_active,
        items=[StaffServiceItem.model_validate(i) for i in service.items],
        request_count=requests,
        created_at=service.created_at,
        updated_at=service.updated_at,
    )


def _staff_request(db: Session, request: ServiceRequest) -> StaffServiceRequest:
    assignee = db.get(User, request.assigned_to_user_id) if request.assigned_to_user_id else None
    return StaffServiceRequest(
        id=request.id,
        reference=request.reference,
        service=ServiceRef(
            id=request.service.id, slug=request.service.slug, name=request.service.name_en
        ),
        full_name=request.full_name,
        phone=request.phone,
        email=request.email,
        location=request.location,
        client_type=request.client_type,  # type: ignore[arg-type]
        message=request.message,
        preferred_date=request.preferred_date,
        locale=request.locale,  # type: ignore[arg-type]
        status=request.status,  # type: ignore[arg-type]
        status_changed_at=request.status_changed_at,
        assigned_to=StaffRef(id=assignee.id, name=assignee.full_name or assignee.email or "")
        if assignee
        else None,
        internal_notes=request.internal_notes,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


# ---- public ------------------------------------------------------------------------------------
@public_router.get(
    "",
    response_model=list[PublicServiceWithItems],
    summary="List the technical services",
    description="Public. The active services in staff's order, with their items.",
)
def list_services(
    db: Db, storage: Storage, locale: LocaleQuery = "en"
) -> list[PublicServiceWithItems]:
    return [
        PublicServiceWithItems(**_summary_fields(s, storage, locale), items=_items(s, locale))
        for s in PublicServices.active(db)
    ]


@public_router.get(
    "/{slug}",
    response_model=PublicService,
    summary="Get a technical service",
    description="Public. An active service with its intro and items; a hidden one is 404.",
    responses=SERVICE_404,
)
def get_service(slug: str, db: Db, storage: Storage, locale: LocaleQuery = "en") -> PublicService:
    service = PublicServices.by_slug(db, slug)
    return PublicService(
        **_summary_fields(service, storage, locale),
        intro=localized(service.intro_en, service.intro_rw, locale),
        items=_items(service, locale),
    )


@public_router.post(
    "/{slug}/requests",
    response_model=ServiceRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Request a technical service",
    description=(
        "Public. Name, a Rwandan mobile number and the client type (home, business or "
        "institution) are required; email, location, message and a preferred date (today to one "
        "year ahead, Kigali time) are optional. `website` must stay empty: a request that fills "
        "it is answered like this but not stored. Every attempt counts against a limit per phone "
        "number and per network (429 with Retry-After); an unavailable limit store answers 503. "
        "Returns the request's reference."
    ),
    responses={
        **SERVICE_404,
        **VALIDATION_422,
        429: {
            **ERR,
            "description": "rate_limited",
            "headers": {
                "Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}
            },
        },
        503: {**ERR, "description": "service_request_unavailable"},
    },
)
def request_service(
    slug: str,
    req: ServiceRequestCreate,
    db: Db,
    ctx: Ctx,
    limiter: Annotated[LoginRateLimiter, Depends(get_service_request_rate_limiter)],
    background: BackgroundTasks,
    notifier: Notifier,
) -> ServiceRequestCreated:
    reference = PublicServices.request(db, slug, req, limiter, ctx)
    notifier.schedule(background, db)  # the acknowledgement, when an email was given
    return ServiceRequestCreated(reference=reference)


# ---- staff: services ---------------------------------------------------------------------------
@staff_router.get(
    "/services",
    response_model=list[StaffService],
    summary="List services (staff)",
    description=f"{READ_NOTE} Every service, hidden ones included, in order, with its items.",
    responses=GUARDED,
)
def staff_list_services(_: Reader, db: Db, storage: Storage) -> list[StaffService]:
    counts = request_counts(db)
    return [_staff_service(s, storage, counts.get(s.id, 0)) for s in ServiceAdmin.all(db)]


@staff_router.post(
    "/services",
    response_model=StaffService,
    status_code=status.HTTP_201_CREATED,
    summary="Create a service",
    description=(
        f"{MANAGE_NOTE} Added last. The slug is generated from the English name when omitted; a "
        "taken slug is 409 slug_taken. Audited as 'services.service_create'."
    ),
    responses={**GUARDED, 409: {**ERR, "description": "slug_taken"}, **VALIDATION_422},
)
def create_service(
    req: ServiceCreateRequest, actor: Manager, db: Db, ctx: Ctx, storage: Storage
) -> StaffService:
    return _staff_service(ServiceAdmin.create(db, actor, req, ctx), storage, 0)


@staff_router.put(
    "/services/order",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Reorder the services",
    description=(
        f"{MANAGE_NOTE} Every service exactly once, in the new order (409 "
        "service_order_mismatch otherwise). Audited as 'services.service_reorder' when the order "
        "changes."
    ),
    responses={**GUARDED, 409: {**ERR, "description": "service_order_mismatch"}, **VALIDATION_422},
)
def reorder_services(req: ServiceOrderRequest, actor: Manager, db: Db, ctx: Ctx) -> Response:
    ServiceAdmin.reorder(db, actor, req, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.patch(
    "/services/{service_id}",
    response_model=StaffService,
    summary="Edit a service",
    description=(
        f"{MANAGE_NOTE} Only the fields sent change; is_active=false hides it from the store. "
        "Audited as 'services.service_update' when something changes."
    ),
    responses={
        **GUARDED,
        **SERVICE_404,
        409: {**ERR, "description": "slug_taken"},
        **VALIDATION_422,
    },
)
def update_service(
    service_id: uuid.UUID,
    req: ServiceUpdateRequest,
    actor: Manager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> StaffService:
    service = ServiceAdmin.update(db, actor, service_id, req, ctx)
    return _staff_service(service, storage, request_counts(db).get(service.id, 0))


@staff_router.delete(
    "/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a service without requests",
    description=(
        f"{MANAGE_NOTE} A service with requests cannot be deleted (409 service_has_requests); "
        "hide it instead. Its items go with it and its image files are retired. Audited as "
        "'services.service_delete'."
    ),
    responses={
        **GUARDED,
        **SERVICE_404,
        409: {**ERR, "description": "service_has_requests"},
        **VALIDATION_422,
    },
)
def delete_service(service_id: uuid.UUID, actor: Manager, db: Db, ctx: Ctx) -> Response:
    ServiceAdmin.delete(db, actor, service_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.post(
    "/services/{service_id}/image",
    response_model=StaffService,
    summary="Upload or replace a service image",
    description=(
        f"{MANAGE_NOTE} multipart/form-data with `file` (JPEG, PNG or WebP, at most 5 MB), "
        "processed as category images. Audited as 'services.service_image_upload'."
    ),
    responses={**GUARDED, **SERVICE_404, **TOO_LARGE_413, **UPLOAD_422},
)
def upload_service_image(
    service_id: uuid.UUID, file: ImageFile, actor: Manager, db: Db, ctx: Ctx, storage: Storage
) -> StaffService:
    raw = read_upload(file.file)
    service = ServiceAdmin.set_image(
        db, storage, actor, service_id, processed_upload(raw), len(raw), ctx
    )
    return _staff_service(service, storage, request_counts(db).get(service.id, 0))


@staff_router.delete(
    "/services/{service_id}/image",
    response_model=StaffService,
    summary="Remove a service image",
    description=(
        f"{MANAGE_NOTE} Clears the image and retires its files. Without an image, nothing "
        "changes. Audited as 'services.service_image_delete'."
    ),
    responses={**GUARDED, **SERVICE_404, **VALIDATION_422},
)
def delete_service_image(
    service_id: uuid.UUID, actor: Manager, db: Db, ctx: Ctx, storage: Storage
) -> StaffService:
    service = ServiceAdmin.remove_image(db, actor, service_id, ctx)
    return _staff_service(service, storage, request_counts(db).get(service.id, 0))


@staff_router.post(
    "/services/{service_id}/items",
    response_model=StaffServiceItem,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item to a service",
    description=(
        f"{MANAGE_NOTE} Added last; at most 30 per service. Audited as 'services.item_create'."
    ),
    responses={**GUARDED, **SERVICE_404, **VALIDATION_422},
)
def add_service_item(
    service_id: uuid.UUID, req: ServiceItemCreateRequest, actor: Manager, db: Db, ctx: Ctx
) -> StaffServiceItem:
    return StaffServiceItem.model_validate(ServiceAdmin.add_item(db, actor, service_id, req, ctx))


@staff_router.put(
    "/services/{service_id}/items/order",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Reorder a service's items",
    description=(
        f"{MANAGE_NOTE} Every item of the service exactly once (409 "
        "service_item_order_mismatch otherwise). Audited as 'services.item_reorder'."
    ),
    responses={
        **GUARDED,
        **SERVICE_404,
        409: {**ERR, "description": "service_item_order_mismatch"},
        **VALIDATION_422,
    },
)
def reorder_service_items(
    service_id: uuid.UUID, req: ServiceItemOrderRequest, actor: Manager, db: Db, ctx: Ctx
) -> Response:
    ServiceAdmin.reorder_items(db, actor, service_id, req, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.patch(
    "/services/{service_id}/items/{item_id}",
    response_model=StaffServiceItem,
    summary="Edit a service item",
    description=f"{MANAGE_NOTE} Audited as 'services.item_update' when something changes.",
    responses={**GUARDED, **ITEM_404, **VALIDATION_422},
)
def update_service_item(
    service_id: uuid.UUID,
    item_id: uuid.UUID,
    req: ServiceItemUpdateRequest,
    actor: Manager,
    db: Db,
    ctx: Ctx,
) -> StaffServiceItem:
    item = ServiceAdmin.update_item(db, actor, service_id, item_id, req, ctx)
    return StaffServiceItem.model_validate(item)


@staff_router.delete(
    "/services/{service_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a service item",
    description=f"{MANAGE_NOTE} Audited as 'services.item_delete'.",
    responses={**GUARDED, **ITEM_404, **VALIDATION_422},
)
def delete_service_item(
    service_id: uuid.UUID, item_id: uuid.UUID, actor: Manager, db: Db, ctx: Ctx
) -> Response:
    ServiceAdmin.delete_item(db, actor, service_id, item_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- staff: requests ---------------------------------------------------------------------------
@staff_router.get(
    "/service-requests",
    response_model=Page[StaffServiceRequest],
    summary="List service requests",
    description=(
        f"{READ_NOTE} Newest first. Filters: status, service (id), assignee and the Kigali dates "
        "the requests were sent (from/to, inclusive)."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_service_requests(
    _: Reader,
    db: Db,
    status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None,
    service_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffServiceRequest]:
    filters = RequestFilters(
        status=status_filter,
        service_id=service_id,
        date_from=date_from,
        date_to=date_to,
        assigned_to_user_id=assigned_to,
    )
    rows, total = ServiceRequestAdmin.page(db, filters, page, size)
    return Page[StaffServiceRequest](
        items=[_staff_request(db, r) for r in rows], total=total, page=page, size=size
    )


@staff_router.get(
    "/service-requests/assignees",
    response_model=list[StaffRef],
    summary="Staff who can be assigned service requests",
    description=f"{READ_NOTE} Active staff with 'services:manage', by name.",
    responses=GUARDED,
)
def list_service_assignees(_: Reader, db: Db) -> list[StaffRef]:
    return [
        StaffRef(id=u.id, name=u.full_name or u.email or "")
        for u in ServiceRequestAdmin.assignees(db)
    ]


@staff_router.get(
    "/service-requests/{request_id}",
    response_model=StaffServiceRequest,
    summary="Get a service request",
    description=READ_NOTE,
    responses={**GUARDED, **REQUEST_404, **VALIDATION_422},
)
def get_service_request(request_id: uuid.UUID, _: Reader, db: Db) -> StaffServiceRequest:
    return _staff_request(db, ServiceRequestAdmin.get(db, request_id))


@staff_router.patch(
    "/service-requests/{request_id}",
    response_model=StaffServiceRequest,
    summary="Follow up a service request",
    description=(
        f"{MANAGE_NOTE} Only the fields sent change: status, assigned_to_user_id (an active "
        "staff member with 'services:manage'; null unassigns) and internal_notes (null or blank "
        "clears them). Audited as 'services.request_update' when something changes; the notes' "
        "text is not copied into the audit trail."
    ),
    responses={**GUARDED, **REQUEST_404, **VALIDATION_422},
)
def update_service_request(
    request_id: uuid.UUID, req: ServiceRequestUpdate, actor: Manager, db: Db, ctx: Ctx
) -> StaffServiceRequest:
    return _staff_request(db, ServiceRequestAdmin.update(db, actor, request_id, req, ctx))
