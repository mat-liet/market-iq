# Sentiment Determination Fix + CI Quality Gate — Design

**Date:** 2026-06-30
**Status:** Approved (brainstorm)

Two independent pieces of work, each shippable as its own PR:

1. **Sentiment determination fix** — correct how the report layer derives article- and company-level sentiment from the atomic per-mention labels.
2. **CI quality gate** — a GitHub Actions workflow that runs the backend and frontend test suites on every PR and on merge to `main`. Continuous deployment (CD) is captured as a deferred follow-up, not built now.

---

## Part 1 — Sentiment determination

### Background

Sentiment exists in the data model **only** at the `article_companies` grain: each row is the model's stance (`positive` / `negative` / `neutral`) toward **one company** in **one article**. That per-mention label is the atomic, meaningful unit and does **not** change — no re-classification, no prompt change, no schema change, no Gemini calls. This is purely a report-aggregation fix in `app/services/report.py`.

Two derivations are currently wrong:

- **`top_articles`** returns `importance = MAX(ac.importance)` (from the single most-important mention) but `sentiment = majority(all the article's mentions)` (a vote across *different* companies). The two fields describe different companies, so a row can read "importance 9 / negative" where the 9 came from a positively-rated NVIDIA and the negative came from two minor names. "Article sentiment" as a majority across different entities does not represent the article's view of anything coherent.
- **`top_companies.avg_sentiment`** is a flat majority count of a company's labels (ties → neutral). It ignores `importance`, so a routine passing mention counts the same as a major story, and it discards magnitude (5-vs-4 looks identical to 5-vs-0).

### 1a. Article-level sentiment → the driving mention

Derive **both** importance and sentiment from the article's **single highest-importance mention**, so they describe the same company.

Implement by selecting one row per article with a window function:

```sql
ROW_NUMBER() OVER (
  PARTITION BY a.id
  ORDER BY ac.importance DESC NULLS LAST, c.name ASC
) AS rn
```

Take `rn = 1`. `importance` and `sentiment` both come from that row. The `c.name ASC` secondary key makes ties on equal importance deterministic and reproducible.

### 1b. Company-level sentiment → importance-weighted net score

Replace the flat majority with an **importance-weighted net score**:

- Map labels to values: `positive = +1`, `neutral = 0`, `negative = -1`.
- Weight each mention by its `importance`.
- `score = Σ(value × importance) / Σ(importance)` → a net value in `[-1, +1]`.
- Mentions with a null sentiment or null importance are excluded from both sums. If a company has no usable mentions, `score = null` and label = `null`.

**Expose both** on each company in `top_companies` / `/companies`:

- `sentiment_score` — the raw float in `[-1, +1]` (unlocks UI intensity later).
- `avg_sentiment` — the categorical label derived from the score, so the existing ▲/▼/■ glyph keeps working:
  - `score > +DEADBAND` → `positive`
  - `score < -DEADBAND` → `negative`
  - otherwise → `neutral`
  - `DEADBAND ≈ 0.15` (exact value pinned during implementation; a small band so a barely-positive net isn't reported as a confident "positive").

The weighting math lives in a small pure helper (e.g. `weighted_sentiment(mentions) -> (score, label)`) so it is unit-testable in isolation; the SQL aggregates the inputs the helper needs.

### 1c. Out of scope

- No narrative/theme-level sentiment field — none exists today and we are not inventing one here.
- No change to the LLM prompt, the stored `article_companies.sentiment` values, or the database schema.

### 1d. Testing (TDD)

- Unit tests for `weighted_sentiment`: importance dominance (a high-importance negative outweighs several low-importance positives), the deadband edges (just inside/outside → neutral vs signed), all-neutral, empty/no-usable-mentions → null.
- Tests for article driving-mention selection: the disagreement case (top mention positive, minor mentions negative → article reads positive), and the guarantee that `importance` and `sentiment` come from the same company.
- Retire / replace the existing `_majority_sentiment` tests.
- Verified against synthetic seed data — no live Gemini.

---

## Part 2 — CI quality gate (build now)

### `.github/workflows/ci.yml`

**Triggers** — on PRs targeting `main`, and on push to `main` (so the gate also runs post-merge):

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
```

**Two jobs, run in parallel:**

**Backend**
- Postgres service container (matching the app's `postgres:15`).
- Python **3.11** — matches the deploy image, not local 3.13; CI should test what ships.
- Install `requirements.txt`.
- Env: `DATABASE_URL` pointing at the service container, `APP_ENV=test` (permits the dummy Gemini key and ensures **no live LLM or network calls**).
- Run `pytest`. The suite builds its schema and the dedicated `test_migration.py` proves the Alembic migration applies cleanly.

**Frontend** (`frontend/`)
- Node **24** (matches the build image).
- `npm ci`
- `npm run lint` (oxlint)
- `npm run test` (vitest)
- `npm run build` (runs `tsc -b`, so typecheck is covered, then the production build)

No deployment. This workflow is new; it supersedes nothing. The existing `docs/market-narrative-cicd.md` describes a *combined* test + deploy `deploy.yml`; here we split the test half into a frontend-aware `ci.yml` and leave deploy for Part 3.

---

## Part 3 — CD (planned only, not built)

A single deferred task, captured so it isn't lost:

- Wire `.github/workflows/deploy.yml` per `docs/market-narrative-cicd.md` (SSH deploy on merge to `main`, GitHub secrets for the key/host).
- Update it to also build and ship the **frontend** container, which that document predates.
- Prerequisites: a reachable server and the configured secrets.

No code is written for this now.

---

## Sequencing

Three independent units; each is its own PR and they do not touch the same files:

1. **CI quality gate** (`ci.yml`) — done next, per request.
2. **Sentiment determination fix** (report layer, TDD) — follows; can interleave with (1).
3. **CD wiring** — deferred (planned, not built).
