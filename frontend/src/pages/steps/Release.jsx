import { useState, useEffect } from 'react'
import { API } from '../../api'
import { Card, Banner, Chip, Btn, useCan, needs, fmt, s } from '../../components/ui'

export default function Release({ state, api, act, role }) {
  const opp = state.opportunity, can = useCan(state, role), pv = state.proposal
  const final = ['approved_for_export', 'archived'].includes(opp.status)
  const [f, setF] = useState({ status: 'not_submitted', submitted_at: '', channel: '', receipt_ref: '', outcome: '', notes: '' })
  const [showAudit, setShowAudit] = useState(false)
  useEffect(() => { if (state.submission) setF(state.submission) }, [state.submission?.status, state.submission?.outcome]) // eslint-disable-line
  const canRecord = final && ['coordinator', 'approver'].includes(role)

  return (
    <>
      <div className={s.h2}>7 · Final proposal, submission record & archive</div>
      <div className={s.sub}>There is no automatic client submission: AB submits the approved proposal manually and records it here. Archiving keeps the source package, analysis, approvals and audit history.</div>
      {!pv && <Banner kind="blue">No proposal yet.</Banner>}
      {pv && !final && <Banner kind="amber">The proposal is not yet approved for release - exports are marked <b>DRAFT</b> and must not be sent to the client.</Banner>}
      {final && <Banner kind="green">Approved proposal <b>v{pv.version_no}</b> locked for release{opp.status === 'archived' ? ' and archived.' : '.'}</Banner>}

      {pv && (
        <Card title="Approved proposal & package contents">
          <p className={s.small} style={{ marginBottom: 8 }}>The DOCX contains: proposal sections, compliance matrix, drawing register, RFI register, approval history and the full audit trail.</p>
          <Btn kind={final ? 'green' : undefined} onClick={() => window.open(`${API}/api/opportunities/${opp.id}/export`, '_blank')}>⬇ Download {final ? 'FINAL' : 'DRAFT'} proposal (DOCX)</Btn>
        </Card>
      )}

      <Card title="Submission tracking" right={<Chip color={state.submission?.status === 'not_submitted' || !state.submission ? 'gray' : 'green'}>{(state.submission?.status || 'not_submitted').replace('_', ' ')}</Chip>}>
        <div className={s.grid2}>
          <label className={s.field}>Status<select className={s.select} disabled={!canRecord} value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="not_submitted">Not submitted</option><option value="submitted">Submitted</option><option value="acknowledged">Acknowledged</option></select></label>
          <label className={s.field}>Submission date<input className={s.input} type="date" disabled={!canRecord} value={f.submitted_at} onChange={e => setF({ ...f, submitted_at: e.target.value })} /></label>
          <label className={s.field}>Channel<input className={s.input} disabled={!canRecord} value={f.channel} placeholder="e.g. client portal / email" onChange={e => setF({ ...f, channel: e.target.value })} /></label>
          <label className={s.field}>Receipt reference<input className={s.input} disabled={!canRecord} value={f.receipt_ref} onChange={e => setF({ ...f, receipt_ref: e.target.value })} /></label>
          <label className={s.field}>Outcome (when known)<select className={s.select} disabled={!canRecord} value={f.outcome} onChange={e => setF({ ...f, outcome: e.target.value })}><option value="">—</option><option>won</option><option>lost</option><option>withdrawn</option></select></label>
          <label className={s.field}>Notes<input className={s.input} disabled={!canRecord} value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></label>
        </div>
        <div className={s.row} style={{ marginTop: 10 }}>
          <Btn kind="primary" disabled={!canRecord} onClick={() => act(() => api.put(`/api/opportunities/${opp.id}/submission`, f))}>Save submission record</Btn>
          {opp.status === 'approved_for_export' && (
            <Btn kind="green" disabled={!can('archive') || state.submission?.status === undefined || state.submission?.status === 'not_submitted'} title={can('archive') ? 'Record the submission first' : needs(state, 'archive')}
              onClick={() => act(() => api.post(`/api/opportunities/${opp.id}/archive`, { version: opp.version }))}>Archive opportunity</Btn>
          )}
          {!canRecord && final && <span className={s.note}>Role coordinator or approver records submissions. Outcomes won/lost are indexed into the historical library for future capability checks.</span>}
        </div>
      </Card>

      <Card title={`Audit trail (${state.audit.length}${state.audit.length >= 300 ? '+' : ''} events, append-only)`} right={<Btn small onClick={() => setShowAudit(!showAudit)}>{showAudit ? 'Hide' : 'Show'}</Btn>} body={false}>
        {showAudit && <div className={s.tableWrap}><table className={s.table}>
          <thead><tr><th>#</th><th>When</th><th>Who</th><th>Action</th><th>Status change</th><th>Reason</th></tr></thead>
          <tbody>{state.audit.map(e => (
            <tr key={e.seq}><td>{e.seq}</td><td className={s.small}>{fmt(e.ts)}</td><td>{e.actor_name} <span className={s.note}>({e.actor_role})</span></td><td>{e.action.replace(/_/g, ' ')}{e.proposal_version ? ` · v${e.proposal_version}` : ''}</td>
              <td className={s.small}>{e.from_status !== e.to_status ? `${e.from_status} → ${e.to_status}` : ''}</td><td className={s.small}>{e.reason}</td></tr>
          ))}</tbody>
        </table></div>}
      </Card>
    </>
  )
}
