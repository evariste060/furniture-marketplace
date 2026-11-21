# Working agreements
Read the original project requirements linked in docs/requirements/README.md first, then the approved scope changes in docs/requirements/scope-changes.md. SC-04 and docs/architecture/ADR-014-multi-vendor-marketplace.md turn the single electronics store into a multi-vendor furniture marketplace (provisional name FurniHub); where they disagree with the original documents, they win.
Use Next.js App Router/TypeScript for frontend and FastAPI/Pydantic v2 for backend.
Use PostgreSQL, SQLAlchemy 2 and Alembic. Review data design before creating models or migrations.
Follow modular API/schema/model/repository/service/integration boundaries.
Reference real Trello card IDs and PR-xx/TC-xx IDs; never invent card IDs. Respect task dependencies.
Write tests for implemented features. Validate frontend and backend inputs.
Enforce backend authorization for protected resources. Never trust browser prices or totals.
When payment implementation is approved, verify provider authenticity and implement idempotency.
Keep secrets out of source control and logs. Update documentation for architectural decisions.
Run relevant tests, Ruff, ESLint, TypeScript and build checks before completing tasks.
Never introduce undocumented features without approval.
/admin is the staff dashboard: the layout checks the session on the server, and the backend checks every call again. It must never show protected data to a customer, a seller or a signed-out visitor.

# Marketplace rules (ADR-014)
Work in the approved ADR-014 phases, one at a time, and report to the owner before starting the next.
Sellers are store owners, not staff: never give a seller a staff role or a global permission.
Seller access is scoped to the caller's own approved store, resolved on the backend on every request; another store's resource answers 404. Hiding UI is never the control.
Never accept store_id, store status, commission or merchandising fields from seller request bodies.
Every seller route needs a cross-store test: seller A is refused seller B's store, products, images, stock and orders.
Keep one parent order and one payment per checkout; sellers change only their own seller group, and payment, stock commitment and whole-order cancellation stay with the platform.
Show sellers only the customer data their own order group needs.
Keep the marketplace name in configuration, not hard-coded in components; change English and Kinyarwanda messages together.
Destructive data scripts run only in development against a local database, after confirming the environment.
