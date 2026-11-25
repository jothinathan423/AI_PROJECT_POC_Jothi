import { useState, useEffect } from 'react'
import { Card, Banner, Chip, Btn, Log, GateBox, useCan, needs, fmt, s } from '../../components/ui'

const GATE = { g_cap: 'Capability (Go/No-Go)', g2: 'Engineering', g_prop: 'Proposal content', g3: 'Commercial', g4: 'Final release' }

function Commercial({ state, api, act, role }) {
  const opp = state.opportunity, pv = state.proposal
  const [c, setC] = useState({ lines: [], expenses: [], currency: 'USD', tax_pct: 0 })
  useEffect(() => { if (pv) setC({ lines: pv.commercial?.lines || [], expenses: pv.commercial?.expenses || [], currency: pv.commercial?.currency || 'USD', tax_pct: pv.commercial?.tax_pct || 0 }) }, [pv?.version_no, opp.version]) // eslint-disable-line
  const editable = role === 'commercial_lead' && ['proposal_draft', 'commercial_review'].includes(opp.status)
  const labour = c.lines.reduce((a, l) => a + (+l.hours || 0) * (+l.rate || 0), 0)
  const exp = c.expenses.reduce((a, e) => a + (+e.amount || 0), 0)
  const tax = (labour + exp) * (+c.tax_pct || 0) / 100
  const upd = (k, i, f, v) => setC({ ...c, [k]: c[k].map((x, j) => j === i ? { ...x, [f]: v } : x) })
  return (
    <Card title="Commercial sheet - entered by the authorised commercial lead (the AI never sets fees)"
      right={editable && <Btn small kind="primary" onClick={() => act(() => api.put(`/api/opportunities/${opp.id}/commercial`, { version: opp.version, ...c, tax_pct: +c.tax_pct || 0 }))}>Save fees</Btn>}>
      <div className={s.tableWrap}><table className={s.table}>
        <thead><tr><th>Task / role</th><th>Hours</th><th>Rate</th><th>Amount</th><th /></tr></thead>
        <tbody>
          {c.lines.map((l, i) => (
            <tr key={i}>
              <td><input className={s.input} style={{ width: '100%' }} disabled={!editable} value={l.desc} onChange={e => upd('lines', i, 'desc', e.target.value)} /></td>
              <td><input className={s.input} style={{ width: 80 }} type="number" disabled={!editable} value={l.hours} onChange={e => upd('lines', i, 'hours', e.target.value)} /></td>
              <td><input className={s.input} style={{ width: 90 }} type="number" disabled={!editable} value={l.rate} onChange={e => upd('lines', i, 'rate', e.target.value)} /></td>
              <td>{((+l.hours || 0) * (+l.rate || 0)).toFixed(2)}</td>
              <td>{editable && <Btn small onClick={() => setC({ ...c, lines: c.lines.filter((_, j) => j !== i) })}>✕</Btn>}</td>
            </tr>
          ))}
          {c.expenses.map((e, i) => (
            <tr key={'e' + i}>
              <td><input className={s.input} style={{ width: '100%' }} disabled={!editable} value={e.desc} onChange={ev => upd('expenses', i, 'desc', ev.target.value)} placeholder="Expense" /></td>
              <td colSpan={2} className={s.muted}>expense</td>
              <td><input className={s.input} style={{ width: 90 }} type="number" disabled={!editable} value={e.amount} onChange={ev => upd('expenses', i, 'amount', ev.target.value)} /></td>
              <td>{editable && <Btn small onClick={() => setC({ ...c, expenses: c.expenses.filter((_, j) => j !== i) })}>✕</Btn>}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {editable && <div className={s.row} style={{ marginTop: 8 }}>
        <Btn small onClick={() => setC({ ...c, lines: [...c.lines, { desc: '', hours: 0, rate: 0 }] })}>+ Labour line</Btn>
        <Btn small onClick={() => setC({ ...c, expenses: [...c.expenses, { desc: '', amount: 0 }] })}>+ Expense</Btn>
        <label className={s.small}>Currency <input className={s.input} style={{ width: 60 }} value={c.currency} onChange={e => setC({ ...c, currency: e.target.value })} /></label>
        <label className={s.small}>Tax % <input className={s.input} style={{ width: 60 }} type="number" value={c.tax_pct} onChange={e => setC({ ...c, tax_pct: e.target.value })} /></label>
      </div>}
      <div style={{ marginTop: 10, fontWeight: 600 }}>Labour {labour.toFixed(2)} · Expenses {exp.toFixed(2)} · Tax {tax.toFixed(2)} · <span style={{ color: '#1d4ed8' }}>Total {(labour + exp + tax).toFixed(2)} {c.currency}</span></div>
      {!editable && <div className={s.note} style={{ marginTop: 4 }}>Switch role to commercial_lead during proposal draft / commercial review to edit.</div>}
    </Card>
  )
}

export default function Approval({ state, api, act, role }) {
  const opp = state.opportunity, can = useCan(state, role)
  const post = (gate, action) => c => act(() => api.post(`/api/opportunities/${opp.id}/gate/${gate}`, { version: opp.version, action, comment: c }))
  const qaFail = state.qa.filter(q => q.status === 'fail').length
  return (
    <>
      <div className={s.h2}>6 · Commercial review, final QA & approval</div>
      <div className={s.sub}>Release needs engineering, commercial and final approvals tied to the <b>exact proposal version</b>. Separation of duties: the final approver cannot be someone who approved earlier gates on this version.</div>
      <Log messages={state.steps[5].messages} />
      {!state.proposal && <Banner kind="blue">Available once a proposal draft exists (step 5).</Banner>}
      {state.proposal && <Commercial state={state} api={api} act={act} role={role} />}

      {opp.status === 'commercial_review' && (
        <GateBox title="Commercial gate (G3) - commercial lead" approveLabel="✓ Commercial approved" returnLabel="↩ Return to proposal"
          canApprove={can('g3_approve') && state.proposal?.totals.total > 0} canReturn={can('g3_return')}
          hint={!can('g3_approve') ? needs(state, 'g3_approve') : 'Enter and save the fees first'} onApprove={post('g3', 'approve')} onReturn={post('g3', 'return')} busy={state.busy} />
      )}

      {state.qa.length > 0 && (
        <Card title="Final QA checklist" right={qaFail ? <Chip color="red">{qaFail} blocking</Chip> : <Chip color="green">no blockers</Chip>} body={false}>
          <div className={s.tableWrap}><table className={s.table}><tbody>
            {state.qa.map(q => (
              <tr key={q.id}><td style={{ width: 70 }}><Chip color={q.status === 'pass' ? 'green' : q.status === 'fail' ? 'red' : 'amber'}>{q.status}</Chip></td><td>{q.label}</td><td className={s.muted}>{q.detail}</td></tr>
            ))}
          </tbody></table></div>
        </Card>
      )}

      {opp.status === 'final_approval' && (
        <GateBox title="Final release gate (G4) - authorised approver" approveLabel="✓ Approve for release" returnLabel="↩ Return to commercial review"
          canApprove={can('g4_approve') && qaFail === 0} canReturn={can('g4_return')}
          hint={!can('g4_approve') ? needs(state, 'g4_approve') : 'Fix the blocking QA items first'} onApprove={post('g4', 'approve')} onReturn={post('g4', 'return')} busy={state.busy} />
      )}

      <Card title="Approval history (version-bound)" body={false}>
        <div className={s.tableWrap}><table className={s.table}>
          <thead><tr><th>Gate</th><th>Decision</th><th>By</th><th>Proposal</th><th>Valid</th><th>Comment</th><th>When</th></tr></thead>
          <tbody>
            {state.approvals.length === 0 && <tr><td colSpan={7} className={s.muted}>No decisions yet.</td></tr>}
            {state.approvals.map((a, i) => (
              <tr key={i}><td>{GATE[a.gate] || a.gate}</td><td><Chip color={a.decision === 'returned' || a.decision === 'no_go' ? 'red' : 'green'}>{a.decision.replace(/_/g, ' ')}</Chip></td>
                <td>{a.actor_name} <span className={s.note}>({a.actor_role})</span></td><td>{a.proposal_version ? `v${a.proposal_version}` : '—'}</td>
                <td>{a.decision === 'approved' ? (a.valid ? <Chip color="green">valid</Chip> : <Chip color="purple">superseded</Chip>) : '—'}</td><td className={s.small}>{a.comment}</td><td className={s.small}>{fmt(a.created_at)}</td></tr>
            ))}
          </tbody>
        </table></div>
      </Card>
    </>
  )
}
