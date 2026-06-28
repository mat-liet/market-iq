# Market Narrative Intelligence

A backend that ingests financial news, uses an LLM to classify each article into a
fixed taxonomy of **market narratives**, maps those narratives to **companies** with
sentiment and importance, and exposes the result as **narrative reports** over a REST
API.

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
   (Gemini Flash)
        │  themes + companies + sentiment/importance
        ▼
 Structured signals (PostgreSQL)
        │
        ▼
 Report generator  ──►  FastAPI read API
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

The fastest path — Postgres and the app come up together, migrations and taxonomy
seeding run automatically on startup.

```bash
cp .env.example .env          # then edit GEMINI_API_KEY
docker compose up --build
```

The API is then available at <http://localhost:8000>. Interactive docs at
<http://localhost:8000/docs>.

On startup the container entrypoint (`docker-entrypoint.sh`) runs
`alembic upgrade head` and seeds the taxonomy (idempotent) **before** serving, so a
fresh database comes up fully usable.

---

## Local development

Requires **Python 3.13** (the Docker image uses 3.11) and a reachable **PostgreSQL 15**.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # edit DATABASE_URL + GEMINI_API_KEY
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

---

## Configuration

Configuration is read from the environment (see `app/config.py` and `.env.example`):

| Variable           | Required | Default                  | Notes |
|--------------------|----------|--------------------------|-------|
| `DATABASE_URL`     | yes      | —                        | SQLAlchemy URL, e.g. `postgresql://market:market@localhost:5432/market_narrative` |
| `GEMINI_API_KEY`   | yes\*    | —                        | Google AI Studio key. Missing key **fails fast** unless `APP_ENV=test`. |
| `GEMINI_MODEL`     | no       | `gemini-2.5-flash-lite`  | Flash-lite avoids JSON truncation from thinking tokens on the free tier. |
| `ENABLE_SCHEDULER` | no       | `true`                   | Set `false` to run the API without the background workers. |
| `APP_ENV`          | no       | —                        | `test` permits a dummy Gemini key (used by the test suite). |

\* The key is a sensitive credential — it is git-ignored via `.env` and must never be
committed. The free tier allows **20 generate-content requests/day per model**, so
classification batches are sized and paced accordingly.

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

PostgreSQL, managed by Alembic (`alembic/versions/0001_initial_schema.py` is head).

- **`articles`** — raw ingested news (`url` unique, `processed` flag drives the queue)
- **`themes`** — the fixed narrative taxonomy (seeded; the LLM may not invent themes)
- **`companies`** — deduplicated by unique `normalized_name` and unique `ticker`
- **`article_themes`** — article↔theme with `confidence`
- **`article_companies`** — article↔company with `sentiment`
  (`positive`/`negative`/`neutral`, enforced by `ck_sentiment`) and `importance`
  (1–10, enforced by `ck_importance`)
- **`classification_log`** — every LLM response (raw + `parsed_ok`) for auditing

The migration is the source of truth for the schema; `tests/test_migration.py`
asserts the constraints and indexes the application relies on so drift is caught.

---

## Testing

The suite runs against a real PostgreSQL database (no SQLite shim). Point it at a
disposable test database:

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/market_iq_test"
export APP_ENV=test          # allows a dummy Gemini key; no live API calls in tests
pytest -q
```

Tests use fakes for the Gemini client and HTTP fetching — **no network or live LLM
calls** — so the suite is fast and deterministic.

---

## Project layout

```
app/
  api/routes.py        FastAPI router (health + report endpoints)
  main.py              app factory + scheduler lifespan wiring
  config.py            env-driven Settings
  db/                  SQLAlchemy models + session
  services/            body_extractor, llm, companies, taxonomy, report
  workers/             ingestion, classification, scheduler
alembic/               migrations (0001 = head)
scripts/               seed_taxonomy, review_classifications
tests/                 pytest suite (Postgres-backed)
docs/                  design, architecture, CI/CD docs
```
