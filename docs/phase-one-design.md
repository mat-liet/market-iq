# Market Narrative Intelligence Platform — Phase 1 Technical Design

## Overview

A platform that identifies and tracks emerging market narratives from financial news and maps them to companies. Phase 1 focuses exclusively on the data collection and narrative extraction foundation. No prediction engine or trading signals.

**Core hypothesis:** Accelerating narratives provide valuable investment research signals before they are fully reflected in market consensus.

**Phase 1 goal:** Build a structured database of articles, themes, companies, and sentiment that can later be used for analytics, trend detection, and backtesting.

---

## Architecture

```
RSS Feeds
SEC EDGAR         →  Ingestion Worker  →  Raw Articles (PostgreSQL)
NewsAPI                                              ↓
                                        Classification Worker (Gemini Flash)
                                                     ↓
                                        Structured Signals (PostgreSQL)
                                                     ↓
                                        Report Generator (daily cron)
                                                     ↓
                                        FastAPI  →  React Dashboard (optional)
```

### Key Design Decisions

- **Decouple ingestion from classification.** Two separate workers means classification can be re-run with a new prompt or model without re-fetching articles.
- **`processed` boolean as a lightweight queue.** Sufficient for Phase 1 volumes. Replace with SQS/RabbitMQ when throughput demands it.
- **Log all raw LLM responses.** Store alongside parsed output for debugging extraction failures.

---

## Data Model

```sql
-- Core article store
CREATE TABLE articles (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url           TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT,
    source        TEXT,
    published_at  TIMESTAMPTZ NOT NULL,   -- backfilled with ingested_at when the feed gives no parseable date
    ingested_at   TIMESTAMPTZ DEFAULT NOW(),
    processed     BOOLEAN DEFAULT FALSE
);

-- Narrative taxonomy
CREATE TABLE themes (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name      TEXT UNIQUE NOT NULL,
    keywords  TEXT[]
);

-- Company registry (populated as discovered)
CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,           -- display name as first seen
    ticker          TEXT,                    -- may be null when the LLM can't resolve one
    normalized_name TEXT NOT NULL            -- lowercased, legal suffixes (Corp/Inc/Ltd/plc) stripped; used for dedup
);

-- Article → Theme relationship
CREATE TABLE article_themes (
    article_id   UUID REFERENCES articles(id),
    theme_id     UUID REFERENCES themes(id),
    confidence   FLOAT,
    PRIMARY KEY (article_id, theme_id)
);

-- Article → Company relationship
CREATE TABLE article_companies (
    article_id  UUID REFERENCES articles(id),
    company_id  UUID REFERENCES companies(id),
    sentiment   TEXT CHECK (sentiment IN ('positive', 'negative', 'neutral')),
    importance  INT CHECK (importance BETWEEN 1 AND 10),
    PRIMARY KEY (article_id, company_id)
);

-- Raw LLM response log (for debugging)
CREATE TABLE classification_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id   UUID REFERENCES articles(id),
    raw_response TEXT,
    parsed_ok    BOOLEAN,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_articles_processed ON articles(processed);
CREATE INDEX idx_articles_published ON articles(published_at);
CREATE INDEX idx_article_themes_theme ON article_themes(theme_id);
CREATE INDEX idx_article_companies_company ON article_companies(company_id);

-- Company identity / dedup: ticker-first, normalized-name fallback
CREATE UNIQUE INDEX idx_companies_ticker ON companies(ticker) WHERE ticker IS NOT NULL;
CREATE UNIQUE INDEX idx_companies_normalized_name ON companies(normalized_name);
```

### Notes

