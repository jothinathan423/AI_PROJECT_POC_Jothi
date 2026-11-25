import { useState } from 'react'
import { Card, Banner, Chip, Btn, Log, useCan, needs, s } from '../../components/ui'

const REC = {
  A: ['green', 'A · Potentially capable - proceed'],
  B: ['amber', 'B · Proceed conditionally - partner / resource / clarification needed'],
  C: ['red', 'C · No-Go recommendation'],
  D: ['gray', 'D · Insufficient historical evidence - management review required'],
}
const LEVEL = { Strong: 'green', Partial: 'amber', 'No evidence': 'red' }

export default function Capability({ state, api, act, role }) {
  const opp = state.opportunity, cap = state.capability, step = state.steps[1]
  const can = useCan(state, role)
  const [decision, setDecision] = useState('go')
  const [comment, setComment] = useState('')
  const [conditions, setConditions] = useState('')
  const [ev, setEv] = useState({ project_name: '', year: new Date().getFullYear(), client: '', project_type: '', disciplines: '', outcome: 'won', notes: '' })
  const [showEv, setShowEv] = useState(false)
  const decidable = opp.status === 'capability_review'

  return (
    <>
      <div className={s.h2}>2 · Historical experience & capability check</div>
      <div className={s.sub}>First substantive assessment: does AB's own history support this work? The recommendation is computed from the evidence by rules - never guessed. An authorised person makes the decision.</div>
      <Log messages={step.messages} />
      {opp.status === 'closed_no_go' && <Banner kind="red"><b>Closed - No-Go.</b> {opp.close_reason}</Banner>}
      {!cap && <Banner kind="blue">{opp.status === 'capability_processing' ? <><span className={s.spin}>⟳</span> Assessment running…</> : 'Not started - confirm the package in step 1.'}</Banner>}

      {cap && (
        <>
          <Banner kind={{ A: 'green', B: 'amber', C: 'red', D: 'blue' }[cap.recommendation]}>
            <b>Recommendation {REC[cap.recommendation][1]}</b>
            <span className={s.muted}> · confidence {cap.confidence} · {cap.evidence_count} historical record(s) searched</span>
            {cap.decision && <div style={{ marginTop: 4 }}>Management decision: <b>{cap.decision.replace(/_/g, ' ')}</b> by {cap.decision_by}{cap.decision_conditions ? ` - conditions: ${cap.decision_conditions}` : ''}</div>}
          </Banner>
          {cap.narrative && <Card title="Summary"><div className={s.secBody}>{cap.narrative}</div></Card>}

          <Card title="Discipline coverage" body={false}>
            <div className={s.tableWrap}><table className={s.table}>
              <thead><tr><th>Discipline required by the RFQ</th><th>Evidence</th><th>Won projects</th><th>Proposal-only</th><th>Records</th></tr></thead>
              <tbody>
                {cap.coverage.length === 0 && <tr><td colSpan={5} className={s.muted}>No disciplines could be identified from the RFQ.</td></tr>}
                {cap.coverage.map(c => (
                  <tr key={c.discipline}><td><b>{c.discipline.replace(/_/g, ' ')}</b></td><td><Chip color={LEVEL[c.level]}>{c.level}</Chip></td>
                    <td>{c.won}</td><td>{c.proposal_only}</td><td className={s.small}>{c.record_ids.join(', ') || '—'}</td></tr>
                ))}
              </tbody>
            </table></div>
          </Card>

          <Card title={`Matched historical records (${cap.matched_projects.length})`} body={false}>
            <div className={s.tableWrap}><table className={s.table}>
              <thead><tr><th>ID</th><th>Project</th><th>Year</th><th>Type</th><th>Evidence</th><th>Matched</th></tr></thead>
              <tbody>
                {cap.matched_projects.map(p => (
                  <tr key={p.id}><td><b>{p.id}</b></td><td>{p.project_name}<div className={s.quote}>{p.notes}</div></td>
                    <td>{p.year}{p.stale && <Chip color="amber" title="Older than 5 years">stale</Chip>}</td><td>{p.project_type}</td>
                    <td><Chip color={p.evidence_type === 'won_project' ? 'green' : 'gray'}>{p.evidence_type === 'won_project' ? 'Won project' : `Proposal only (${p.outcome})`}</Chip></td>
                    <td className={s.small}>{p.matched_disciplines.join(', ') || 'project type'}</td></tr>
                ))}
              </tbody>
            </table></div>
          </Card>

          {(cap.gaps.length > 0 || cap.risks.length > 0) && (
            <div className={s.grid2}>
              <Card title="Gaps & dependencies"><ul style={{ marginLeft: 16 }}>{cap.gaps.map((g, i) => <li key={i}><b>{g.item}</b> <Chip>{g.kind}</Chip> {g.note}</li>)}</ul></Card>
              <Card title="Risks"><ul style={{ marginLeft: 16 }}>{cap.risks.map((r, i) => <li key={i}>{r}</li>)}</ul></Card>
            </div>
          )}
        </>
      )}

      {decidable && cap && (
        <div className={s.gate}>
          <div className={s.gateTitle}>⚡ Management decision (Gate 2)</div>
          <div className={s.row} style={{ marginBottom: 8 }}>
            {[['go', 'Go'], ['conditional_go', 'Conditional Go'], ['no_go', 'No-Go (close & archive)'], ['request_evidence', 'Request more evidence']].map(([k, l]) => (
              <label key={k}><input type="radio" checked={decision === k} onChange={() => setDecision(k)} /> {l}</label>
            ))}
          </div>
          {decision === 'conditional_go' && <textarea className={s.textarea} placeholder="Named conditions / actions (partner, resource, clarification)…" value={conditions} onChange={e => setConditions(e.target.value)} />}
          <textarea className={s.textarea} style={{ minHeight: 44, marginTop: 6 }} placeholder="Comment / reason (required for No-Go and Request evidence)…" value={comment} onChange={e => setComment(e.target.value)} />
          <div className={s.row} style={{ marginTop: 8 }}>
            <Btn kind="primary" disabled={!can('cap_go') || state.busy} title={can('cap_go') ? '' : needs(state, 'cap_go')}
              onClick={() => act(() => api.post(`/api/opportunities/${opp.id}/capability-decision`, { version: opp.version, decision, comment, conditions }))}>Record decision</Btn>
            <Btn disabled={!can('rerun_capability') || state.busy} onClick={() => act(() => api.post(`/api/opportunities/${opp.id}/run/capability`, { version: opp.version }))}>Re-run assessment</Btn>
            <Btn onClick={() => setShowEv(!showEv)}>{showEv ? 'Hide' : '+ Add historical evidence'}</Btn>
            {!can('cap_go') && <span className={s.note}>{needs(state, 'cap_go')}</span>}
          </div>
          {cap.recommendation === 'D' && <div className={s.note} style={{ marginTop: 6 }}>Insufficient evidence is not a finding that AB lacks capability. Add past RFQs / projects, then re-run.</div>}
          {showEv && (
            <div className={s.grid2} style={{ marginTop: 10 }}>
              {[['project_name', 'Project name'], ['client', 'Client'], ['project_type', 'Type (e.g. road_rehabilitation)'], ['disciplines', 'Disciplines (comma separated)'], ['year', 'Year'], ['notes', 'Notes']].map(([k, l]) => (
                <label key={k} className={s.field}>{l}<input className={s.input} value={ev[k]} onChange={e => setEv({ ...ev, [k]: e.target.value })} /></label>
              ))}
              <label className={s.field}>Outcome<select className={s.select} value={ev.outcome} onChange={e => setEv({ ...ev, outcome: e.target.value })}><option>won</option><option>lost</option><option>declined</option></select></label>
              <div><Btn small kind="primary" onClick={async () => { await act(() => api.post('/api/past-projects', { ...ev, year: +ev.year, disciplines: ev.disciplines.split(',').map(x => x.trim()).filter(Boolean) })); setShowEv(false) }}>Save record</Btn></div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
