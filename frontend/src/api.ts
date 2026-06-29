// Typed client for the Market Narrative read API.
// Shapes mirror app/services/report.py and app/api/routes.py exactly — the
// backend is the source of truth, so update these together with it.
//
// In dev, requests go to relative paths and Vite proxies them to the FastAPI
// server (see vite.config.ts). In other environments set VITE_API_BASE_URL.

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export type Sentiment = 'positive' | 'negative' | 'neutral'

/** A company aggregate (top_companies / GET /companies). */
export interface Company {
  name: string
  ticker: string | null
  mentions: number
  avg_importance: number | null
  avg_sentiment: Sentiment | null
}

/** A newly-emerging company association (emerging_associations). */
export interface EmergingAssociation {
  company: string
  ticker: string | null
  first_seen: string | null // ISO timestamp
}

/** An important article (top_articles / GET /articles). */
export interface Article {
  title: string
  url: string
  source: string | null
  published_at: string | null // ISO timestamp
  importance: number | null
  sentiment: Sentiment | null
}

/** Per-theme block inside the daily report. */
export interface NarrativeReport {
  article_count: number
  wow_growth_pct: number
  top_companies: Company[]
  emerging_associations: EmergingAssociation[]
  important_articles: Article[]
}

/** GET /report/daily */
export interface DailyReport {
  generated_at: string
  narratives: Record<string, NarrativeReport>
}

/** A daily-report theme flattened with its name, for ranking/rendering. */
export interface NarrativeRow extends NarrativeReport {
  theme: string
}

/** GET /report/{theme} */
export interface ThemeReport {
  theme: string
  article_count: number
  company_count: number
  top_companies: Company[]
  emerging_associations: EmergingAssociation[]
  important_articles: Article[]
}

/** GET /articles/{theme} */
export interface ThemeArticles {
  theme: string
  articles: Article[]
}

/** GET /companies/{theme} */
export interface ThemeCompanies {
  theme: string
  companies: Company[]
}

/** Flatten the daily report's narratives map into a list carrying the name. */
export function toNarrativeRows(report: DailyReport): NarrativeRow[] {
  return Object.entries(report.narratives).map(([theme, n]) => ({ theme, ...n }))
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`)
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} for ${path}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => getJson<{ status: string }>('/health'),
  dailyReport: () => getJson<DailyReport>('/report/daily'),
  themeReport: (theme: string) =>
    getJson<ThemeReport>(`/report/${encodeURIComponent(theme)}`),
  themeArticles: (theme: string) =>
    getJson<ThemeArticles>(`/articles/${encodeURIComponent(theme)}`),
  themeCompanies: (theme: string) =>
    getJson<ThemeCompanies>(`/companies/${encodeURIComponent(theme)}`),
}
