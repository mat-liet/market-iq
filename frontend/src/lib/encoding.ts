// Pure encoding/formatting helpers shared across the dashboard. These carry the
// design's visual logic (acceleration, sentiment, importance, time) and are unit
// tested in encoding.test.ts.

import type { Company, Sentiment } from '../api'

// --- Acceleration ---------------------------------------------------------

export const ACCENT_ACCEL = 'oklch(0.8 0.13 78)' // amber
export const ACCENT_COOL = 'oklch(0.72 0.09 235)' // blue
const VELOCITY_CEILING = 130 // |wow| that fills the lane; bar caps at 96%

export function accentFor(wow: number): string {
  return wow >= 0 ? ACCENT_ACCEL : ACCENT_COOL
}

export function caretFor(wow: number): string {
  return wow >= 0 ? '▶' : '◀'
}

/** "+120.5%" / "−18.6%" — note the U+2212 minus glyph for negatives. */
export function fmtWow(wow: number): string {
  return (wow >= 0 ? '+' : '−') + Math.abs(wow).toFixed(1) + '%'
}

/** Width of the velocity fill bar as a CSS percentage, capped at 96%. */
export function velocityWidth(wow: number): string {
  return Math.min(96, Math.round((Math.abs(wow) / VELOCITY_CEILING) * 100)) + '%'
}

// --- Sentiment ------------------------------------------------------------

export interface SentimentMark {
  glyph: string
  color: string
  label: string
}

const SENTIMENT: Record<Sentiment, SentimentMark> = {
  positive: { glyph: '▲', color: 'oklch(0.74 0.09 165)', label: 'Positive' },
  negative: { glyph: '▼', color: 'oklch(0.68 0.11 28)', label: 'Negative' },
  neutral: { glyph: '■', color: 'oklch(0.66 0.02 258)', label: 'Neutral' },
}

/** The glyph/color/label for a sentiment, or null when there is no data. */
export function sentimentMark(s: Sentiment | null): SentimentMark | null {
  return s ? SENTIMENT[s] : null
}

// --- Importance -----------------------------------------------------------

/** Meter fill width for an importance score (1–10) as a CSS percentage. */
export function importanceWidth(importance: number | null): string {
  if (importance == null) return '0%'
  return Math.round((importance / 10) * 100) + '%'
}

// --- Company sorting ------------------------------------------------------

export type CompanySort = 'importance' | 'mentions' | 'sentiment'

const SENTIMENT_RANK: Record<Sentiment, number> = { positive: 0, neutral: 1, negative: 2 }

function sentimentRank(s: Sentiment | null): number {
  return s ? SENTIMENT_RANK[s] : 3 // unknown sentiment sorts last
}

/** Sort companies for the Company view. Returns a new array. */
export function sortCompanies(companies: Company[], sort: CompanySort): Company[] {
  const byImportance = (a: Company, b: Company) =>
    (b.avg_importance ?? -1) - (a.avg_importance ?? -1)
  return [...companies].sort((a, b) => {
    if (sort === 'mentions') return b.mentions - a.mentions
    if (sort === 'sentiment') {
      return sentimentRank(a.avg_sentiment) - sentimentRank(b.avg_sentiment) || byImportance(a, b)
    }
    return byImportance(a, b)
  })
}

// --- Time -----------------------------------------------------------------

/** Relative time of an article vs. the report's generated_at: now / Xh / Xd. */
export function timeLabel(publishedIso: string | null, generatedIso: string): string {
  if (!publishedIso) return ''
  const hours = (new Date(generatedIso).getTime() - new Date(publishedIso).getTime()) / 3_600_000
  if (hours < 1) return 'now'
  if (hours < 24) return `${Math.floor(hours)}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Jun 25" in UTC, for emerging "first seen" labels. */
export function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`
}

/** "28 JUN 2026 · 08:00 UTC" from an ISO timestamp, for the header. */
export function fmtHeaderDateTime(iso: string): string {
  const d = new Date(iso)
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const mon = MONTHS[d.getUTCMonth()].toUpperCase()
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${dd} ${mon} ${d.getUTCFullYear()} · ${hh}:${mm} UTC`
}

// --- Sparkline ------------------------------------------------------------

export interface Sparkline {
  points: string
  head: [number, number]
}

/** A stylized 7-point acceleration sparkline derived from the WoW value.
 * Not real time-series data — a representation, per the design. */
export function sparkline(wow: number, seed: number, w: number, h: number): Sparkline {
  const n = 7
  const pad = 5
  const slope = wow / 100
  const vals: number[] = []
  for (let k = 0; k < n; k++) {
    vals.push(0.5 + slope * (k / (n - 1)) + Math.sin(k * 1.7 + seed) * 0.05)
  }
  const mn = Math.min(...vals)
  const mx = Math.max(...vals)
  const rng = mx - mn || 1
  const pts = vals.map((v, k): [number, number] => [
    pad + (k / (n - 1)) * (w - 2 * pad),
    h - pad - ((v - mn) / rng) * (h - 2 * pad),
  ])
  return {
    points: pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '),
    head: pts[n - 1],
  }
}
