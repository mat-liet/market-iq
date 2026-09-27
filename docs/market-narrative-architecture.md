# Market Narrative Intelligence Platform — Architecture Diagram

## Full System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL DATA SOURCES                       │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ Reuters RSS  │  │ Yahoo Finance│  │  MarketWatch │             │
│  │     Feed     │  │   RSS Feed   │  │   RSS Feed   │             │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             │
│         │                 │                  │                      │
│  ┌──────┴─────────────────┴──────────────────┴──────┐              │
│  │              NewsAPI (optional)                   │              │
│  │              SEC EDGAR (optional)                 │              │
│  └───────────────────────────┬───────────────────────┘             │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                              │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Ingestion Worker                         │   │
│  │                  (runs every 30 min)                        │   │
│  │                                                             │   │
│  │   feedparser → fetch feed entries                          │   │
│  │   trafilatura → extract full article body from URL         │   │
│  │   deduplication → skip already-seen URLs                   │   │
│  │   store → write raw article to database                    │   │
│  └─────────────────────────────┬───────────────────────────────┘   │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                               │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    PostgreSQL Database                       │  │
│  │                                                              │  │
│  │   ┌─────────────┐      ┌──────────────┐                    │  │
│  │   │   articles  │      │    themes    │                    │  │
│  │   │─────────────│      │──────────────│                    │  │
│  │   │ id          │      │ id           │                    │  │
│  │   │ url         │      │ name         │                    │  │
│  │   │ title       │      │ keywords[]   │                    │  │
│  │   │ body        │      └──────┬───────┘                    │  │
│  │   │ source      │             │                            │  │
│  │   │ published_at│      ┌──────┴───────────┐               │  │
│  │   │ processed ◄─┼──┐   │  article_themes  │               │  │
│  │   └──────┬──────┘  │   │──────────────────│               │  │
│  │          │         │   │ article_id        │               │  │
│  │          │         │   │ theme_id          │               │  │
│  │   ┌──────┴──────┐  │   │ confidence        │               │  │
│  │   │  companies  │  │   └──────────────────┘               │  │
│  │   │─────────────│  │                                       │  │
│  │   │ id          │  │   ┌──────────────────┐               │  │
│  │   │ name        │  │   │article_companies │               │  │
│  │   │ ticker      │  │   │──────────────────│               │  │
│  │   │ norm_name   │  │   │ article_id        │               │  │
│  │   └─────────────┘  │   │ company_id        │               │  │
│  │                    │   │ sentiment         │               │  │
│  │   ┌─────────────┐  │   │ importance        │               │  │
│  │   │classif_log  │  │   │ importance        │               │  │
│  │   │─────────────│  │   └──────────────────┘               │  │
│  │   │ article_id  │  │                                       │  │
│  │   │ raw_response│  │                                       │  │
│  │   │ parsed_ok   │  │                                       │  │
│  │   └─────────────┘  │                                       │  │
│  └────────────────────┼───────────────────────────────────────┘  │
└───────────────────────┼─────────────────────────────────────────────┘
                        │ polls for processed = FALSE
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     CLASSIFICATION LAYER                            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                 Classification Worker                       │   │
│  │                  (runs every 15 min)                        │   │
│  │                                                             │   │
│  │   1. fetch batch of 10 unprocessed articles                │   │
│  │   2. build prompt (inject taxonomy + article body)         │   │
│  │   3. call Claude API (structured JSON output)              │   │
│  │   4. parse + validate JSON response                        │   │
│  │   5. write themes, companies + per-company sentiment to DB │   │
│  │   6. log raw response + model to classification_log        │   │
│  │   7. mark article as processed = TRUE                      │   │
│  └──────────────────────┬──────────────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL AI SERVICE                            │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                        Claude API                            │  │
│  │              (model via CLAUDE_MODEL, default Sonnet 5)      │  │
│  │                                                              │  │
│  │   Billed per token; SDK retries 429 / 5xx with backoff       │  │
│  │   Input:  taxonomy system prompt + article title + body      │  │
│  │   Output: themes, companies (each with sentiment,            │  │
│  │           importance), reason                                │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                          │
                          │ structured signals now in DB
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      REPORTING LAYER                                │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Report Generator                          │   │
│  │                  (runs daily 07:00 UTC)                     │   │
│  │                                                             │   │
│  │   for each theme:                                          │   │
│  │     → article count this week vs last week                 │   │
│  │     → week-on-week growth %                                │   │
│  │     → top 5 companies by mention volume                    │   │
│  │     → emerging associations (new this week, unseen prior   │   │
│  │       3 weeks)                                             │   │
│  │     → top 3 articles by importance score                   │   │
│  └──────────────────────┬──────────────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          API LAYER                                  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                        FastAPI                               │  │
│  │                                                              │  │
│  │   GET  /report/daily          → full daily narrative report │  │
│  │   GET  /report/{theme}        → single theme report         │  │
│  │   GET  /articles/{theme}      → articles for a theme        │  │
│  │   GET  /companies/{theme}     → companies for a theme       │  │
│  │   GET  /health                → system health check         │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
└─────────────────────────────────┼───────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER (optional)                    │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    React Dashboard                           │  │
│  │                                                              │  │
│  │   Narrative momentum cards (week-on-week growth)            │  │
│  │   Company association charts                                │  │
│  │   Emerging association highlights                           │  │
│  │   Important articles feed                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Worker Scheduling

