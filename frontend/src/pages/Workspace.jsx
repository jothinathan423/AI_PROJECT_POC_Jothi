import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { client, errText, STATUS_LABEL } from '../api'
import { Banner, Chip, Btn, StepChip, fmt, s, cx } from '../components/ui'
import Intake from './steps/Intake'
import Capability from './steps/Capability'
import { Analysis, Review } from './steps/Findings'
import Proposal from './steps/Proposal'
import Approval from './steps/Approval'
import Release from './steps/Release'
import ProcessView from './steps/ProcessView'

const PANELS = { intake: Intake, capability: Capability, analysis: Analysis, review: Review, proposal: Proposal, approval: Approval, release: Release }
const SHORT = { intake: 'Intake', capability: 'Capability', analysis: 'Technical analysis', review: 'Engineering review', proposal: 'Proposal', approval: 'Approval', release: 'Final + archive' }

export default function Workspace({ oppId, actor, onBack, onStatus }) {
  const api = useMemo(() => client(actor), [actor.name, actor.role]) // eslint-disable-line
  const [state, setState] = useState(null)
  const [selected, setSelected] = useState(null)   // null = follow the workflow's current step
  const [process, setProcess] = useState(false)
  const [toast, setToast] = useState(null)
  const lastStatus = useRef('')

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/opportunities/${oppId}`)
      setState(data)
      onStatus?.(data)
    } catch (e) { setToast({ kind: 'red', msg: errText(e) }) }
  }, [api, oppId]) // eslint-disable-line

  useEffect(() => { load() }, [load])
  useEffect(() => {      // poll: fast while a background step runs, slower otherwise; paused when the tab is hidden
    const ms = state?.busy || state?.opportunity.status.endsWith('_processing') ? 2000 : 5000
    const t = setInterval(() => { if (!document.hidden) load() }, ms)
    return () => clearInterval(t)
  }, [load, state?.busy, state?.opportunity.status])
  useEffect(() => {      // when the workflow moves to a new step, follow it
    const cur = state?.opportunity.current_step
    if (cur && lastStatus.current !== state.opportunity.status) { lastStatus.current = state.opportunity.status; setSelected(null) }
  }, [state?.opportunity.status]) // eslint-disable-line
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 7000); return () => clearTimeout(t) } }, [toast])

  /** Run a request, show the server's message on failure, then refresh. Returns the response (or undefined). */
  const act = useCallback(async (fn) => {
    try { const r = await fn(); await load(); return r } catch (e) { setToast({ kind: 'red', msg: errText(e) }); await load() }
  }, [load])

  if (!state) return <div className={s.main}>{toast ? <Banner kind="red">{toast.msg}</Banner> : 'Loading…'}</div>
  const opp = state.opportunity
  const current = selected || opp.current_step
  const Panel = PANELS[current]
  const role = actor.role

  return (
    <div className={s.main}>
      <div className={s.wrap}>
        {toast && <div className={cx(s.banner, s['b_' + toast.kind], s.toast)} onClick={() => setToast(null)}>{toast.msg}</div>}
        <div className={s.oppBar}>
          <Btn small onClick={onBack}>← All opportunities</Btn>
          <div>
            <div className={s.oppCode}>{opp.code}</div>
            <div className={s.oppName}>{opp.project_name || 'Untitled opportunity'}{opp.client ? ` · ${opp.client}` : ''}</div>
          </div>
          <div className={s.oppMeta}>
            <span>Status: <b>{STATUS_LABEL[opp.status] || opp.status}</b></span>
            <span>Package: <Chip color={opp.package_status === 'Ready' ? 'green' : opp.package_status === 'Warning' ? 'amber' : 'red'}>{opp.package_status}</Chip></span>
            <span>Owner: {opp.owner || '—'}</span>
            <span>Deadline: {opp.submission_deadline || '—'}</span>
            <span>Updated: {fmt(opp.updated_at)} · v{opp.version}</span>
          </div>
          <span className={s.spacer} />
          {state.busy && <span className={s.small}><span className={s.spin}>⟳</span> working…</span>}
          <Btn kind={process ? 'primary' : undefined} onClick={() => setProcess(!process)}>{process ? '← Back to step' : 'View complete process'}</Btn>
        </div>

        <div className={s.timeline}>
          {state.steps.map((st, i) => (
            <div key={st.step} className={cx(s.tlItem, !process && current === st.step && s.tlSel)} onClick={() => { setSelected(st.step); setProcess(false) }} title={st.title}>
              <div className={cx(s.circle, s['c_' + st.status])}>{st.status === 'approved' || st.status === 'archived' ? '✓' : i + 1}</div>
              <div className={s.tlLabel}>{SHORT[st.step]}</div>
              <div className={s.tlStatus}><StepChip status={st.status} /></div>
            </div>
          ))}
        </div>

        {process
          ? <ProcessView state={state} onOpen={k => { setSelected(k); setProcess(false) }} />
          : <Panel state={state} api={api} act={act} role={role} actor={actor} />}
      </div>
    </div>
  )
}
