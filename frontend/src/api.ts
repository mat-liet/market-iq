// Typed client for the Market Narrative read API.
// Shapes mirror app/services/report.py and app/api/routes.py exactly — the
// backend is the source of truth, so update these together with it.
//
// In dev, requests go to relative paths and Vite proxies them to the FastAPI
// server (see vite.config.ts). In other environments set VITE_API_BASE_URL.

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export type Sentiment = 'positive' | 'negative' | 'neutral'

/** A company aggregate as returned by top_companies / emerging_associations. */
export interface CompanyMention {
  name: string
  ticker: string | null
  mention_count: number
}

/** An article as returned by top_articles. */
export interface ArticleSummary {
  title: string
  url: string
  importance: number | null
}

/** Per-theme block inside the daily report and the single-theme report. */
export interface NarrativeReport {
  article_count: number
  wow_growth_pct: number
  top_companies: CompanyMention[]
  emerging_associations: CompanyMention[]
  important_articles: ArticleSummary[]
}

/** GET /report/daily */
export interface DailyReport {
  generated_at: string
  narratives: Record<string, NarrativeReport>
}

/** GET /report/{theme} */
export interface ThemeReport {
  theme: string
  article_count: number
  top_companies: CompanyMention[]
  emerging_associations: CompanyMention[]
  important_articles: ArticleSummary[]
}

/** GET /articles/{theme} */
export interface ThemeArticles {
  theme: string
  articles: ArticleSummary[]
}

/** GET /companies/{theme} */
export interface ThemeCompanies {
  theme: string
  companies: CompanyMention[]
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
