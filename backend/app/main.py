import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.root import router as root_router
from app.api.v1.router import router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.request_context import warn_if_peer_client_ip_in_production
from app.core.upload_limit import UPLOAD_FORM_OVERHEAD_BYTES, UploadSizeLimitMiddleware
from app.integrations.media import LocalMediaStorage, PublicMediaFiles
from app.integrations.notifications import warn_if_temporary_gmail_smtp
from app.schemas.catalog_import import MAX_IMPORT_BYTES
from app.services.bulk_images import MAX_FILES as BULK_MAX_FILES
from app.services.bulk_images import MAX_REQUEST_BYTES as BULK_MAX_REQUEST_BYTES
from app.services.dev_data_guard import check_at_startup
from app.services.image_processing import MAX_UPLOAD_BYTES

settings = get_settings()
configure_logging(settings.log_level)

tags_metadata = [
    {
        "name": "Health",
        "description": "API health and readiness check.",
    },
    {
        "name": "Authentication",
        "description": "Customer registration, credential authentication, session tokens, logout.",
    },
    {
        "name": "Customer Accounts & Addresses",
        "description": "Customer profile management and delivery address CRUD.",
    },
    {
        "name": "Wishlist",
        "description": "Products a signed-in customer saved (module 21; at most 200).",
    },
    {
        "name": "Reviews",
        "description": "Verified-buyer product reviews (module 20): review links, submission and "
        "moderation. The public list is under catalog.",
    },
    {
        "name": "Staff Accounts & Authorization",
        "description": "Staff identity and effective permissions for every staff role; "
        "staff account provisioning, role and status administration for administrators.",
    },
    {
        "name": "Security Audit Logs",
        "description": "Append-only security audit trail inspection (Administrator only).",
    },
    {
        "name": "catalog",
        "description": "Public read-only catalogue: categories, brands, products and stock.",
    },
    {
        "name": "Customer Orders",
        "description": "Authenticated customers can read status summaries for their own orders "
        "and download their issued invoices (module 16).",
    },
    {
        "name": "Staff Order Fulfilment",
        "description": (
            "Order status transitions and fulfilment assignment (administrator); "
            "invoice (orders:read) and delivery-note (orders:fulfil) PDFs, and invoice recovery "
            "for a paid order whose invoice was refused (invoices:recover, administrator only) "
            "(module 16)."
        ),
    },
    {
        "name": "Staff Catalogue",
        "description": "Categories, brands, products, variants, product images and "
        "catalogue imports (administrator).",
    },
    {
        "name": "Storefront Content",
        "description": "Public homepage banners, the store's contact details and announcement, "
        "policy pages one language at a time (a missing translation is 404, never another "
        "language), all cached for 60 seconds; and business quote requests (module 19).",
    },
    {
        "name": "Staff Content",
        "description": "Homepage banners and policy pages (administrator; "
        "content:manage) and business quote requests (administrator; quotes:manage).",
    },
    {
        "name": "Staff Jobs",
        "description": "Background jobs done by the worker process (bulk image upload): "
        "progress and retrying failed items (administrator).",
    },
    {
        "name": "Cart",
        "description": "Guest and customer carts with server-side totals (module 11). Guests "
        "use the X-Cart-Token header; customers their bearer session.",
    },
    {
        "name": "Delivery",
        "description": "Public delivery zones, fees and the free-delivery threshold (module 12).",
    },
    {
        "name": "Staff Delivery",
        "description": "Delivery zones and fee history: view (administrator), "
        "change (administrator).",
    },
    {
        "name": "Staff Settings",
        "description": "Settings such as the free-delivery threshold and the seller details "
        "printed on invoices: view (administrator), change (administrator).",
    },
    {
        "name": "Checkout",
        "description": "Place an order from the cart: server-priced, with the promotion, "
        "delivery and VAT snapshots, stock holds and an Idempotency-Key (module 14).",
    },
    {
        "name": "Payments",
        "description": "Payment initiation and status for an order, and provider callbacks "
        "(module 15). Mobile money uses the mock provider until ADR-003 (§7 Q21).",
    },
    {
        "name": "Staff Payments",
        "description": "Payment attempts and provider events (payments:read) and "
        "cash-on-delivery confirmation (payments:manage); administrator.",
    },
    {
        "name": "Staff Promotions",
        "description": "Promotion codes: view (administrator), create, edit, "
        "activate and disable (administrator).",
    },
    {
        "name": "Staff Notifications",
        "description": "Order notification log (SMS/email for confirmed, dispatched, delivered "
        "and cancelled orders) and retries (administrator; module 17). Mock provider only "
        "until ADR-005 (§7 Q22).",
    },
    {
        "name": "Staff Reports",
        "description": "Sales by day or week, top products and stock, with Excel (XLSX) export "
        "(administrator; module 18). Sales count paid orders and delivered "
        "cash-on-delivery orders only, in Africa/Kigali days (weeks from Monday).",
    },
    {
        "name": "Seller",
        "description": "Marketplace sellers (ADR-014): a signed-in customer with a verified "
        "email applies to sell and follows the application; an approved seller reads and edits "
        "their own store. The store is always the caller's own, resolved on every request.",
    },
    {
        "name": "Seller Catalogue",
        "description": "An approved seller's own products, variants, images and stock, and the "
        "store's logo and cover (ADR-014 phase 2). Another store's resources answer 404; store_id "
        "and is_featured are never accepted.",
    },
    {
        "name": "Seller Orders",
        "description": "An approved seller's own part of each order (ADR-014 phase 3): list, "
        "read and move it one step at a time; the order's status follows its stores. Earnings "
        "are computed from these orders; payouts are not built. Another store's order is 404.",
    },
    {
        "name": "Stores",
        "description": "Approved stores on the public storefront, with their public product "
        "counts (ADR-014 phase 2). Contact details, owner and commission are never shown.",
    },
    {
        "name": "Staff Sellers",
        "description": "Seller applications and stores for administrators (sellers:read, "
        "sellers:manage): review, approve, reject, suspend and reinstate, and the commission "
        "override (ADR-014).",
    },
    {
        "name": "Support",
        "description": "Customer support conversations: sending a message (guests and "
        "customers), reading and replying by private link or from My messages, and the "
        "staff inbox (support:read; replying and closing need support:reply).",
    },
    {
        "name": "Inventory",
        "description": "Staff stock figures (administrator) and physical "
        "stock adjustments (administrator). "
        "Reservation commit, release and expiry are internal operations, not HTTP endpoints.",
    },
    {
        "name": "Storefront Services",
        "description": "Technical services (ADR-013): the active services with their items, "
        "and requesting a service (rate-limited, no account needed).",
    },
    {
        "name": "Staff Services",
        "description": "Managing the services, their items and images (services:manage) and "
        "following up service requests (services:read to view, services:manage to update).",
    },
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    check_at_startup()  # production: development seed SKUs are logged as an error
    warn_if_temporary_gmail_smtp()
    warn_if_peer_client_ip_in_production()
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version="0.1.0",
    description="Rwanda Electronics E-Commerce MVP Backend API. "
    "Implements customer registration, database-backed sessions, saved addresses, "
    "staff accounts and permission-based authorization, security audit logs, and the public "
    "read-only catalogue, plus customer order status reads and staff order fulfilment, "
    "server-priced checkout with stock holds, and payment initiation, status and signed provider "
    "callbacks (mock mobile-money provider and cash on delivery only until ADR-003; card "
    "disabled), invoice and delivery-note PDFs (no EBM claim), and order notifications "
    "(mock provider only until ADR-005).",
    openapi_tags=tags_metadata,
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Added before CORS so that CORS wraps it and a 413 still carries the CORS headers.
app.add_middleware(
    UploadSizeLimitMiddleware,
    # Product images, category images and brand logos (module 7; B1, ADR-009), and the seller's
    # product images, store logo and cover (ADR-014 phase 2).
    path_pattern=(
        r"/api/v1/(?:staff/(?:products/[^/]+/images|categories/[^/]+/image|brands/[^/]+/logo"
        r"|banners/[^/]+/image)|seller/(?:products/[^/]+/images|store/(?:logo|cover)))/?"
    ),
    max_body=MAX_UPLOAD_BYTES + UPLOAD_FORM_OVERHEAD_BYTES,
)
app.add_middleware(
    UploadSizeLimitMiddleware,
    # Bulk image upload (checkpoint 1b): at most 20 files and 100 MB per request.
    path_pattern=r"/api/v1/staff/products/bulk-images/?",
    max_body=BULK_MAX_REQUEST_BYTES + BULK_MAX_FILES * UPLOAD_FORM_OVERHEAD_BYTES,
    message="The upload is larger than 100 MB; send the files in smaller batches.",
)
app.add_middleware(
    UploadSizeLimitMiddleware,
    path_pattern=r"/api/v1/staff/imports/?",
    max_body=MAX_IMPORT_BYTES + UPLOAD_FORM_OVERHEAD_BYTES,
    message="The upload is larger than 10 MB.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # X-Cart-Token: guest carts (module 11); Idempotency-Key: stock adjustments (ADR-002).
    allow_headers=["Content-Type", "Authorization", "X-Cart-Token", "Idempotency-Key"],
)


if settings.app_env == "development":
    # Development only: the API serves public image sources itself (MEDIA_ROOT/public, plus
    # module 7 files kept in place; never MEDIA_ROOT/private). Staging and production need a web
    # server or CDN at IMAGE_PUBLIC_BASE_URL; that is not configured (ADR-004, ADR-009).
    app.mount(
        "/media",
        PublicMediaFiles(LocalMediaStorage(settings.media_root, settings.image_public_base_url)),
        name="media",
    )

logger = logging.getLogger("app.errors")

# Codes for errors raised by the framework itself (unknown route, wrong method, ...).
HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details}}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=headers)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    code = HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without echoing submitted values: they can include passwords (ADR-006)."""
    errors = [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]
    return error_response(422, "validation_error", "Request validation failed.", errors)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Method and path only: query strings and bodies can carry personal data or secrets.
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "internal_error", "An unexpected error occurred.")


app.include_router(root_router)  # GET /, outside /api/v1
app.include_router(router)


def openapi_with_standard_errors() -> dict[str, Any]:
    """FastAPI documents its own 422 body; point every 422 at the standard ErrorResponse.

    FastAPI drops null values from the whole document, examples included, so an example's
    `"details": null` appears without `details`, and null request values cannot be shown."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = FastAPI.openapi(app)
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            response = operation.get("responses", {}).get("422")
            if response is not None:
                documented = response.get("content", {}).get("application/json", {})
                body: dict[str, Any] = {"schema": error_ref}
                if "examples" in documented:  # route-specific examples are kept
                    body["examples"] = documented["examples"]
                response["content"] = {"application/json": body}
    components = schema.get("components", {}).get("schemas", {})
    for unused in ("HTTPValidationError", "ValidationError"):
        components.pop(unused, None)
    app.openapi_schema = schema
    return schema


app.openapi = openapi_with_standard_errors  # type: ignore[method-assign]