- `confidence` on `article_themes` is captured from day one — essential for thresholding when building acceleration metrics in Phase 2.
- `reason` from the LLM (see Classification section) is stored in the classification log, not the main schema. It's a debugging and report-quality tool, not a first-class signal yet.
- **Company identity (dedup):** the classification worker upserts companies **ticker-first** — match on `ticker` when the LLM supplies one, otherwise match on `normalized_name`. Without this, "NVIDIA" / "Nvidia" / "Nvidia Corp" fragment into separate rows and corrupt the mention counts the whole report depends on. `normalized_name` = lowercased with legal suffixes (Corp, Inc, Ltd, plc) stripped.
- **Time basis for trends:** `published_at` is `NOT NULL`. When a feed gives no parseable publish date, the ingestion worker backfills it with `ingested_at` at write time. All trend queries (this-week vs last-week, WoW growth, emerging associations) run off `published_at`, so no article is silently dropped from the counts.
- **Unknown themes:** the worker maps the LLM's theme names to seeded `themes` rows by name and **skips + logs** any theme not in the taxonomy. No new theme rows are created at classification time — the prompt already forbids inventing themes, this is the defensive backstop.

---

## Narrative Taxonomy

Manually curated starting taxonomy. Expand over time.

```python
TAXONOMY = {
    "AI Infrastructure": [
        "artificial intelligence", "LLM", "large language model",
        "GPU", "datacentre", "data center", "inference",
        "foundation model", "AI chips", "NVIDIA", "accelerator"
    ],
    "Nuclear Energy": [
        "uranium", "SMR", "small modular reactor",
        "nuclear power", "reactor", "nuclear energy",
        "enriched uranium", "nuclear plant"
    ],
    "Defence Spending": [
        "defence budget", "defense budget", "military spending",
        "missile systems", "defence contracts", "defense contracts",
        "NATO spending", "military procurement", "arms"
    ],
}
```

> Both US and UK spellings are included (defence/defense, datacentre/data center). RSS feeds mix both.

---

## Third-Party Integrations

| Integration                     | Type           | Cost      | Purpose                          |
| ------------------------------- | -------------- | --------- | -------------------------------- |
| Gemini Flash (Google AI Studio) | API            | Free tier | LLM classification               |
| feedparser                      | Python library | Free      | RSS feed parsing                 |
| trafilatura                     | Python library | Free      | Full article body extraction     |
| SEC EDGAR                       | REST API       | Free      | Earnings filings (optional)      |
| NewsAPI                         | REST API       | Free tier | Broader news coverage (optional) |

### Gemini Flash Free Tier Limits

| Limit               | Value |
| ------------------- | ----- |
| Requests per minute | 15    |
| Requests per day    | 1,500 |
| Cost                | £0    |

At ~1,000 articles/day, the free tier is sufficient for Phase 1. Get an API key at `aistudio.google.com` — no credit card required.

> If you exceed 1,500 articles/day, prioritise classification by filtering out articles under 150 words before sending to the API. Short articles rarely contain enough substance to classify reliably anyway.

### RSS Feed Sources

```python
RSS_SOURCES = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://finance.yahoo.com/rss/",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
]
```

> ⚠️ **Feed URLs are not guaranteed live.** Reuters discontinued its public RSS feeds (`feeds.reuters.com`), and Yahoo/MarketWatch feed paths shift over time. Treat `RSS_SOURCES` as config-driven, and include an early build task that **verifies each feed actually returns entries** before relying on it. Swap in working financial-news feeds as needed; the architecture doesn't care which feeds, only that they parse.

---

## Workers

### Ingestion Worker

Runs every 30 minutes via APScheduler.

```python
def ingest():
    for feed_url in RSS_SOURCES:
        articles = feedparser.parse(feed_url).entries
        for entry in articles:
            if already_seen(entry.link):
                continue
            body = trafilatura.fetch_url(entry.link)  # full article text
            store_raw({
                "url": entry.link,
                "title": entry.title,
                "body": body,
                "source": source_name,
                "published_at": entry.published,
                "processed": False,
            })
```

**Deduplication:** by URL. Sufficient for Phase 1.
**Error handling:** log every feed attempt with success/failure. Gaps in ingestion corrupt trend lines.
**Body extraction is the flakiest dependency.** `trafilatura.fetch_url` hits paywalls, bot-blocking, and timeouts. Isolate it behind a `body_extractor` interface and **fall back to the RSS summary** when extraction fails — a blocked source must never halt ingestion or drop the article. (Missing `published_at` is backfilled with `ingested_at` here too; see Data Model notes.)

---

### Classification Worker

Runs every 15 minutes. Processes unclassified articles in batches, respecting Gemini rate limits.

