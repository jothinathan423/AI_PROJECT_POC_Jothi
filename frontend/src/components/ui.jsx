import { useState } from 'react'
import s from './ui.module.css'

export const cx = (...a) => a.filter(Boolean).join(' ')

export function Chip({ color = 'gray', children, title }) {
  return <span className={cx(s.chip, s[color])} title={title}>{children}</span>
}

const STEP_COLOR = { approved: 'green', archived: 'green', in_progress: 'blue', awaiting_review: 'amber', returned: 'red', blocked: 'red', needs_refresh: 'purple', not_started: 'gray' }
export function StepChip({ status }) {
  return <Chip color={STEP_COLOR[status] || 'gray'}>{(status || 'not_started').replace(/_/g, ' ')}</Chip>
}

export function Banner({ kind = 'blue', children }) {
  return <div className={cx(s.banner, s['b_' + kind])}>{children}</div>
}

export function Card({ title, right, children, body = true }) {
  return (
    <div className={s.card}>
      {title && <div className={s.cardHead}><span>{title}</span><span className={s.spacer} />{right}</div>}
      {body ? <div className={s.cardBody}>{children}</div> : children}
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className={s.tabs}>
      {tabs.map(([k, label]) => (
        <button key={k} className={cx(s.tab, value === k && s.tabOn)} onClick={() => onChange(k)}>{label}</button>
      ))}
    </div>
  )
}

export function Btn({ kind, small, ...p }) {
  return <button {...p} className={cx(s.btn, kind === 'primary' && s.btnPrimary, kind === 'green' && s.btnGreen, kind === 'red' && s.btnRed, small && s.btnSm)} />
}

/** Is the current role allowed to run this workflow action right now? */
export function useCan(state, role) {
  return (action) => {
    const a = (state.allowed || []).find(x => x.action === action)
    return !!a && (a.roles || []).includes(role)
  }
}
export function needs(state, action) {
  const a = (state.allowed || []).find(x => x.action === action)
  return a ? `Needs role: ${a.roles.join(' / ')}` : 'Not available in the current status'
}

/** Approve / Return panel for a human gate. */
export function GateBox({ title, approveLabel = 'Approve', returnLabel = 'Return for rework', canApprove, canReturn, hint, onApprove, onReturn, busy }) {
  const [comment, setComment] = useState('')
  return (
    <div className={s.gate}>
      <div className={s.gateTitle}>⚡ {title}</div>
      <textarea className={s.textarea} style={{ minHeight: 44 }} placeholder="Comment (required when returning)…" value={comment} onChange={e => setComment(e.target.value)} />
      <div className={s.row} style={{ marginTop: 8 }}>
        <Btn kind="green" disabled={!canApprove || busy} title={canApprove ? '' : hint} onClick={() => onApprove(comment)}>{approveLabel}</Btn>
        <Btn kind="red" disabled={!canReturn || busy} title={canReturn ? '' : hint} onClick={() => { onReturn(comment); }}>{returnLabel}</Btn>
        {!canApprove && <span className={s.note}>{hint}</span>}
      </div>
    </div>
  )
}

export function Log({ messages }) {
  if (!messages?.length) return null
  return (
    <div className={s.log}>
      {messages.map((m, i) => <div key={i}>{m.ts?.slice(11, 19)} · {m.msg}</div>)}
    </div>
  )
}

export function fmt(ts) { return ts ? new Date(ts + (ts.endsWith('Z') ? '' : 'Z')).toLocaleString() : '—' }
export { s }
