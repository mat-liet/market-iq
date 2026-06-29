import type { ThemeReport } from '../api'
import {
  accentFor,
  caretFor,
  fmtDate,
  fmtWow,
  importanceWidth,
  sentimentMark,
  sparkline,
  timeLabel,
} from '../lib/encoding'
import styles from './NarrativeDetail.module.css'

interface NarrativeDetailProps {
  report: ThemeReport
  generatedAt: string | null
  onBack: () => void
  onCompanies: () => void
}

export function NarrativeDetail({ report, generatedAt, onBack, onCompanies }: NarrativeDetailProps) {
  const wow = report.wow_growth_pct
  const accel = wow >= 0
  const accent = accentFor(wow)
  const accentSoft = accel ? 'oklch(0.8 0.13 78 / 0.14)' : 'oklch(0.72 0.09 235 / 0.14)'
  const emergingCount = report.emerging_associations.length
  const now = generatedAt ?? new Date().toISOString()
  const spark = sparkline(wow, report.theme.length, 240, 58)
  const articles = [...report.important_articles].sort(
    (a, b) => (b.importance ?? -1) - (a.importance ?? -1),
  )

  return (
    <main className={styles.page}>
      <button type="button" className={styles.back} onClick={onBack}>
        ← All narratives
      </button>

      <div className={styles.hero}>
        <div className={styles.heroLeft}>
          <span className={styles.pill} style={{ color: accent, background: accentSoft }}>
            {caretFor(wow)} {accel ? 'ACCELERATING' : 'COOLING'}
          </span>
          <h1 className={styles.h1}>{report.theme}</h1>
          <div className={styles.stats}>
            <div>
              <div className={styles.statLabel}>THIS WEEK</div>
              <div className={styles.statVal}>
                {report.article_count} <span className={styles.statUnit}>articles</span>
              </div>
            </div>
            <div>
              <div className={styles.statLabel}>COMPANIES</div>
              <div className={styles.statVal}>{report.company_count}</div>
            </div>
            <div>
              <div className={styles.statLabel}>EMERGING</div>
              <div
                className={styles.statVal}
                style={{ color: emergingCount > 0 ? 'var(--emerging)' : 'var(--text-faint)' }}
              >
                {emergingCount}
              </div>
            </div>
          </div>
        </div>

        <div className={styles.heroRight}>
          <div className={styles.wowLine}>
            <span className={styles.wowCaret} style={{ color: accent }}>
              {caretFor(wow)}
            </span>
            <span className={styles.wowBig} style={{ color: accent }}>
              {fmtWow(wow)}
            </span>
          </div>
          <div className={styles.wowSub}>WEEK-OVER-WEEK</div>
          <div className={styles.sparkWrap}>
            <svg width="240" height="58" style={{ overflow: 'visible' }}>
              <polyline
                points={spark.points}
                fill="none"
                stroke={accent}
                strokeWidth="2.2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              <circle cx={spark.head[0]} cy={spark.head[1]} r="9" fill={accent} opacity="0.15" />
              <circle cx={spark.head[0]} cy={spark.head[1]} r="4" fill={accent} />
            </svg>
          </div>
        </div>
      </div>

      {emergingCount > 0 && (
        <div className={styles.emerging}>
          <div className={styles.emergingHead}>
            <span className={styles.emergingBadge}>NEW</span>
            <span className={styles.emergingTitle}>Emerging associations</span>
            <span className={styles.emergingDesc}>
              — companies newly attached to this narrative this week
            </span>
          </div>
          <div className={styles.emergingCards}>
            {report.emerging_associations.map((e) => (
              <div className={styles.emergingCard} key={e.company}>
                <div>
                  <div className={styles.ecName}>{e.company}</div>
                  <div className={styles.ecTicker}>{e.ticker ?? '—'}</div>
                </div>
                <div className={styles.ecSeen}>
                  first
                  <br />
                  seen
                  <br />
                  {fmtDate(e.first_seen)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={styles.grid}>
        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Most important articles</span>
            <span className={styles.panelMeta}>last 7 days</span>
          </div>
          {articles.map((a) => {
            const mark = sentimentMark(a.sentiment)
            const high = (a.importance ?? 0) >= 8
            return (
              <a
                key={a.url}
                href={a.url}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.article}
              >
                <div className={styles.impCell}>
                  <span className={high ? `${styles.impNum} ${styles.impNumHigh}` : styles.impNum}>
                    {a.importance ?? '—'}
                  </span>
                  <span className={styles.impLabel}>IMP</span>
                </div>
                <div className={styles.titleCell}>
                  <div className={styles.artTitle}>{a.title}</div>
                  <div className={styles.artMeta}>
                    {a.source && <span className={styles.artSource}>{a.source}</span>}
                    <span>·</span>
                    <span>{timeLabel(a.published_at, now)}</span>
                  </div>
                </div>
                <div className={styles.sentCell} style={{ color: mark?.color }}>
                  {mark && <span className={styles.sentGlyph}>{mark.glyph}</span>}
                  {mark?.label}
                </div>
              </a>
            )
          })}
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Top companies</span>
            <button type="button" className={styles.allLink} onClick={onCompanies}>
              All {report.company_count} →
            </button>
          </div>
          {report.top_companies.slice(0, 5).map((c) => {
            const mark = sentimentMark(c.avg_sentiment)
            return (
              <div className={styles.company} key={c.name}>
                <div className={styles.compRow1}>
                  <div className={styles.compIdent}>
                    {mark && (
                      <span className={styles.compGlyph} style={{ color: mark.color }}>
                        {mark.glyph}
                      </span>
                    )}
                    <span className={styles.compName}>{c.name}</span>
                    <span className={styles.compTicker}>{c.ticker ?? ''}</span>
                  </div>
                  <span className={styles.compMentions}>{c.mentions} mentions</span>
                </div>
                <div className={styles.compRow2}>
                  <span className={styles.impMeterLabel}>IMP</span>
                  <div className={styles.meterTrack}>
                    <div
                      className={styles.meterFill}
                      style={{ width: importanceWidth(c.avg_importance) }}
                    />
                  </div>
                  <span className={styles.impVal}>{c.avg_importance?.toFixed(1) ?? '—'}</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </main>
  )
}