```
Timeline (each hour)
─────────────────────────────────────────────────────────────────────

:00  Ingestion Worker runs    → fetches new articles from RSS feeds
:04  Classification Worker    → processes batch of 10 articles
:08  Classification Worker    → processes batch of 10 articles
:12  Classification Worker    → processes batch of 10 articles
:15  Ingestion Worker runs    → fetches new articles
:16  Classification Worker    → processes batch of 10 articles
...
:30  Ingestion Worker runs    → fetches new articles
:45  Ingestion Worker runs    → fetches new articles

07:00 UTC daily               → Report Generator produces daily digest
```

---

## Data Flow: Single Article

```
1. RSS Feed
   └─► feedparser extracts: url, title, summary, published_at

2. Ingestion Worker
   └─► trafilatura fetches full body from URL
   └─► deduplication check (url already in articles table?)
   └─► INSERT into articles (processed = FALSE)

3. Classification Worker (picks up unprocessed articles)
   └─► builds prompt with article body + taxonomy
   └─► POST to Claude API (JSON schema enforced by structured outputs)
   └─► receives JSON: themes, companies (each with sentiment, importance), reason
   └─► parses and validates response
   └─► INSERT into article_themes (one row per theme)
   └─► INSERT into article_companies (one row per company)
   └─► INSERT into classification_log (raw response, parsed_ok, model)
   └─► UPDATE articles SET processed = TRUE

4. Report Generator (daily)
   └─► queries article_themes, article_companies, articles
   └─► aggregates by theme, counts, calculates growth
   └─► identifies emerging company associations
   └─► ranks articles by importance score
   └─► outputs structured report JSON

5. FastAPI
   └─► serves report JSON on demand via REST endpoints

6. React Dashboard (optional)
   └─► polls FastAPI endpoints
   └─► renders narrative cards, company lists, article feed
```

---

## Component Responsibilities

| Component | Runs | Responsibility |
|---|---|---|
| Ingestion Worker | Every 30 min | Fetch RSS feeds, extract article bodies, store raw articles |
| Classification Worker | Every 15 min | Classify unprocessed articles via Claude, store structured signals |
| PostgreSQL | Always on | Persist all articles, themes, companies, relationships, logs |
| Claude API | On demand | Extract themes, companies, per-company sentiment from article text |
| Report Generator | Daily 07:00 UTC | Aggregate signals into narrative report |
| FastAPI | Always on | Serve report data via REST API |
| React Dashboard | Browser | Visualise narrative momentum and company associations |

---

## Deployment: Single VPS

```
┌──────────────────────────────────────────────┐
│              Hetzner VPS (4GB RAM)           │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │           Docker Compose             │   │
│  │                                      │   │
│  │  ┌────────────┐  ┌────────────────┐ │   │
│  │  │  app       │  │  postgres      │ │   │
│  │  │  container │  │  container     │ │   │
│  │  │            │  │                │ │   │
│  │  │  FastAPI   │  │  PostgreSQL 15 │ │   │
│  │  │  Workers   │  │                │ │   │
│  │  │  Scheduler │  │                │ │   │
│  │  └────────────┘  └────────────────┘ │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  .env  →  ANTHROPIC_API_KEY                 │
│            DATABASE_URL                      │
└──────────────────────────────────────────────┘
                     │
                     │ outbound HTTPS only
                     ▼
        ┌────────────────────────┐
        │   Claude API           │
        │   RSS Feed endpoints   │
        │   SEC EDGAR (optional) │
        │   NewsAPI (optional)   │
        └────────────────────────┘
```

---

## Key Interfaces

### Ingestion Worker → PostgreSQL
```
INSERT INTO articles (url, title, body, source, published_at, processed)
VALUES (:url, :title, :body, :source, :published_at, FALSE)
ON CONFLICT (url) DO NOTHING;
```

### Classification Worker → Claude API
```
Called via the anthropic SDK (client.messages.create), model: CLAUDE_MODEL
(default claude-sonnet-5). Underlying REST endpoint:
POST https://api.anthropic.com/v1/messages

Headers:  x-api-key: {ANTHROPIC_API_KEY}
Body:     { model, max_tokens, system: "{taxonomy prompt}",
            messages: [{ role: "user", content: "{title + body}" }],
            output_config: { effort: CLAUDE_EFFORT,
                             format: { type: "json_schema", schema: {...} } } }
Response: { content: [{ type: "text", text: "{json}" }], stop_reason, usage }
```

### Classification Worker → PostgreSQL
```
INSERT INTO article_themes (article_id, theme_id, confidence) VALUES (...)
INSERT INTO article_companies (article_id, company_id, sentiment, importance) VALUES (...)
INSERT INTO classification_log (article_id, raw_response, parsed_ok, model) VALUES (...)
UPDATE articles SET processed = TRUE WHERE id = :id
```

### Report Generator → FastAPI
```
Returns JSON:
{
  "generated_at": "2025-01-20T07:00:00Z",
  "narratives": {
    "AI Infrastructure": {
      "article_count": 142,
      "wow_growth_pct": 28.0,
      "top_companies": [...],
      "emerging_associations": [...],
      "important_articles": [...]
    }
  }
}
```
