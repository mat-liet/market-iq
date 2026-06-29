import { useEffect, useState } from 'react'
import { api, toNarrativeRows, type DailyReport, type NarrativeRow } from './api'
import { Header } from './components/Header'
import { Overview, type OverviewSort } from './components/Overview'
import styles from './App.module.css'

export type View = 'overview' | 'detail' | 'company'

export default function App() {
  const [report, setReport] = useState<DailyReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('overview')
  const [activeTheme, setActiveTheme] = useState<string | null>(null)
  const [overviewSort, setOverviewSort] = useState<OverviewSort>('accel')

  useEffect(() => {
    api
      .dailyReport()
      .then(setReport)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  function go(next: View, theme: string | null = activeTheme) {
    setView(next)
    setActiveTheme(theme)
    window.scrollTo(0, 0)
  }

  const rows: NarrativeRow[] = report ? toNarrativeRows(report) : []

  return (
    <>
      <Header
        generatedAt={report?.generated_at ?? null}
        view={view}
        activeTheme={activeTheme}
        onLogo={() => go('overview', null)}
        onTheme={() => go('detail')}
      />

      {error && (
        <div className={styles.status} role="alert">
          Could not reach the API ({error}). Start the backend with{' '}
          <code>uvicorn app.main:app</code> on port 8000.
        </div>
      )}

      {!report && !error && <div className={styles.status}>Loading daily report…</div>}

      {report && view === 'overview' && (
        <Overview
          rows={rows}
          sort={overviewSort}
          onSort={setOverviewSort}
          onOpenTheme={(theme) => go('detail', theme)}
        />
      )}

      {report && (view === 'detail' || view === 'company') && (
        <div className={styles.status}>
          {activeTheme}: this screen is coming next.
        </div>
      )}
    </>
  )
}
