import { useState } from 'react'
import { Card, Banner, Chip, Btn, Log, Tabs, GateBox, useCan, needs, s, cx } from '../../components/ui'

const STATUS = { extracted: ['green', 'Extracted'], ai_suggested: ['blue', 'AI-suggested'], needs_verification: ['amber', 'Needs verification'] }
const REVIEW = { pending: ['gray', 'pending'], verified: ['green', 'verified'], corrected: ['blue', 'corrected'], disputed: ['red', 'disputed'], assumption: ['purple', 'assumption'] }
const RFI_STATES = ['draft', 'approved', 'sent', 'answered', 'closed', 'assumption', 'dismissed']

function Source({ f }) {
  if (!f.source_file) return <span className={s.muted}>—</span>
  return (
    <div className={s.small}>{f.source_file.length > 34 ? f.source_file.slice(0, 32) + '…' : f.source_file}{f.source_page ? ` · p.${f.source_page}` : ''}
      {f.quote_verified ? <Chip color="green" title="The quote was found in the cited page text">quote ✓</Chip> : f.quote ? <Chip color="amber" title="The quote could not be located in the source">quote ✗</Chip> : null}
    </div>
  )
}

function ReviewCell({ f, editable, onReview }) {
  const [mode, setMode] = useState(null)
  const [text, setText] = useState('')
  const [color, label] = REVIEW[f.review] || REVIEW.pending
  if (!editable) return <Chip color={color}>{label}</Chip>
  if (mode) {
    return (
      <div style={{ minWidth: 190 }}>
        <input className={s.input} style={{ width: '100%' }} autoFocus value={text} onChange={e => setText(e.target.value)}
          placeholder={mode === 'corrected' ? 'Corrected value…' : `Why is this ${mode}?`} />
        <div className={s.row} style={{ marginTop: 4 }}>
          <Btn small kind="primary" onClick={async () => { await onReview(f.id, mode, mode === 'corrected' ? text : '', mode === 'corrected' ? '' : text); setMode(null); setText('') }}>Save</Btn>
          <Btn small onClick={() => setMode(null)}>Cancel</Btn>
        </div>
      </div>
    )
  }
  return (
    <div>
      <Chip color={color}>{label}</Chip>{f.reviewer && <span className={s.note}> {f.reviewer}</span>}
      <div className={s.row} style={{ marginTop: 3, gap: 3 }}>
        <Btn small onClick={() => onReview(f.id, 'verified')}>✓</Btn>
        <Btn small onClick={() => { setText(f.value); setMode('corrected') }}>Correct</Btn>
        <Btn small onClick={() => setMode('disputed')}>Dispute</Btn>
        <Btn small onClick={() => setMode('assumption')}>Assume</Btn>
      </div>
      {f.review_comment && <div className={s.quote}>{f.review_comment}</div>}
    </div>
  )
}

