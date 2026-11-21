# ADR-001: Next.js, FastAPI and PostgreSQL
Status: developer-selected technologies, accepted for the development foundation.
Next.js and FastAPI are explicitly selected by the developer, resolving the documents' open platform choice. PostgreSQL is selected for persistence by this task.
Next.js App Router supports shared layouts, future SEO/server rendering, responsive Tailwind UI and a single storefront/admin application. TypeScript improves frontend contracts.
FastAPI supplies typed Pydantic validation and OpenAPI with modular Python services. SQLAlchemy supports transactional persistence boundaries.
PostgreSQL provides relational integrity and concurrency controls needed for future stock/orders. No commerce schema or inventory policy is approved here.
Frontend communicates using JSON HTTP under /api/v1 with NEXT_PUBLIC_API_URL. Explicit CORS origins permit browser access. Health uses the reusable API client.
Alembic manages reviewed schema migrations. Approve ADR-002 first, import approved models, review generated revisions and rollback plans. No commerce schema or production migration is applied.
Tradeoffs: two runtimes and deployments increase operations and contract coordination; separate API boundaries support integrations. PostgreSQL requires container resources, backups and restore testing.
Deployment: separate credentials/databases and payment modes per environment, HTTPS, least privilege, monitoring, backups/restore drills and reviewed releases. Public frontend variables are build-time settings and must never contain secrets. Hosting is not selected by this setup.
Unresolved approvals: entity/relationship/index design and stock reservation rules (ADR-002), hosting/managed database/domain/TLS/backup plan (ADR-004), authentication/session/roles, payment provider and merchant onboarding (ADR-003), notifications, VAT/EBM/invoices, delivery fees, catalogue/brand, language default and translation owner. PostgreSQL engine selection is resolved; deployment sizing/provider remains open.
