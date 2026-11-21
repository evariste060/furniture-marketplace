from fastapi import APIRouter

from app.api.v1.endpoints import reviews as reviews_endpoints
from app.api.v1.endpoints.audit import router as audit_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.banners import public_router as banners_router
from app.api.v1.endpoints.banners import staff_router as staff_banners_router
from app.api.v1.endpoints.cart import router as cart_router
from app.api.v1.endpoints.catalog import router as catalog_router
from app.api.v1.endpoints.catalog_admin import router as catalog_admin_router
from app.api.v1.endpoints.catalog_import import router as catalog_import_router
from app.api.v1.endpoints.checkout import router as checkout_router
from app.api.v1.endpoints.customers import router as customers_router
from app.api.v1.endpoints.delivery import public_router as delivery_router
from app.api.v1.endpoints.delivery import staff_router as staff_delivery_router
from app.api.v1.endpoints.google_auth import router as google_auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.image_admin import router as image_admin_router
from app.api.v1.endpoints.inventory import router as inventory_router
from app.api.v1.endpoints.jobs import router as jobs_router
from app.api.v1.endpoints.media_admin import router as media_admin_router
from app.api.v1.endpoints.notifications import router as staff_notifications_router
from app.api.v1.endpoints.orders import customer_router as customer_orders_router
from app.api.v1.endpoints.orders import lookup_router as order_lookup_router
from app.api.v1.endpoints.orders import staff_router as staff_orders_router
from app.api.v1.endpoints.pages import public_router as pages_router
from app.api.v1.endpoints.pages import staff_router as staff_pages_router
from app.api.v1.endpoints.payments import router as payments_router
from app.api.v1.endpoints.payments import staff_router as staff_payments_router
from app.api.v1.endpoints.payments import webhook_router as payment_webhook_router
from app.api.v1.endpoints.product_admin import router as product_admin_router
from app.api.v1.endpoints.promotions import router as staff_promotions_router
from app.api.v1.endpoints.quotes import public_router as quotes_router
from app.api.v1.endpoints.quotes import staff_router as staff_quotes_router
from app.api.v1.endpoints.reports import router as staff_reports_router
from app.api.v1.endpoints.sellers import seller_router
from app.api.v1.endpoints.sellers import staff_router as staff_sellers_router
from app.api.v1.endpoints.services import public_router as services_router
from app.api.v1.endpoints.services import staff_router as staff_services_router
from app.api.v1.endpoints.settings import public_router as settings_router
from app.api.v1.endpoints.settings import router as staff_settings_router
from app.api.v1.endpoints.staff import router as staff_router
from app.api.v1.endpoints.support import customer_router as support_customer_router
from app.api.v1.endpoints.support import public_router as support_router
from app.api.v1.endpoints.support import staff_router as staff_support_router
from app.api.v1.endpoints.wishlist import router as wishlist_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(google_auth_router)
router.include_router(customers_router)
router.include_router(wishlist_router)  # /customers/me/wishlist (module 21)
router.include_router(staff_router)
router.include_router(catalog_admin_router)  # /staff/categories, /staff/brands
router.include_router(product_admin_router)  # /staff/products
router.include_router(image_admin_router)  # /staff/products/{id}/images, /staff/images
router.include_router(catalog_import_router)  # /staff/imports
router.include_router(media_admin_router)  # /staff/media (ADR-009 media registry)
router.include_router(jobs_router)  # /staff/jobs (durable job queue)
router.include_router(banners_router)  # /banners (storefront content)
router.include_router(staff_banners_router)  # /staff/banners (content:manage)
router.include_router(audit_router)
router.include_router(catalog_router)
router.include_router(reviews_endpoints.public_router)  # /catalog/products/{slug}/reviews (20)
router.include_router(cart_router)  # /cart (module 11)
router.include_router(delivery_router)  # /delivery (module 12)
router.include_router(staff_delivery_router)  # /staff/delivery (module 12)
router.include_router(staff_settings_router)  # /staff/settings (module 12)
router.include_router(settings_router)  # /settings, public store contact (module 19)
router.include_router(pages_router)  # /pages/{slug} (module 19)
router.include_router(staff_pages_router)  # /staff/pages (module 19, content:manage)
router.include_router(quotes_router)  # /quote-requests (module 19)
router.include_router(staff_quotes_router)  # /staff/quote-requests (module 19, quotes:manage)
router.include_router(services_router)  # /services (ADR-013)
router.include_router(staff_services_router)  # /staff/services, /staff/service-requests
router.include_router(support_router)  # /support-messages (2026-11-11)
router.include_router(support_customer_router)  # /customers/me/support-threads
router.include_router(staff_support_router)  # /staff/support-threads (support:read/reply)
router.include_router(staff_promotions_router)  # /staff/promotions (module 13)
router.include_router(checkout_router)  # /checkout (module 14)
router.include_router(customer_orders_router)
router.include_router(order_lookup_router)  # /orders/lookup (module 14)
router.include_router(reviews_endpoints.customer_router)  # review links (module 20)
router.include_router(reviews_endpoints.guest_router)  # /orders/review-link (module 20)
router.include_router(reviews_endpoints.link_router)  # /reviews/{token} (module 20)
router.include_router(reviews_endpoints.staff_router)  # /staff/reviews (module 20)
router.include_router(payments_router)  # /payments (module 15)
router.include_router(payment_webhook_router)  # /webhooks (module 15)
router.include_router(staff_payments_router)  # /staff/payments (module 15)
router.include_router(staff_orders_router)
router.include_router(inventory_router)
router.include_router(staff_notifications_router)  # /staff/notifications (module 17)
router.include_router(staff_reports_router)  # /staff/reports (module 18)
router.include_router(seller_router)  # /seller (ADR-014: applications, own store)
router.include_router(staff_sellers_router)  # /staff/sellers (ADR-014, sellers:read/manage)
