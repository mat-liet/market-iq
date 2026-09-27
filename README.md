# Market Narrative Intelligence

Ingests financial news, uses an LLM to classify each article into a fixed taxonomy of
**market narratives**, maps those narratives to **companies** with sentiment and
importance, and serves the result as **narrative reports** — over a REST API and a
React dashboard that visualises which narratives are accelerating and the companies
riding them.

The working hypothesis: *accelerating narratives are an investment-research signal
before they are fully priced in*. The system builds a structured data foundation —
articles, themes, companies, sentiment — that analytics and trend detection can be
built on.

---

## How it works

```
RSS feeds (CNBC, Yahoo Finance, MarketWatch)
        │
        ▼
 Ingestion worker ──► articles (PostgreSQL, processed=false)   [every 30 min]
        │                         │
        │                  body extraction (trafilatura, SSRF-guarded)
        ▼                         │
 Classification worker ◄──────────┘                            [every 15 min]
   (Claude)
        │  themes + companies, each with sentiment/importance
        ▼
 Structured signals (PostgreSQL)
        │
        ▼
 Report generator  ──►  FastAPI read API  ──►  React dashboard (nginx)
```

The two workers are **decoupled through the database**: ingestion only writes raw
articles and marks them `processed=false`; classification polls for unprocessed
articles, calls the LLM, and writes the structured result. Each runs on its own
schedule and neither blocks the other.

For deeper detail see:

- [`docs/phase-one-design.md`](docs/phase-one-design.md) — technical design & data model rationale
- [`docs/market-narrative-architecture.md`](docs/market-narrative-architecture.md) — full system diagram
- [`docs/market-narrative-cicd.md`](docs/market-narrative-cicd.md) — CI/CD pipeline design

---

## Quick start (Docker)

The fastest path — Postgres, the API, and the dashboard come up together; migrations
and taxonomy seeding run automatically on startup.

```bash
cp .env.example .env          # then edit ANTHROPIC_API_KEY
docker compose up --build
```

Once up:

- **Dashboard** — <http://localhost:3000>
- **API** — <http://localhost:8000> (interactive docs at <http://localhost:8000/docs>)

The dashboard container serves the built SPA via nginx and reverse-proxies the API on
the same origin, so the browser talks only to port 3000.

On startup the container entrypoint (`docker-entrypoint.sh`) runs
`alembic upgrade head` and seeds the taxonomy (idempotent) **before** serving, so a
fresh database comes up fully usable.

---

## Local development

Requires **Python 3.13** (the Docker image uses 3.11) and a reachable **PostgreSQL 15**.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # edit DATABASE_URL + ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)   # or use your own env loader

# Bring the schema and taxonomy up
alembic upgrade head
python -m scripts.seed_taxonomy

# Run the API (with the background scheduler disabled, see below)
ENABLE_SCHEDULER=false uvicorn app.main:app --reload
```

### Running the workers manually

The scheduler (`app/workers/scheduler.py`) normally runs both workers on intervals
inside the API process. To trigger a single pass by hand:

```bash
python -c "from app.workers.scheduler import run_ingestion; run_ingestion()"
python -c "from app.workers.scheduler import run_classification; run_classification()"
```

### Reviewing classification quality

`scripts/review_classifications.py` prints a sample of recent articles alongside
their stored themes/companies/sentiment for manual spot-checking:

```bash
python -m scripts.review_classifications
```

### Dashboard (frontend)

The dashboard is a React + TypeScript (Vite) SPA in [`frontend/`](frontend/). With the
API running, start the dev server with hot reload:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

In dev, API paths are proxied to the backend at `http://localhost:8000`. See
[`frontend/README.md`](frontend/README.md) for the screens, scripts, and API client.

---

## Configuration

Configuration is read from the environment (see `app/config.py` and `.env.example`):

