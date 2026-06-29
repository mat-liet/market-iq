import type { View } from '../App'
import { fmtHeaderDateTime } from '../lib/encoding'
import styles from './Header.module.css'

interface HeaderProps {
  generatedAt: string | null
  view: View
  activeTheme: string | null
  onLogo: () => void
  onTheme: () => void
}

export function Header({ generatedAt, view, activeTheme, onLogo, onTheme }: HeaderProps) {
  const inTheme = (view === 'detail' || view === 'company') && activeTheme !== null

  return (
    <header className={styles.header}>
      <div className={styles.left}>
        <button type="button" className={styles.brand} onClick={onLogo}>
          <span className={styles.logo}>N</span>
          <span className={styles.wordmark}>NARRATIVE&nbsp;INTELLIGENCE</span>
        </button>
        {inTheme && (
          <div className={styles.crumbs}>
            <span className={styles.slash}>/</span>
            <button type="button" className={styles.crumbTheme} onClick={onTheme}>
              {activeTheme}
            </button>
            {view === 'company' && (
              <>
                <span className={styles.slash}>/</span>
                <span className={styles.crumbLeaf}>Companies</span>
              </>
            )}
          </div>
        )}
      </div>
      <div className={styles.right}>
        {generatedAt && <span className={styles.clock}>{fmtHeaderDateTime(generatedAt)}</span>}
        <span className={styles.live}>
          <span className={styles.liveDot} />
          LIVE
        </span>
      </div>
    </header>
  )
}
