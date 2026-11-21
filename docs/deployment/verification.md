# Setup verification ? 2026-10-19

Repository: tsonGroup/rwanda-electronics-ecommerce. The pre-existing workspace starter and three original requirements documents were preserved; all setup writes targeted this new repository. Git is initialized locally; no commit, remote push or deployment was performed.

## Installed versions
Next.js 16.4.2; React 19.3.0; FastAPI 0.148.0; PostgreSQL container 18.6 (postgres:18); SQLAlchemy 2.1.5; Pydantic 2.14.1; Alembic 1.20.0; Ruff 0.17.1; Uvicorn 0.54.0. Python dependencies are frozen in backend/uv.lock and frontend dependencies in frontend/package-lock.json.

## Results
- Frontend clean `npm ci`: PASS, zero vulnerabilities.
- Frontend `npm run lint`: PASS using ESLint 10, typescript-eslint and React Hooks rules.
- Frontend `npm run typecheck`: PASS, Next route type generation and tsc.
- Frontend `npm run build`: PASS; routes / and /admin generated.
- Next.js development startup: PASS, localhost:3000; homepage and admin HTTP 200.
- FastAPI Uvicorn startup: PASS, 127.0.0.1:8000.
- Live GET /api/v1/health: PASS, HTTP 200 and {"status":"ok"}.
- Backend frozen `uv sync --frozen`: PASS.
- `uv run --frozen pytest -q`: PASS, 3 tests (health, allowed CORS origin, rejected origin).
- `uv run --frozen ruff check .`: PASS.
- `uv run --frozen ruff format --check .`: PASS, 17 files.
- `docker compose up -d --wait db`: PASS; container healthy on 127.0.0.1:55432.
- SQLAlchemy `python ../scripts/check_database.py`: PASS, SELECT 1.
- `alembic current` and `alembic heads`: PASS, no current revision or migration heads. No commerce schema or production migration was applied.
- Real Chromium mobile browser at 390x844: PASS. `playwright screenshot --browser chromium --viewport-size '390,844' --wait-for-selector 'text=Backend reachable' --timeout 120000 http://localhost:3000 ../docs/deployment/development-mobile.png` completed successfully from frontend using temporary npx @playwright/test. This verifies client fetch, URL configuration and browser CORS together. See development-mobile.png.
- `git check-ignore .env backend/.env frontend/.env.local`: PASS. Each real environment file is excluded.
- Safe root/backend/frontend .env.example and staging/production templates: confirmed trackable with git ls-files --others --exclude-standard.
- New git rev-parse --show-toplevel: correct isolated repository. Original files were not edited.

## Resolved setup issues and limitations
Docker Desktop was initially stopped; it was started in the background. Initial `docker compose up -d --wait db` failed because Windows disallowed binding 127.0.0.1:5432; ignored local configuration now uses port 55432, without changing existing database services. Direct IPv4 is used for backend database connections.
The first clean npm reinstall failed with EPERM on a native CSS module while Next dev was running. The server was stopped and clean npm ci succeeded. Run installations with development servers stopped on Windows.
An early HTTP health probe occurred before Uvicorn started and failed; subsequent live API and browser checks succeeded. A duplicate Uvicorn startup encountered occupied port 8000 while the verified server was already running; only the successful server was retained.
The default Next ESLint preset included incompatible ESLint 10 peers and a vulnerable braces dependency chain. Supported generic ESLint/TypeScript/React Hooks rules replace it; final npm audit reports zero vulnerabilities. Framework-specific Next lint rules are not enabled.
Pytest emits one upstream Starlette deprecation warning for its httpx TestClient transport. All tests pass; no warning is suppressed.
The Trello board URL could not be read by the web tool (Internal Error). Real card IDs/current board ordering are unverified. Next tasks in README follow the supplied technical delivery document, not a claimed board inspection.
Local development is verified. Hosted staging/production, production credentials, authentication, payment integrations, commerce migrations and business UAT are outside this setup and have not been run.
