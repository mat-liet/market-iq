import { useEffect, useState } from 'react'
import {
  api,
  toNarrativeRows,
  type Company,
  type DailyReport,
  type NarrativeRow,
  type ThemeReport,
} from './api'
import { Header } from './components/Header'
import { Overview, type OverviewSort } from './components/Overview'
import { NarrativeDetail } from './components/NarrativeDetail'
import { CompanyView } from './components/CompanyView'
import type { CompanySort } from './lib/encoding'
import styles from './App.module.css'

export type View = 'overview' | 'detail' | 'company'

export default function App() {
  const [report, setReport] = useState<DailyReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('overview')
  const [activeTheme, setActiveTheme] = useState<string | null>(null)
  const [overviewSort, setOverviewSort] = useState<OverviewSort>('accel')
  const [companySort, setCompanySort] = useState<CompanySort>('importance')
  const [themeReport, setThemeReport] = useState<ThemeReport | null>(null)
  const [themeCompanies, setThemeCompanies] = useState<Company[] | null>(null)

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e))

  useEffect(() => {
    api.dailyReport().then(setReport).catch(fail)
  }, [])

  // Fetch per-theme data on drill-in (the daily report is cached above).
  useEffect(() => {
    if (!activeTheme) return
    if (view === 'detail') {
      setThemeReport(null)
      api.themeReport(activeTheme).then(setThemeReport).catch(fail)
    } else if (view === 'company') {
      setThemeCompanies(null)
      api.themeCompanies(activeTheme).then((r) => setThemeCompanies(r.companies)).catch(fail)
    }
  }, [view, activeTheme])

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

      {report && view === 'detail' &&
        (themeReport ? (
          <NarrativeDetail
            report={themeReport}
            generatedAt={report.generated_at}
            onBack={() => go('overview', null)}
            onCompanies={() => go('company')}
          />
        ) : (
          !error && <div className={styles.status}>Loading {activeTheme}…</div>
        ))}

      {report && view === 'company' &&
        activeTheme &&
        (themeCompanies ? (
          <CompanyView
            theme={activeTheme}
            companies={themeCompanies}
            sort={companySort}
            onSort={setCompanySort}
            onBack={() => go('detail')}
          />
        ) : (
          !error && <div className={styles.status}>Loading companies…</div>
        ))}
    </>
  )
}
