# Dashboard (frontend)

React + TypeScript + Vite SPA for the Market Narrative Intelligence read API.

This is the scaffold; the dashboard UI is still being designed. `src/App.tsx` is a
minimal placeholder that proves the app is wired to the API. Styling is intentionally
bare until the design direction is settled.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173
```

In dev, API paths (`/health`, `/report`, `/articles`, `/companies`) are proxied to the
backend at `http://localhost:8000` (configurable via `VITE_API_TARGET`). Run the
backend separately — see the repo root README.

## Scripts

- `npm run dev` — dev server with HMR
- `npm run build` — type-check and production build to `dist/`
- `npm run preview` — serve the production build
- `npm run lint` — oxlint

## API client

`src/api.ts` holds typed interfaces matching the backend responses and a thin `fetch`
wrapper. The backend (`app/services/report.py`, `app/api/routes.py`) is the source of
truth — keep the types in sync with it.