```python
import time

def process_unclassified():
    # Batch size of 10 keeps well within 15 requests/minute limit
    articles = db.query(
        "SELECT * FROM articles WHERE processed = FALSE LIMIT 10"
    )
    for article in articles:
        raw_response = call_gemini(article)
        log_raw_response(article.id, raw_response)
        result = parse_response(raw_response)
        if result:
            store_classifications(article.id, result)
        mark_processed(article.id)
        time.sleep(4)  # 4 second delay = max 15 requests/minute
```

**Batch size:** 10 articles per run, with a 4-second delay between calls. This stays safely within the 15 requests/minute free tier limit.
**Retry logic:** exponential backoff on API failures (2s, 4s, 8s). Gemini occasionally returns 429 (rate limit) — handle gracefully.

---

## LLM Classification

### Gemini Flash Setup

```python
from google import genai
from google.genai import types
import os

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def call_gemini(article: dict) -> str:
    prompt = build_prompt(article)
    response = client.models.generate_content(
        model="gemini-flash-latest",   # confirm the current Flash model id at build time (see note)
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,       # Low temperature for consistent structured output
            max_output_tokens=300, # Classification JSON is small; cap to save quota
        ),
    )
    return response.text
```

> Install with: `pip install google-genai`
>
> **SDK note:** This uses the current `google-genai` SDK (client-based API). The older `google-generativeai` package (`genai.configure` / `GenerativeModel`) is deprecated — do not use it. Confirm the exact current Flash model id against Google's model list when implementing; pin it once chosen so classification stays consistent.

**Why `temperature=0.1`:** You want deterministic, consistent JSON output — not creative responses. Low temperature keeps the model on-task.

---

### Prompt Design

```python
def build_prompt(article: dict) -> str:
    taxonomy_str = "\n".join(
        f"- {name}: {', '.join(keywords)}"
        for name, keywords in TAXONOMY.items()
    )

    return f"""
You are a financial news analyst. Extract structured information from the article below.

Available narratives — only assign from this list, do not invent new ones:
{taxonomy_str}

Return JSON only. No explanation, no markdown, no preamble.

{{
  "themes": [
    {{"name": "<narrative name>", "confidence": <0.0-1.0>}}
  ],
  "companies": [
    {{"name": "<company name>", "ticker": "<ticker or null>"}}
  ],
  "sentiment": "<positive|negative|neutral>",
  "importance": <1-10>,
  "reason": "<one sentence: why this article matters>"
}}

Rules:
- Only assign a theme if the article is substantively about it, not a passing mention.
- Confidence > 0.7 means the theme is central to the article.
- Importance 8-10 = major announcement or policy shift. 1-3 = routine or minor.
- If no themes match, return an empty themes array.

Article title: {article['title']}
Article body: {article['body']}
"""
```

### Response Parsing

Gemini occasionally wraps JSON in markdown code fences even when instructed not to. Strip them defensively:

````python
import json
import re

def parse_response(raw: str) -> dict | None:
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"```json|```", "", raw).strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        log_parse_failure(raw)
        return None
````

### Example Output

```json
{
  "themes": [{ "name": "AI Infrastructure", "confidence": 0.92 }],
  "companies": [
    { "name": "Microsoft", "ticker": "MSFT" },
    { "name": "NVIDIA", "ticker": "NVDA" }
  ],
  "sentiment": "positive",
  "importance": 8,
  "reason": "Microsoft announces $10bn datacentre expansion, directly increasing demand for AI accelerator chips."
}
```

### Prompt Notes

- Taxonomy is injected explicitly — Gemini is constrained to your defined narratives, not free to invent.
- The `reason` field forces justification of the importance score and surfaces misclassifications during manual review.
- Full article body via trafilatura significantly improves accuracy over RSS summaries.
- The JSON stripping in `parse_response` is important — Gemini ignores "no markdown" instructions more often than Claude or GPT-4.

---

## Report Generator

Runs daily at 07:00 UTC via cron. Outputs JSON and optionally a formatted digest.

