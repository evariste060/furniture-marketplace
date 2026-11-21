# Working agreements
Read the original project requirements linked in docs/requirements/README.md first.
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
The public /admin placeholder contains no protected data or functionality.
