# Dashboard (frontend)

React + TypeScript + Vite SPA for the Market Narrative Intelligence read API. It turns
the daily narrative report into a drill-down view of which narratives are accelerating
and the companies attached to them.

## Screens

- **Overview** — every narrative as a velocity lane ranked by acceleration or volume,
  with a fastest-mover callout, week-over-week growth, `NEW` badges for emerging
  narratives, and the companies most associated with each.
- **Narrative detail** — one narrative in depth: direction and hero stats, a large
  week-over-week figure with a sparkline, the strip of newly emerging companies (with
  when each was first seen), the most important articles, and the top companies ranked
  by importance.
- **Company view** — the companies for a narrative as a ranked table you can sort by
  importance, mentions, or sentiment.

A sticky header carries the breadcrumb, the report's generated-at time, and a live
indicator.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173
```

In dev, API paths (`/health`, `/report`, `/articles`, `/companies`) are proxied to the
backend at `http://localhost:8000` (configurable via `VITE_API_TARGET`). Run the
backend separately — see the repo root README. In Docker the SPA is built and served by
nginx, which reverse-proxies the API on the same origin.

## Scripts

- `npm run dev` — dev server with HMR
- `npm run build` — type-check and production build to `dist/`
- `npm run preview` — serve the production build
- `npm run lint` — oxlint
- `npm run test` — Vitest unit tests (the `src/lib` encoding helpers)

## Code

- `src/api.ts` — typed interfaces matching the backend responses and a thin `fetch`
  wrapper. The backend (`app/services/report.py`, `app/api/routes.py`) is the source of
  truth — keep the types in sync with it.
- `src/lib/encoding.ts` — pure helpers for the visual encodings (acceleration colour and
  caret, sentiment glyphs, importance meters, week-over-week formatting, the sparkline,
  company sorting), unit-tested in `encoding.test.ts`.
- `src/components/` — one component (plus CSS module) per screen.