```python
def generate_daily_report(date):
    report = {}

    for theme in get_all_themes():
        this_week   = count_articles(theme, last_7_days)
        last_week   = count_articles(theme, prior_7_days)
        wow_growth  = (this_week - last_week) / max(last_week, 1) * 100

        top_companies      = get_top_companies(theme, last_7_days, limit=5)
        emerging           = get_emerging_associations(theme)  # see query below
        important_articles = get_top_articles(theme, by="importance", limit=3)

        report[theme.name] = {
            "article_count":         this_week,
            "wow_growth_pct":        round(wow_growth, 1),
            "top_companies":         top_companies,
            "emerging_associations": emerging,
            "important_articles":    important_articles,
        }

    return report
```

### Emerging Association Query

Finds companies newly associated with a theme this week that had no association in the prior three weeks. This is the highest-value output of Phase 1.

```sql
SELECT c.name, c.ticker, COUNT(*) as mention_count
FROM article_companies ac
JOIN companies c ON c.id = ac.company_id
JOIN article_themes at ON at.article_id = ac.article_id
JOIN themes t ON t.id = at.theme_id
WHERE t.name = :theme_name
  AND ac.article_id IN (
      SELECT id FROM articles
      WHERE published_at >= NOW() - INTERVAL '7 days'
  )
  AND c.id NOT IN (
      SELECT ac2.company_id
      FROM article_companies ac2
      JOIN article_themes at2 ON at2.article_id = ac2.article_id
      JOIN themes t2 ON t2.id = at2.theme_id
      WHERE t2.name = :theme_name
        AND ac2.article_id IN (
            SELECT id FROM articles
            WHERE published_at < NOW() - INTERVAL '7 days'
              AND published_at >= NOW() - INTERVAL '28 days'
        )
  )
GROUP BY c.name, c.ticker
ORDER BY mention_count DESC;
```

### Example Report Output

```
=== AI Infrastructure ===
Articles this week:  142  (+28% vs last week)

Top companies:
  1. NVIDIA       (87 mentions)
  2. Microsoft    (64 mentions)
  3. AMD          (41 mentions)
  4. TSMC         (29 mentions)
  5. Broadcom     (22 mentions)

Emerging associations:
  → Eaton Corporation (EATON) — 6 mentions, first appearance in narrative

Most important articles:
  [9/10] Microsoft announces $10bn datacentre expansion
         "Directly increases demand for AI accelerator chips."
  [8/10] TSMC reports record Q2 revenue driven by AI chip orders
         "Confirms sustained demand acceleration from hyperscalers."
  [7/10] EU announces AI infrastructure investment framework
         "Regulatory tailwind for European datacentre buildout."
```

---

## Tech Stack

| Layer              | Technology                          | Notes                             |
| ------------------ | ----------------------------------- | --------------------------------- |
| Language           | Python 3.11+                        | ML ecosystem, LLM SDKs            |
| Framework          | FastAPI                             | API layer for report endpoints    |
| Database           | PostgreSQL 15                       | Primary store                     |
| Migrations         | Alembic                             | Schema version control            |
| Scheduling         | APScheduler                         | In-process cron for workers       |
| RSS Parsing        | feedparser                          | Ingestion                         |
| Article Extraction | trafilatura                         | Full body text                    |
| LLM                | Gemini Flash (Google AI Studio)     | Classification — free tier, `google-genai` SDK |
| Containerisation   | Docker + Docker Compose             | Local and VPS deployment          |
| Hosting            | Hetzner / Railway / Render          | Single VPS sufficient for Phase 1 |
| Frontend           | React (optional Phase 1)            | Dashboard                         |

---

## Project Structure

```
market-narrative/
├── docker-compose.yml
├── .env                         # GEMINI_API_KEY, DATABASE_URL
├── alembic/
│   └── versions/
├── app/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Settings, env vars
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models
│   │   └── session.py           # DB connection
│   ├── workers/
│   │   ├── ingestion.py         # RSS ingestion worker
│   │   └── classification.py    # Gemini classification worker
│   ├── services/
│   │   ├── llm.py               # Gemini client + prompt + response parsing
│   │   ├── body_extractor.py    # full-text extraction w/ RSS-summary fallback
│   │   ├── report.py            # Report generator
│   │   └── taxonomy.py          # Narrative taxonomy + seed
│   └── api/
│       └── routes.py            # FastAPI routes
├── scripts/
│   └── review_classifications.py  # quality-gate CLI (build step 3 checkpoint)
└── tests/
    ├── test_ingestion.py
    ├── test_classification.py
    └── test_report.py
```

