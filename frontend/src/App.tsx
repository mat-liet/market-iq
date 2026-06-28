import { useEffect, useState } from 'react'
import { api, type DailyReport } from './api'

// Minimal placeholder shell. The real dashboard UI is being designed separately;
// this only proves the app is wired to the read API. Styling is intentionally
// bare until the design direction is settled.
function App() {
  const [report, setReport] = useState<DailyReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .dailyReport()
      .then(setReport)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '2rem' }}>
      <h1>Market Narrative Intelligence</h1>
      <p>Dashboard scaffold — wired to the read API.</p>

      {error && (
        <p role="alert">
          Could not reach the API ({error}). Start the backend with{' '}
          <code>uvicorn app.main:app</code> on port 8000.
        </p>
      )}

      {!report && !error && <p>Loading daily report…</p>}

      {report && (
        <>
          <p>
            Report generated at <time>{report.generated_at}</time>.{' '}
            {Object.keys(report.narratives).length} narratives tracked.
          </p>
          <ul>
            {Object.entries(report.narratives).map(([name, n]) => (
              <li key={name}>
                {name} — {n.article_count} articles, {n.wow_growth_pct}% WoW
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  )
}

export default App
