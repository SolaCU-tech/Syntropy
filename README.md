# Syntropy

Syntropy turns a small business's scattered records (spreadsheets, notebooks, WhatsApp
messages) into a working business database, then helps the owner run and understand the
business from it.

The single source of truth for what to build is [`docs/syntropy-spec.md`](docs/syntropy-spec.md).

## Status

**Phase 3 — Workspace UI.** The app shell with the nine-item navigation, sign-in, the tables
index, an SSD-driven table view (search, filter chips, server-side sorting and pages), record
pages with linked records, and generated forms with link pickers that can create a linked
record inline. Offline entry: the app installs as a PWA and opens with no connection, reads
come from an IndexedDB cache, and creates and edits go through a sync queue
(`POST /api/workspaces/{id}/sync/`) with idempotency keys, conflicts the user resolves, and
rejections the user fixes. Exit gate: sync tests pass (backend adversarial tests and the
Playwright offline journeys).

Phase 2 — Storage. Business records as JSONB rows with links in a relational link table,
workspace- and table-scoped foreign keys, a unique-value registry, delete policies,
optimistic concurrency and a records API, with adversarial and concurrency tests. Exit gate:
the JSONB vs physical-tables benchmark, done. See
[`docs/storage-decision.md`](docs/storage-decision.md). Passed its gate.

Phase 1 — Schema registry. SSD v1 as Pydantic models with an exported JSON Schema; a
versioned registry with immutable published snapshots; organizations, workspaces,
memberships and the workspace resolver; the hand-written retail SSD. Exit gate: retail SSD
valid. See [`docs/ssd.md`](docs/ssd.md). Passed its gate.

Phase 0 (foundation: monorepo, Compose, CI, test harness, design tokens) passed its gate.

## Repository layout

```
backend/    Django + DRF API, Celery worker, pytest
frontend/   React + TypeScript + Vite, Tailwind CSS + shadcn/ui, Vitest
docs/       The spec and decision records
docker-compose.yml   PostgreSQL, Redis and MinIO for local development
.github/workflows/   CI: lint, type-check, tests on every push
```

## Prerequisites (Windows)

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.12 or newer (`py --version`)
- Node.js 20.19 or newer (`node --version`)
- Git

## First-time setup

The commands below are for PowerShell, run from the repository root.

```powershell
# 1. Start PostgreSQL, Redis and MinIO
docker compose up -d

# 2. Backend
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin
python manage.py seed_demo         # demo user "demo" / "demo-pass-1" with the example shop
python manage.py runserver         # http://localhost:8000/api/health/

# 3. Frontend (in a second terminal)
cd frontend
npm install
npm run dev                        # http://localhost:5173, sign in as demo
```

`seed_demo` only runs with `DJANGO_DEBUG=true` (the `.env.example` default). To add the
example workspace to your own user instead, run `python manage.py seed_retail_example <username>`.

If PowerShell refuses to run `Activate.ps1`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

The frontend's dev server forwards `/api` to Django, so the browser sees one site and the
session cookie and CSRF token work without CORS (ADR-24).

To run everything (Django, a Celery worker and Vite) in Docker instead:
`docker compose --profile app up -d`.

## Running the checks

These are the same checks CI runs. All of them must pass before merging to `main`.

```powershell
# Backend (with the venv active, from backend/)
ruff check .
ruff format --check .
python manage.py makemigrations --check --dry-run
pytest

# Frontend (from frontend/)
npm run lint
npm run typecheck
npm test
npm run build

# End-to-end, offline journeys included (from frontend/). Needs the backend running with
# seed_demo, and the built app served on port 4173:
npm run build; npx vite preview --port 4173   # second terminal
npx playwright install chromium               # first time only
npm run e2e
```

Offline behaviour needs the built app (`npm run build` then `vite preview`): the service
worker that makes the app open offline is not active in `npm run dev`. In Chrome DevTools,
Network > Offline simulates losing the connection.

## Storage benchmark

```powershell
cd backend;  python manage.py run_storage_benchmark   # about a minute; --quick for a smoke run
```

It creates and drops its own throwaway database (your dev data is untouched) and rewrites
[`docs/benchmarks/storage-benchmark.md`](docs/benchmarks/storage-benchmark.md).

## API types

The backend publishes an OpenAPI schema with drf-spectacular, and the frontend generates its
TypeScript types from it (ADR-26). After changing an endpoint:

```powershell
cd backend;  python manage.py spectacular --file schema.yml
cd ../frontend;  npm run api:types
```

Commit both `backend/schema.yml` and `frontend/src/api/types.ts`. CI fails if either is stale.

Interactive API docs are at http://localhost:8000/api/docs/ while `DJANGO_DEBUG=true`.

## Useful URLs (local)

| What | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| API health | http://localhost:8000/api/health/ |
| API docs | http://localhost:8000/api/docs/ |
| Django admin | http://localhost:8000/admin/ |
| MinIO console | http://localhost:9001 (user `syntropy`, password `syntropy-dev-secret`) |

## Branches

`dev` is for work in progress; `main` is stable. Merge `dev` into `main` when CI is green.

## Secrets

Never commit real passwords, API keys or connection strings. Put them in `backend/.env`
(git-ignored) and keep `backend/.env.example` up to date with the variable names.
