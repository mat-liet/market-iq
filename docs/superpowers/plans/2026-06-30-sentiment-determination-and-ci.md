# Sentiment Determination Fix + CI Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct how the report layer derives article- and company-level sentiment, and add a GitHub Actions CI quality gate for the backend and frontend.

**Architecture:** Three independent units, each its own PR. (1) A GitHub Actions `ci.yml` running backend pytest and frontend lint/test/build in parallel. (2) Company-level sentiment becomes an importance-weighted net score computed by a pure helper, exposing both the score and a derived label. (3) Article-level sentiment is taken from the article's single highest-importance mention instead of a majority vote across its companies. The sentiment changes are pure report-layer aggregation in `app/services/report.py` — no schema change, no re-classification, no Gemini calls.

**Tech Stack:** Python 3.11 (CI) / 3.13 (local), SQLAlchemy 2.0 raw `text()` queries, PostgreSQL 15, pytest, GitHub Actions, Node 24, Vite/React/TypeScript, oxlint, Vitest.

**Spec:** `docs/superpowers/specs/2026-06-30-sentiment-determination-and-ci-design.md`

## Global Constraints

- Commit messages: a single one-line conventional-commit subject. Detail belongs in the PR body, not the commit.
- No AI attribution in commits or PR bodies (no `Co-Authored-By: Claude`, no "Generated with Claude Code").
- One `feature/` branch per unit; open a PR into `main`; the user reviews and merges manually. Never auto-merge or `git merge` into `main`.
- Never commit secrets. Tests and CI run with `APP_ENV=test` and a dummy/absent Gemini key — no live LLM or network calls.
- CI Python version is `3.11` (matches the deploy image). CI Node version is `24`.
- Sentiment work touches only `app/services/report.py`, its tests, and the frontend type — no database migration, no change to stored `article_companies.sentiment` values or the LLM prompt.
- Neutral deadband for the weighted-sentiment label is `0.15`.

---

## Task 1: CI quality gate workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: existing `requirements.txt` (includes pytest + httpx), `tests/` (Postgres-backed suite), `frontend/package.json` scripts (`lint`, `test`, `build`), `frontend/package-lock.json`.
- Produces: nothing other tasks depend on (standalone).

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_market_narrative
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgresql+psycopg2://test:test@localhost:5432/test_market_narrative
      APP_ENV: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run tests
        run: pytest -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "24"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run test
      - run: npm run build
```

> The backend suite builds its own schema (the session fixture in `tests/conftest.py` runs `create_all`, and `tests/test_migration.py` exercises Alembic itself), so no separate migration step is needed. `APP_ENV=test` permits the dummy Gemini key and guarantees no live LLM calls.

- [ ] **Step 2: Validate the YAML parses**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: prints `ok` (no exception).

- [ ] **Step 3: Sanity-check the two job commands locally (optional but recommended)**

Run the same commands CI will run, to confirm they pass before pushing:

```bash
# backend (needs a local Postgres; matches tests/README)
DATABASE_URL=postgresql+psycopg2://market:market@localhost:5432/market_narrative APP_ENV=test pytest -q

# frontend
cd frontend && npm ci && npm run lint && npm run test && npm run build
```

Expected: backend suite passes; frontend lint/test/build all succeed.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add backend + frontend quality gate workflow"
```

---

## Task 2: Company-level importance-weighted sentiment