| Variable           | Required | Default                  | Notes |
|--------------------|----------|--------------------------|-------|
| `DATABASE_URL`     | yes      | —                        | SQLAlchemy URL, e.g. `postgresql://market:market@localhost:5432/market_narrative` |
| `ANTHROPIC_API_KEY`| yes\*    | —                        | Claude API key. Missing key **fails fast** unless `APP_ENV=test`. |
| `CLAUDE_MODEL`     | no       | `claude-sonnet-5`        | Model used for classification, e.g. `claude-opus-5` or `claude-haiku-4-5`. Recorded per row in `classification_log.model`. |
| `CLAUDE_EFFORT`    | no       | `low`                    | Reasoning effort (`low`–`max`). Set empty for models without effort support (`claude-haiku-4-5`). |
| `ENABLE_SCHEDULER` | no       | `true`                   | Set `false` to run the API without the background workers. |
| `APP_ENV`          | no       | —                        | `test` permits a dummy API key (used by the test suite). |

\* The key is a sensitive credential — it is git-ignored via `.env` and must never be
committed. Claude API usage is billed per token; transient errors (rate limits, overload)
are retried by the SDK with backoff.

---

## API

All endpoints are read-only JSON. Theme path params are validated and return `404`
for unknown themes.

| Method & path        | Description |
|----------------------|-------------|
| `GET /health`        | Liveness check — `{"status": "ok"}` |
| `GET /report/daily`  | Daily narrative report: per-theme article counts, WoW growth, top companies, emerging associations |
| `GET /report/{theme}`| 7-day report for one theme: counts, top companies, emerging associations, important articles |
| `GET /articles/{theme}` | Up to 50 most important articles for a theme (last 7 days) |
| `GET /companies/{theme}` | Up to 50 top companies for a theme (last 7 days) |

OpenAPI/Swagger UI is served at `/docs`.

---

## Data model

PostgreSQL, managed by Alembic (`alembic/versions/0002_classification_log_model.py` is head).

- **`articles`** — raw ingested news (`url` unique, `processed` flag drives the queue)
- **`themes`** — the fixed narrative taxonomy (seeded; the LLM may not invent themes)
- **`companies`** — deduplicated by unique `normalized_name` and unique `ticker`
- **`article_themes`** — article↔theme with `confidence`
- **`article_companies`** — article↔company with that company's own `sentiment`
  (`positive`/`negative`/`neutral`, enforced by `ck_sentiment`) and `importance`
  (1–10, enforced by `ck_importance`)
- **`classification_log`** — every LLM response (raw + `parsed_ok` + `model`) for auditing

The migration is the source of truth for the schema; `tests/test_migration.py`
asserts the constraints and indexes the application relies on so drift is caught.

---

## Testing

The suite runs against a real PostgreSQL database (no SQLite shim). Point it at a
disposable test database:

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/market_iq_test"
export APP_ENV=test          # allows a dummy API key; no live API calls in tests
pytest -q
```

Tests use fakes for the Claude client and HTTP fetching — **no network or live LLM
calls** — so the suite is fast and deterministic.

---

## Project layout

The backend is layered so business logic stays independent of data access:
**repositories** own all database access (ORM and raw SQL, and never commit),
**services** hold the business logic and are constructed with the repositories they
need, and **routes and workers stay thin** — the API wires request-scoped
repositories and services through FastAPI dependencies, and the scheduler builds them
per run. Write-side services own the transaction boundary; no query logic lives in
routes or workers.

```
app/
  api/routes.py        FastAPI router + dependency wiring (health + report endpoints)
  main.py              app factory + scheduler lifespan + error handlers
  config.py            env-driven Settings
  db/                  SQLAlchemy models + session
  repositories/        data access only — report, theme, company, article
  services/            business logic — report, companies, taxonomy, classification,
                       ingestion (+ pure helpers: llm, body_extractor)
  workers/             scheduler orchestration
alembic/               migrations (0002 = head)
scripts/               seed_taxonomy, review_classifications
tests/                 pytest suite (Postgres-backed)
docs/                  design, architecture, CI/CD docs
frontend/              React + TypeScript dashboard (Vite, served by nginx in Docker)
  src/components/       Overview, NarrativeDetail, CompanyView, Header screens
  src/lib/              encoding helpers (acceleration, sentiment, sparkline)
  src/api.ts            typed read-API client
```
