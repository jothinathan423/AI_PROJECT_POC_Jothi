import styles from './Header.module.css'

export default function Header({ statusLabel, isActive }) {
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <div className={styles.brand}>
          <span className={styles.logo}>SOFT SUAVE</span>
          <div className={styles.divider} />
          <div>
            <div className={styles.title}>AB Consultants — AI-Powered RFQ Analysis</div>
            <div className={styles.sub}>Scenario A · POC Demonstration</div>
          </div>
        </div>
        <div className={styles.status}>
          <span className={`${styles.dot} ${isActive ? styles.dotActive : ''}`} />
          <span>{statusLabel}</span>
        </div>
      </div>
    </header>
  )
}