**Files:**
- Modify: `app/services/report.py` (add `weighted_sentiment` helper; rewrite `top_companies` to use it and expose `sentiment_score`)
- Modify: `tests/test_report.py` (unit tests for the helper; update two `top_companies` tests)
- Modify: `frontend/src/api.ts:13-19` (add `sentiment_score` to `Company`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `weighted_sentiment(pairs: Iterable[tuple[str | None, int | None]]) -> tuple[float | None, str | None]` — returns `(score, label)`. Used again conceptually by Task 3's reviewer for consistency, but Task 3 does not call it.
  - `top_companies(...)` dicts now include `"sentiment_score": float | None` alongside the existing `"avg_sentiment": str | None`.

- [ ] **Step 1: Write the failing unit tests for the helper**

Add to `tests/test_report.py` (top of file, after the existing imports add `weighted_sentiment` to the `from app.services.report import (...)` list, then add these tests):

```python
def test_weighted_sentiment_importance_dominates():
    # one high-importance negative outweighs several low-importance positives
    score, label = weighted_sentiment([("positive", 2), ("positive", 2), ("negative", 9)])
    assert score == -0.385          # (2 + 2 - 9) / 13
    assert label == "negative"


def test_weighted_sentiment_deadband_is_neutral():
    score, label = weighted_sentiment([("positive", 8), ("negative", 8)])  # net 0
    assert score == 0.0
    assert label == "neutral"


def test_weighted_sentiment_all_positive():
    score, label = weighted_sentiment([("positive", 5), ("positive", 7)])
    assert score == 1.0
    assert label == "positive"


def test_weighted_sentiment_skips_nulls_and_empty():
    assert weighted_sentiment([]) == (None, None)
    assert weighted_sentiment([(None, 5), ("positive", None)]) == (None, None)
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `pytest tests/test_report.py -k weighted_sentiment -v`
Expected: FAIL with `ImportError: cannot import name 'weighted_sentiment'`.

- [ ] **Step 3: Implement the `weighted_sentiment` helper**

In `app/services/report.py`, add the new helper directly below the existing `_majority_sentiment` function. Do **not** remove `_majority_sentiment` in this task — `top_articles` still calls it until Task 3.

```python
_SENTIMENT_VALUE = {"positive": 1, "negative": -1, "neutral": 0}
_NEUTRAL_DEADBAND = 0.15


def weighted_sentiment(pairs) -> tuple[float | None, str | None]:
    """Importance-weighted net sentiment for a set of mentions.

    `pairs` is an iterable of (sentiment, importance). Each sentiment maps to
    +1/0/-1 (positive/neutral/negative) and is weighted by its importance.
    Mentions with a null/unknown sentiment or null importance are ignored.

    Returns (score, label):
      score — net value in [-1.0, 1.0] rounded to 3 dp, or None if no usable mentions
      label — 'positive'/'negative'/'neutral' from the score (deadband), or None
    """
    numerator = 0.0
    weight = 0.0
    for sentiment, importance in pairs:
        if importance is None:
            continue
        value = _SENTIMENT_VALUE.get(sentiment)
        if value is None:
            continue
        numerator += value * importance
        weight += importance
    if weight == 0:
        return None, None
    score = round(numerator / weight, 3)
    if score > _NEUTRAL_DEADBAND:
        label = "positive"
    elif score < -_NEUTRAL_DEADBAND:
        label = "negative"
    else:
        label = "neutral"
    return score, label
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `pytest tests/test_report.py -k weighted_sentiment -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Update the two existing `top_companies` tests for the new contract**

In `tests/test_report.py`, replace `test_top_companies_includes_avg_sentiment_and_importance` and `test_top_companies_avg_sentiment_tie_is_neutral` with:

```python
def test_top_companies_includes_avg_sentiment_and_importance(session):
    seed_taxonomy(session)
    _tag(session, "a1", 1, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 8)])
    _tag(session, "a2", 2, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 6)])

    rows = top_companies(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    nvda = next(r for r in rows if r["ticker"] == "NVDA")
    assert nvda["mentions"] == 2
    assert nvda["avg_importance"] == 7.0       # (8 + 6) / 2
    assert nvda["avg_sentiment"] == "positive"
    assert nvda["sentiment_score"] == 1.0      # all positive -> +1


def test_top_companies_sentiment_is_importance_weighted(session):
    seed_taxonomy(session)
    # equal-but-opposite importance nets to zero -> neutral (within deadband)
    _tag(session, "a1", 1, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 8)])
    _tag(session, "a2", 2, "AI Infrastructure", [("NVIDIA", "NVDA", "negative", 8)])

    rows = top_companies(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    nvda = next(r for r in rows if r["ticker"] == "NVDA")
    assert nvda["sentiment_score"] == 0.0
    assert nvda["avg_sentiment"] == "neutral"
```

- [ ] **Step 6: Run those tests to verify they fail**

Run: `pytest tests/test_report.py -k "top_companies" -v`
Expected: FAIL — `KeyError: 'sentiment_score'` (the key isn't returned yet).

- [ ] **Step 7: Rewrite `top_companies` to weight by importance and expose the score**

In `app/services/report.py`, replace the `top_companies` function body. Change the SQL to aggregate aligned `sentiment` and `importance` arrays, and build the result with `weighted_sentiment`:

```python
def top_companies(session, theme_name: str, start: datetime, end: datetime, limit: int = 5):
    rows = session.execute(text("""
        SELECT c.name, c.ticker,
               COUNT(*) AS mentions,
               ROUND(AVG(ac.importance) FILTER (WHERE ac.importance IS NOT NULL), 1) AS avg_importance,
               array_agg(ac.sentiment ORDER BY ac.article_id, ac.company_id) AS sentiments,
               array_agg(ac.importance ORDER BY ac.article_id, ac.company_id) AS importances
        FROM article_companies ac
        JOIN companies c ON c.id = ac.company_id
        JOIN article_themes at ON at.article_id = ac.article_id
        JOIN themes t ON t.id = at.theme_id
        JOIN articles a ON a.id = ac.article_id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
        GROUP BY c.name, c.ticker
        ORDER BY mentions DESC
        LIMIT :limit
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    result = []
    for r in rows:
        score, label = weighted_sentiment(zip(r["sentiments"] or [], r["importances"] or []))
        result.append({
            "name": r["name"],
            "ticker": r["ticker"],
            "mentions": int(r["mentions"]),
            "avg_importance": float(r["avg_importance"]) if r["avg_importance"] is not None else None,
            "avg_sentiment": label,
            "sentiment_score": score,
        })
    return result
```

> The two `array_agg`s share an identical `ORDER BY`, so the `sentiments` and `importances` arrays are positionally aligned — `zip` pairs each mention's sentiment with its own importance.

- [ ] **Step 8: Run the report tests to verify they pass**

Run: `pytest tests/test_report.py -v`
Expected: PASS (all report tests, including the updated `top_companies` ones and the helper tests).

- [ ] **Step 9: Add `sentiment_score` to the frontend `Company` type**

In `frontend/src/api.ts`, update the `Company` interface (lines 13-19):

```typescript
/** A company aggregate (top_companies / GET /companies). */
export interface Company {
  name: string
  ticker: string | null
  mentions: number
  avg_importance: number | null
  avg_sentiment: Sentiment | null
  sentiment_score: number | null // importance-weighted net sentiment, -1..1
}
```

- [ ] **Step 10: Verify the frontend still type-checks and builds**

Run: `cd frontend && npm run build`
Expected: `tsc -b` passes and the Vite build succeeds (adding an optional-to-consume field is non-breaking; no component reads it yet).

- [ ] **Step 11: Commit**

```bash
git add app/services/report.py tests/test_report.py frontend/src/api.ts
git commit -m "feat: importance-weighted company sentiment with exposed score"
```

---

## Task 3: Article-level driving-mention sentiment

**Files:**
- Modify: `app/services/report.py` (rewrite `top_articles`; remove the now-unused `_majority_sentiment`)
- Modify: `tests/test_report.py` (replace the tie test; add a tiebreak test)

**Interfaces:**
- Consumes: nothing from other tasks (independent of Task 2; both only touch `report.py` in non-overlapping functions).
- Produces: `top_articles(...)` dicts unchanged in shape — `importance` and `sentiment` now both come from the article's single highest-importance mention.

- [ ] **Step 1: Replace the article tie test and add a tiebreak test**

In `tests/test_report.py`, replace `test_top_articles_sentiment_tie_is_neutral` with these two tests:

```python
def test_top_articles_sentiment_from_driving_mention(session):
    seed_taxonomy(session)
    # NVIDIA is the highest-importance mention -> it drives BOTH importance and sentiment
    _tag(session, "art1", 1, "AI Infrastructure",
         [("NVIDIA", "NVDA", "positive", 9), ("Eaton", "ETN", "negative", 3)])

    rows = top_articles(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert rows[0]["importance"] == 9
    assert rows[0]["sentiment"] == "positive"   # from NVIDIA, not a majority vote


def test_top_articles_importance_tie_broken_by_company_name(session):
    seed_taxonomy(session)
    # equal importance -> deterministic tiebreak by company name ASC (Eaton < NVIDIA)
    _tag(session, "art1", 1, "AI Infrastructure",
         [("NVIDIA", "NVDA", "positive", 8), ("Eaton", "ETN", "negative", 8)])

    rows = top_articles(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert rows[0]["importance"] == 8
    assert rows[0]["sentiment"] == "negative"   # Eaton wins the tie
```

- [ ] **Step 2: Run these tests to verify they fail**

Run: `pytest tests/test_report.py -k "driving_mention or tie_broken_by_company" -v`
Expected: FAIL — the current majority-vote logic returns `neutral` for the tie case (and may mismatch importance), so the assertions fail.

- [ ] **Step 3: Rewrite `top_articles` to use the highest-importance mention**

In `app/services/report.py`, replace the `top_articles` function. Use `DISTINCT ON` to pick one mention per article (highest importance, ties broken by company name), then order the surviving rows for the limit:

```python
def top_articles(session, theme_name: str, start: datetime, end: datetime, limit: int = 3):
    # One row per article: its single highest-importance mention drives both the
    # importance and the sentiment, so the two describe the same company. Ties on
    # importance are broken deterministically by company name.
    rows = session.execute(text("""
        SELECT title, url, source, published_at, importance, sentiment
        FROM (
            SELECT DISTINCT ON (a.id)
                   a.id, a.title AS title, a.url AS url, a.source AS source,
                   a.published_at AS published_at,
                   ac.importance AS importance, ac.sentiment AS sentiment
            FROM articles a
            JOIN article_themes at ON at.article_id = a.id
            JOIN themes t ON t.id = at.theme_id
            LEFT JOIN article_companies ac ON ac.article_id = a.id
            LEFT JOIN companies c ON c.id = ac.company_id
            WHERE t.name = :theme
              AND a.published_at >= :start AND a.published_at < :end
            ORDER BY a.id, ac.importance DESC NULLS LAST, c.name ASC
        ) sub
        ORDER BY importance DESC NULLS LAST
        LIMIT :limit
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    return [{
        "title": r["title"],
        "url": r["url"],
        "source": r["source"],
        "published_at": _iso(r["published_at"]),
        "importance": int(r["importance"]) if r["importance"] is not None else None,
        "sentiment": r["sentiment"],
    } for r in rows]
```

> `DISTINCT ON (a.id)` keeps the first row per article under the inner `ORDER BY`, i.e. the highest-importance mention (name-ascending on ties). The outer query then ranks the per-article rows for the `LIMIT`. Articles with no company mentions survive the `LEFT JOIN` with `importance`/`sentiment` = `NULL`.

- [ ] **Step 4: Remove the now-unused `_majority_sentiment`**

`top_articles` was the last caller. Delete the `_majority_sentiment` function (the `def _majority_sentiment(...)` block) from `app/services/report.py`. The `from collections import Counter` import was only used by it — remove that import line too.

- [ ] **Step 5: Run the full report suite to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: PASS. Note these existing tests still hold under the new logic:
- `test_top_articles_includes_source_published_and_sentiment` — single mention NVIDIA positive/8 → driving mention is NVIDIA → `sentiment == "positive"`, `importance == 8`.
- `test_top_articles_dedups_multi_company_article` — both companies importance 7 → still one row per article, `importance == 7`.

- [ ] **Step 6: Run the whole backend suite to confirm nothing else regressed**

Run: `pytest -q`
Expected: PASS (full suite green; `test_api.py` report endpoints still return their shapes).

- [ ] **Step 7: Commit**

```bash
git add app/services/report.py tests/test_report.py
git commit -m "feat: article sentiment from highest-importance mention"
```

---

## Self-Review notes (coverage map)

- Spec 1a (article = driving mention; importance + sentiment same company) → Task 3.
- Spec 1b (importance-weighted net score; expose `sentiment_score` + derived `avg_sentiment` with 0.15 deadband) → Task 2.
- Spec 1c (no schema/LLM/narrative-level change) → respected; only `report.py`, its tests, and the frontend type change.
- Spec 1d (TDD; helper + driving-mention tests; retire `_majority_sentiment`; synthetic data) → Tasks 2 & 3.
- Spec Part 2 (CI: triggers on PR + push to main; backend py3.11/pytest/APP_ENV=test/Postgres service; frontend node24 ci/lint/test/build; parallel; no deploy) → Task 1.
- Spec Part 3 (CD planned only) → Deferred Follow-up below; intentionally no task.

## Deferred Follow-up (not built in this plan)

- **CD — `.github/workflows/deploy.yml`.** Wire SSH deploy on merge to `main` per `docs/market-narrative-cicd.md` (secrets: `VPS_HOST`, `VPS_USER`, `SSH_PRIVATE_KEY`), updated to also build/serve the `frontend` container the doc predates. Requires a reachable server and configured secrets. Not implemented here.
