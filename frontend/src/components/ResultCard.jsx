import styles from './ResultCard.module.css'

export default function ResultCard({ icon, title, count, children, visible }) {
  return (
    <div className={`${styles.card} ${visible ? styles.visible : ''}`}>
      <div className={styles.header}>
        <span className={styles.icon}>{icon}</span>
        <span className={styles.title}>{title}</span>
        {count !== undefined && <span className={styles.count}>{count}</span>}
      </div>
      <div className={styles.body}>{children}</div>
    </div>
  )
}

export function Row({ label, value, children }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowVal}>{children || value}</span>
    </div>
  )
}

export function Tag({ type, children }) {
  return <span className={`${styles.tag} ${styles['tag_' + type]}`}>{children}</span>
}

export function RfiItem({ id, priority, children }) {
  const cls = priority === 'High' ? styles.rfiHigh : styles.rfiMed
  return (
    <div className={`${styles.rfi} ${cls}`}>
      <div className={styles.rfiId}>{id} · {priority?.toUpperCase()}</div>
      {children}
    </div>
  )
}
