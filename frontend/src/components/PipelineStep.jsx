import { useState, useRef, useEffect } from 'react'
import styles from './PipelineStep.module.css'

const STATUS_CLASS = {
  pending: styles.pending,
  running: styles.running,
  done: styles.done,
  waiting: styles.waiting,
  returned: styles.returned,
}

export default function PipelineStep({
  id, label, title, badge, badgeType, description, messages,
  status, showConnector, connectorActive,
  gateActions, onApprove, onReturn,
  approveLabel, returnLabel,
  stepRef,
}) {
  return (
    <div className={styles.step} ref={stepRef}>
      <div className={styles.left}>
        <div className={`${styles.icon} ${STATUS_CLASS[status] || styles.pending}`}>
          {status === 'done' ? '✓' : status === 'returned' ? '↩' : label}
        </div>
        {showConnector && (
          <div className={`${styles.connector} ${connectorActive ? styles.connectorActive : ''}`} />
        )}
      </div>
      <div className={styles.body}>
        <div className={styles.titleRow}>
          <span className={styles.title}>{title}</span>
          {badge && (
            <span className={`${styles.badge} ${styles['badge_' + badgeType]}`}>{badge}</span>
          )}
        </div>
        <div className={styles.desc}>{description}</div>
        {messages.length > 0 && (
          <div className={styles.messages}>
            {messages.map((m, i) => (
              <div key={i} className={styles.msg}>{m}</div>
            ))}
          </div>
        )}
        {gateActions && status === 'waiting' && (
          <GateButtons onApprove={onApprove} onReturn={onReturn}
            approveLabel={approveLabel} returnLabel={returnLabel} />
        )}
      </div>
    </div>
  )
}

function GateButtons({ onApprove, onReturn, approveLabel, returnLabel }) {
  const [returning, setReturning] = useState(false)
  const [comment, setComment] = useState('')

  if (returning) {
    return (
      <div className={styles.gateActions}>
        <input
          className={styles.returnInput}
          placeholder="Return reason (optional)…"
          value={comment}
          onChange={e => setComment(e.target.value)}
          autoFocus
        />
        <div className={styles.gateRow}>
          <button className={styles.btnReturn} onClick={() => { onReturn(comment); setReturning(false) }}>
            {returnLabel ? returnLabel.replace(/^[^ ]+ /, '') : '↩ Confirm Return'}
          </button>
          <button className={styles.btnCancel} onClick={() => setReturning(false)}>Cancel</button>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.gateActions}>
      <button className={styles.btnApprove} onClick={onApprove}>{approveLabel || '✓ Approve'}</button>
      <button className={styles.btnReturn} onClick={() => setReturning(true)}>{returnLabel || '↩ Return for Rework'}</button>
    </div>
  )
}
