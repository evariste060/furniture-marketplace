# Frontend

Next.js 16 (App Router, Cache Components) for the storefront and the admin. Architecture: `docs/architecture/ADR-011-frontend-architecture.md`. Design handoff and rules: `frontend/CLAUDE.md` and `frontend/design/`. Settings: copy `.env.example` to `.env.local`.

| Command | What it does |
| --- | --- |
| `npm run dev` | Development server on http://localhost:3000 (the API must be running; see `.env.example`). |
| `npm run build` | Production build (does not need the API). |
| `npm run lint` / `npm run typecheck` | ESLint (with accessibility rules) and TypeScript. |
| `npm test` | Unit and component tests (Vitest). |
| `npm run test:e2e` | Playwright against a production build on port 3100, with an axe check on every page and screenshots in `e2e/screenshots`. Needs the API running and `npx playwright install chromium` once. |
| `npm run api:types` | Regenerates `src/lib/api/schema.d.ts` from the running API's OpenAPI; commit the result. |
| `npm run i18n:review` | Regenerates `docs/frontend/rw-review.md` (Kinyarwanda strings for native-speaker review). |

Development pages: `/dev/ui` shows every base component.