### Environment Variables

```bash
# .env
GEMINI_API_KEY=your_key_from_aistudio.google.com
DATABASE_URL=postgresql://user:password@localhost:5432/market_narrative
```

---

## Build Order

Build in this sequence. Do not start the next step until the current one produces trustworthy output.

1. **Database schema + Alembic migrations**
2. **RSS ingestion for one source** (Reuters only) — store raw articles
3. **Manual classification test** — run the Gemini prompt against 20 hand-picked articles, score accuracy before automating
4. **Classification worker** — automate for all ingested articles, respecting rate limits
5. **Add remaining RSS sources** (Yahoo Finance, MarketWatch)
6. **Report generator** — start as a terminal script, not an API
7. **FastAPI endpoints** — expose report as JSON
8. **React dashboard** — only once the data quality passes the smell test

> Do not build the dashboard until Step 7. Spend that time on extraction quality instead. Everything downstream depends on it.

---

## Quality Control

### Weekly Manual Review

Sample 50 random articles per week. Score each classification:

| Score      | Meaning                                  |
| ---------- | ---------------------------------------- |
| ✅ Correct | Theme and companies correctly identified |
| ⚠️ Partial | Theme correct, companies missed or added |
| ❌ Wrong   | Theme misclassified or hallucinated      |

Target: >85% correct before building Phase 2 analytics.

### Gemini-Specific Watch Points

- **JSON wrapping:** Gemini sometimes returns ` ```json ``` ` fences despite being told not to. The `parse_response` function handles this, but monitor `parsed_ok = FALSE` rows in `classification_log` to catch new failure patterns.
- **Confidence calibration:** Gemini's confidence scores tend to skew high. If you find >90% of scores are above 0.8, lower your confidence threshold accordingly rather than trusting the raw numbers.
- **Rate limit 429s:** If the classification worker hits a 429, back off for 60 seconds before retrying. Log these occurrences — frequent 429s mean your batch cadence is too aggressive.

### Confidence Thresholding

Only include `article_themes` with `confidence >= 0.6` in report queries. Tune this threshold based on manual review results.

### Ingestion Health Check

Log every feed fetch attempt. Alert (email or Slack) if any source fails three consecutive fetches. Data gaps corrupt trend lines.

---

## Cost Estimates

| Item                        | Volume              | Est. Cost      |
| --------------------------- | ------------------- | -------------- |
| Gemini Flash classification | ~1,000 articles/day | £0 (free tier) |
| PostgreSQL (Hetzner VPS)    | 4GB RAM VPS         | ~£5/month      |
| NewsAPI (optional)          | Free tier           | £0             |
| SEC EDGAR (optional)        | Free                | £0             |

**Total Phase 1 running cost: ~£5/month.**

> If you later outgrow the free tier (1,500 requests/day), Gemini Flash paid pricing is significantly cheaper than Claude or GPT-4. Upgrading doesn't require changing any code — just billing details in Google AI Studio.

---

## Phase 1 Success Criteria

- [ ] Articles are automatically collected from at least three sources
- [ ] Articles are classified into narratives with >85% accuracy (manual review)
- [ ] Companies are extracted reliably with correct ticker mapping
- [ ] Emerging company-theme associations are correctly identified
- [ ] Daily narrative report can be generated and passes a smell test
- [ ] The system produces insights that are useful for manual investment research

**The validation gate for Phase 2:** The narratives showing acceleration in the data should match what you're observing in the financial press. If they don't, fix extraction quality before building acceleration metrics.

---

## Out of Scope for Phase 1

- Narrative acceleration metrics and scoring
- Backtesting against price data
- Reddit / X / social media ingestion
- Semantic similarity or vector search
- Trading signals or recommendations
- Multi-user access or authentication
- Message queues (SQS / RabbitMQ)
- Cloud infrastructure (AWS / GCP)
