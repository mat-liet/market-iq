import type { NarrativeRow } from '../api'
import {
  accentFor,
  caretFor,
  fmtWow,
  sentimentMark,
  velocityWidth,
} from '../lib/encoding'
import styles from './Overview.module.css'

export type OverviewSort = 'accel' | 'volume'

interface OverviewProps {
  rows: NarrativeRow[]
  sort: OverviewSort
  onSort: (sort: OverviewSort) => void
  onOpenTheme: (theme: string) => void
}

function rank2(i: number): string {
  return (i + 1 < 10 ? '0' : '') + (i + 1)
}

export function Overview({ rows, sort, onSort, onOpenTheme }: OverviewProps) {
  const ordered = [...rows].sort((a, b) =>
    sort === 'volume' ? b.article_count - a.article_count : b.wow_growth_pct - a.wow_growth_pct,
  )
  const fastest = rows.reduce(
    (best, r) => (best === null || r.wow_growth_pct > best.wow_growth_pct ? r : best),
    null as NarrativeRow | null,
  )
  const fastestEmerging = fastest?.emerging_associations.length ?? 0

  return (
    <main className={styles.page}>
      <div className={styles.titleRow}>
        <div>
          <div className={styles.eyebrow}>Morning Report</div>
          <h1 className={styles.h1}>Narrative Acceleration</h1>
          <p className={styles.subhead}>
            Every market narrative, ranked by week-over-week momentum — not raw volume. What&apos;s
            heating up before it&apos;s priced in.
          </p>
        </div>
        <div className={styles.toggle} role="tablist" aria-label="Sort narratives">
          <button
            type="button"
            role="tab"
            aria-selected={sort === 'accel'}
            className={sort === 'accel' ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            onClick={() => onSort('accel')}
          >
            RANK BY ACCEL
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={sort === 'volume'}
            className={sort === 'volume' ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            onClick={() => onSort('volume')}
          >
            VOLUME
          </button>
        </div>
      </div>

      {fastest && (
        <div className={styles.callout}>
          <span className={styles.calloutLabel}>▶ FASTEST MOVER</span>
          <span className={styles.calloutTheme}>{fastest.theme}</span>
          <span className={styles.calloutWow}>{fmtWow(fastest.wow_growth_pct)}</span>
          <span className={styles.calloutNote}>
            {fastestEmerging > 0
              ? `${fastestEmerging} emerging association${fastestEmerging > 1 ? 's' : ''} this week`
              : 'leading on momentum'}
          </span>
        </div>
      )}

      <div className={styles.table}>
        <div className={styles.headRow}>
          <div>#</div>
          <div>Narrative · Top companies</div>
          <div>Velocity</div>
          <div className={styles.headWow}>WoW</div>
        </div>

        {ordered.map((r, i) => {
          const accent = accentFor(r.wow_growth_pct)
          const width = velocityWidth(r.wow_growth_pct)
          const emerging = r.emerging_associations.length
          return (
            <button
              type="button"
              key={r.theme}
              className={styles.row}
              onClick={() => onOpenTheme(r.theme)}
            >
              <div className={i === 0 ? `${styles.rank} ${styles.rankTop}` : styles.rank}>
                {rank2(i)}
              </div>

              <div className={styles.narrative}>
                <div className={styles.themeLine}>
                  <span className={styles.themeName}>{r.theme}</span>
                  {emerging > 0 && <span className={styles.badge}>{emerging} NEW</span>}
                </div>
                <div className={styles.chips}>
                  {r.top_companies.slice(0, 3).map((c) => {
                    const mark = sentimentMark(c.avg_sentiment)
                    return (
                      <span className={styles.chip} key={c.name}>
                        {mark && (
                          <span className={styles.chipGlyph} style={{ color: mark.color }}>
                            {mark.glyph}
                          </span>
                        )}
                        <span>{c.ticker ?? c.name}</span>
                        {c.avg_importance != null && (
                          <span className={styles.chipImp}>{c.avg_importance.toFixed(1)}</span>
                        )}
                      </span>
                    )
                  })}
                </div>
              </div>

              <div className={styles.velocity}>
                <div className={styles.track} />
                <div
                  className={styles.fill}
                  style={{ width, background: `linear-gradient(90deg, transparent, ${accent})` }}
                />
                <div
                  className={styles.puck}
                  style={{ left: width, background: accent, boxShadow: `0 0 14px ${accent}` }}
                />
              </div>

              <div className={styles.wow}>
                <div className={styles.wowLine}>
                  <span className={styles.wowCaret} style={{ color: accent }}>
                    {caretFor(r.wow_growth_pct)}
                  </span>
                  <span className={styles.wowVal} style={{ color: accent }}>
                    {fmtWow(r.wow_growth_pct)}
                  </span>
                </div>
                <div className={styles.count}>{r.article_count} articles</div>
              </div>
            </button>
          )
        })}
      </div>

      <div className={styles.legend}>
        <span className={styles.legendKey}>ENCODING</span>
        <span className={styles.legendItem}>
          <span
            className={styles.swatch}
            style={{ background: 'linear-gradient(90deg, transparent, var(--accel))' }}
          />
          accelerating
        </span>
        <span className={styles.legendItem}>
          <span
            className={styles.swatch}
            style={{ background: 'linear-gradient(90deg, transparent, var(--cool))' }}
          />
          cooling
        </span>
        <span className={styles.legendItem}>
          <span style={{ color: 'var(--pos)' }}>▲</span>positive
          <span style={{ color: 'var(--neg)' }}>▼</span>negative
          <span style={{ color: 'var(--neu)' }}>■</span>neutral
        </span>
        <span>number after ticker = importance 1–10</span>
      </div>
    </main>
  )
}
