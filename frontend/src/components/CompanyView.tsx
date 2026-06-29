import type { Company } from '../api'
import { importanceWidth, sentimentMark, sortCompanies, type CompanySort } from '../lib/encoding'
import styles from './CompanyView.module.css'

interface CompanyViewProps {
  theme: string
  companies: Company[]
  sort: CompanySort
  onSort: (sort: CompanySort) => void
  onBack: () => void
}

const SORT_LABEL: Record<CompanySort, string> = {
  importance: 'importance',
  mentions: 'mention volume',
  sentiment: 'sentiment',
}

const TABS: { key: CompanySort; label: string }[] = [
  { key: 'importance', label: 'IMPORTANCE' },
  { key: 'mentions', label: 'MENTIONS' },
  { key: 'sentiment', label: 'SENTIMENT' },
]

function rank2(i: number): string {
  return (i + 1 < 10 ? '0' : '') + (i + 1)
}

export function CompanyView({ theme, companies, sort, onSort, onBack }: CompanyViewProps) {
  const ordered = sortCompanies(companies, sort)
  const maxMentions = companies.reduce((m, c) => Math.max(m, c.mentions), 1)

  return (
    <main className={styles.page}>
      <button type="button" className={styles.back} onClick={onBack}>
        ← {theme}
      </button>

      <div className={styles.titleRow}>
        <div>
          <div className={styles.eyebrow}>{theme}</div>
          <h1 className={styles.h1}>Companies in this narrative</h1>
          <p className={styles.subhead}>
            {companies.length} companies attached this week, ranked by {SORT_LABEL[sort]}.
          </p>
        </div>
        <div className={styles.toggle} role="tablist" aria-label="Sort companies">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={sort === t.key}
              className={sort === t.key ? `${styles.tab} ${styles.tabActive}` : styles.tab}
              onClick={() => onSort(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.table}>
        <div className={styles.headRow}>
          <div>#</div>
          <div>Company</div>
          <div className={styles.headMentions}>Mentions</div>
          <div className={styles.headSent}>Sentiment</div>
          <div className={styles.headImp}>Importance</div>
        </div>

        {ordered.map((c, i) => {
          const mark = sentimentMark(c.avg_sentiment)
          return (
            <div className={styles.row} key={c.name}>
              <div className={styles.rank}>{rank2(i)}</div>
              <div className={styles.company}>
                <span className={styles.compName}>{c.name}</span>
                <span className={styles.compTicker}>{c.ticker ?? ''}</span>
              </div>
              <div className={styles.mentions}>
                <div className={styles.meterTrack}>
                  <div
                    className={styles.mentionsFill}
                    style={{ width: `${Math.round((c.mentions / maxMentions) * 100)}%` }}
                  />
                </div>
                <span className={styles.mentionsVal}>{c.mentions}</span>
              </div>
              <div className={styles.sentiment} style={{ color: mark?.color }}>
                {mark && <span className={styles.sentGlyph}>{mark.glyph}</span>}
                {mark?.label ?? '—'}
              </div>
              <div className={styles.importance}>
                <div className={styles.impMeter}>
                  <div
                    className={styles.impFill}
                    style={{ width: importanceWidth(c.avg_importance) }}
                  />
                </div>
                <span className={styles.impVal}>{c.avg_importance?.toFixed(1) ?? '—'}</span>
              </div>
            </div>
          )
        })}
      </div>
    </main>
  )
}