function FindingsTable({ rows, editable, onReview, selected, setSelected, showKey = true, extra }) {
  return (
    <div className={s.tableWrap}><table className={s.table}>
      <thead><tr>{editable && <th />}<th>#</th>{showKey && <th>Item</th>}<th>Value</th><th>Source</th><th>Status</th><th>Conf.</th><th>Review</th></tr></thead>
      <tbody>
        {rows.length === 0 && <tr><td colSpan={8} className={s.muted}>Nothing here yet.</td></tr>}
        {rows.map(f => (
          <tr key={f.id}>
            {editable && <td><input type="checkbox" checked={selected.includes(f.id)} onChange={e => setSelected(e.target.checked ? [...selected, f.id] : selected.filter(x => x !== f.id))} /></td>}
            <td>F{f.id}{f.critical && <span title="Critical - must be resolved before engineering approval"> ⭐</span>}</td>
            {showKey && <td><b>{f.key}</b></td>}
            <td style={{ maxWidth: 440 }}>
              {f.review === 'corrected' ? <><s>{f.value}</s> → <b>{f.corrected_value}</b></> : f.value}
              {f.data?.measurement_warning && <div className={s.small} style={{ color: '#b45309' }}>⚠ {f.data.measurement_warning}</div>}
              {f.method !== 'read_from_source' && f.method !== 'read_from_drawing' && <div className={s.note}>method: {f.method.replace(/_/g, ' ')}</div>}
              {extra && extra(f)}
            </td>
            <td><Source f={f} /></td>
            <td><Chip color={STATUS[f.status]?.[0]}>{STATUS[f.status]?.[1] || f.status}</Chip></td>
            <td>{f.confidence}</td>
            <td><ReviewCell f={f} editable={editable} onReview={onReview} /></td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}

function RfiTable({ state, api, act, editable }) {
  const [draft, setDraft] = useState({})
  const set = (id, k, v) => setDraft(d => ({ ...d, [id]: { ...(d[id] || {}), [k]: v } }))
  const [nr, setNr] = useState('')
  return (
    <>
      <div className={s.tableWrap}><table className={s.table}>
        <thead><tr><th>No.</th><th>Priority</th><th>Issue / clarification question</th><th>Status</th><th>Owner · due</th><th>Response / reason</th></tr></thead>
        <tbody>
          {state.rfis.length === 0 && <tr><td colSpan={6} className={s.muted}>No RFIs.</td></tr>}
          {state.rfis.map(r => {
            const d = draft[r.id] || {}, val = k => d[k] ?? r[k] ?? ''
            const dirty = Object.keys(d).length > 0
            return (
              <tr key={r.id}>
                <td><b>{r.rfi_no}</b><div className={s.note}>{r.origin}</div></td>
                <td><Chip color={r.priority === 'High' ? 'red' : r.priority === 'Medium' ? 'amber' : 'gray'}>{r.priority}</Chip></td>
                <td style={{ maxWidth: 420 }}>{r.issue}
                  {r.evidence && <div className={s.quote}>Evidence: {r.evidence}</div>}
                  {r.suggested_action && <div className={s.small}>→ {r.suggested_action}</div>}</td>
                <td>{editable ? <select className={s.select} value={val('status')} onChange={e => set(r.id, 'status', e.target.value)}>{RFI_STATES.map(x => <option key={x}>{x}</option>)}</select> : <Chip>{r.status}</Chip>}</td>
                <td>{editable ? <><input className={s.input} style={{ width: 110 }} placeholder="owner" value={val('owner')} onChange={e => set(r.id, 'owner', e.target.value)} />
                  <input className={s.input} style={{ width: 110, marginTop: 3 }} placeholder="due date" value={val('due_date')} onChange={e => set(r.id, 'due_date', e.target.value)} /></> : <span className={s.small}>{r.owner} {r.due_date}</span>}</td>
                <td>{editable ? <><textarea className={s.textarea} style={{ minHeight: 40 }} value={val('response')} onChange={e => set(r.id, 'response', e.target.value)} />
                  {dirty && <Btn small kind="primary" onClick={async () => { await act(() => api.patch(`/api/rfis/${r.id}`, d)); setDraft(x => { const n = { ...x }; delete n[r.id]; return n }) }}>Save</Btn>}</> : <span className={s.small}>{r.response}</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table></div>
      {editable && (
        <div className={s.row} style={{ marginTop: 10 }}>
          <input className={s.input} style={{ flex: 1 }} placeholder="Add a manual RFI / clarification question…" value={nr} onChange={e => setNr(e.target.value)} />
          <Btn disabled={!nr.trim()} onClick={async () => { await act(() => api.post(`/api/opportunities/${state.opportunity.id}/rfis`, { issue: nr, priority: 'Medium' })); setNr('') }}>Add RFI</Btn>
        </div>
      )}
    </>
  )
}

export function Report({ state, api, act, editable }) {
  const [tab, setTab] = useState('rfq')
  const [selected, setSelected] = useState([])
  const F = state.findings
  const by = k => F.filter(f => f.kind === k)
  const onReview = (id, review, corrected_value = '', comment = '') => act(() => api.patch(`/api/findings/${id}`, { review, corrected_value, comment }))
  const obsFor = sheet => F.filter(f => f.kind === 'observation' && f.source_file === sheet.source_file && f.source_page === sheet.source_page)
  const tabs = [['rfq', `RFQ scope & requirements (${by('rfq_field').length + by('requirement').length})`], ['draw', `Drawing register (${by('drawing_sheet').length})`],
    ['rfi', `Gaps / RFIs (${state.rfis.length})`], ['risk', `Risks (${by('risk').length})`]]
  return (
    <>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {editable && tab !== 'rfi' && (
        <div className={s.row} style={{ marginBottom: 8 }}>
          <Btn small disabled={!selected.length} onClick={async () => { await act(() => api.post(`/api/opportunities/${state.opportunity.id}/findings/bulk`, { ids: selected, review: 'verified' })); setSelected([]) }}>Verify {selected.length} selected</Btn>
          <Btn small onClick={() => setSelected(F.filter(f => f.review === 'pending' && ({ rfq: ['rfq_field', 'requirement'], draw: ['drawing_sheet', 'observation'], risk: ['risk'] }[tab] || []).includes(f.kind)).map(f => f.id))}>Select all pending in this tab</Btn>
          <span className={s.note}>⭐ = critical (mandatory requirement / high risk): must be verified, corrected or carried as an assumption before engineering approval.</span>
        </div>
      )}
      {tab === 'rfq' && <>
        <Card title="RFQ fields" body={false}><FindingsTable rows={by('rfq_field')} editable={editable} onReview={onReview} selected={selected} setSelected={setSelected} /></Card>
        <Card title="Requirement checklist" body={false}><FindingsTable rows={by('requirement')} editable={editable} onReview={onReview} selected={selected} setSelected={setSelected} /></Card>
      </>}
      {tab === 'draw' && <>
        <Card title="Drawing register" body={false}>
          <FindingsTable rows={by('drawing_sheet')} editable={editable} onReview={onReview} selected={selected} setSelected={setSelected}
            extra={f => <div className={s.small} style={{ color: '#6b7280' }}>{f.data.discipline} · rev {f.data.revision || '—'} · scale {f.data.scale || '—'} · {obsFor(f).length} observation(s){(f.data.issues || []).length ? ` · issues: ${f.data.issues.join('; ')}` : ''}</div>} />
        </Card>
        <Card title="Drawing-derived observations" body={false}><FindingsTable rows={by('observation')} editable={editable} onReview={onReview} selected={selected} setSelected={setSelected} /></Card>
      </>}
      {tab === 'rfi' && <Card title="Gap & clarification register" body={false}><div style={{ padding: 12 }}><RfiTable state={state} api={api} act={act} editable={editable} /></div></Card>}
      {tab === 'risk' && <Card title="Technical / bid risk register" body={false}><FindingsTable rows={by('risk')} editable={editable} onReview={onReview} selected={selected} setSelected={setSelected} showKey={false} /></Card>}
    </>
  )
}

export function Analysis({ state, api, act, role }) {
  const step = state.steps[2], opp = state.opportunity
  const started = !['draft', 'capability_processing', 'capability_review', 'closed_no_go'].includes(opp.status) || state.findings.length
  return (
    <>
      <div className={s.h2}>3 · Technical analysis (RFQ + drawings + cross-check)</div>
      <div className={s.sub}>One consolidated report. Every finding shows its source file/page, confidence and status. Read-only here - the discipline lead validates it in step 4.</div>
      <Log messages={step.messages} />
      {opp.status === 'analysis_processing' && <Banner kind="blue"><span className={s.spin}>⟳</span> Analysis running - this can take a few minutes (each drawing sheet is read separately).</Banner>}
      {step.status === 'needs_refresh' && <Banner kind="amber">A revised input arrived after this analysis. Re-run it from step 4 ("Re-run analysis").</Banner>}
      {started ? <Report state={state} api={api} act={act} editable={false} /> : <Banner kind="blue">Starts after management records <b>Go</b> or <b>Conditional Go</b> in step 2.</Banner>}
    </>
  )
}

export function Review({ state, api, act, role }) {
  const opp = state.opportunity, can = useCan(state, role)
  const editable = opp.status === 'engineering_validation' && role === 'discipline_lead'
  const blockers = state.g2_blockers
  return (
    <>
      <div className={s.h2}>4 · Engineering review & clarification</div>
      <div className={s.sub}>The discipline lead turns AI observations into reviewed findings. Only <b>verified / corrected / assumption</b> items reach the proposal; unreviewed or disputed AI output never becomes a proposal fact.</div>
      <Log messages={state.steps[3].messages} />
      {opp.status === 'engineering_validation' && !editable && <Banner kind="amber">Switch your role to <b>discipline_lead</b> (top bar) to review findings. You are viewing read-only.</Banner>}
      {opp.status === 'engineering_validation' && blockers.length > 0 && (
        <Banner kind="red"><b>{blockers.length} item(s) block engineering approval:</b><ul>{blockers.slice(0, 8).map((b, i) => <li key={i}>{b}</li>)}</ul>{blockers.length > 8 && `…and ${blockers.length - 8} more`}</Banner>
      )}
      {opp.status === 'engineering_validation' && blockers.length === 0 && <Banner kind="green">No blocking items. Approving routes the validated findings into proposal drafting.</Banner>}
      {state.findings.length > 0 ? <Report state={state} api={api} act={act} editable={editable} /> : <Banner kind="blue">Nothing to review yet - complete step 3 first.</Banner>}
      {opp.status === 'engineering_validation' && (
        <>
          <GateBox title="Engineering validation gate (G2)" approveLabel="✓ Approve - validated for proposal" returnLabel="↩ Return for rework"
            canApprove={can('g2_approve') && blockers.length === 0} canReturn={can('g2_return')} hint={!can('g2_approve') ? needs(state, 'g2_approve') : 'Resolve the blocking items first'}
            onApprove={c => act(() => api.post(`/api/opportunities/${opp.id}/gate/g2`, { version: opp.version, action: 'approve', comment: c }))}
            onReturn={c => act(() => api.post(`/api/opportunities/${opp.id}/gate/g2`, { version: opp.version, action: 'return', comment: c }))} busy={state.busy} />
          <Btn disabled={!can('rerun_analysis')} title={can('rerun_analysis') ? '' : needs(state, 'rerun_analysis')}
            onClick={() => window.confirm('Re-run the whole analysis? Current findings are kept as superseded and reviews restart.') && act(() => api.post(`/api/opportunities/${opp.id}/run/analysis`, { version: opp.version }))}>↻ Re-run analysis (after new / revised files)</Btn>
        </>
      )}
    </>
  )
}
