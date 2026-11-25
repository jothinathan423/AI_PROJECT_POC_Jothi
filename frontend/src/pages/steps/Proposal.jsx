import { useState, useEffect } from 'react'
import { Card, Banner, Chip, Btn, Log, GateBox, useCan, needs, s } from '../../components/ui'

const SRC = { ai: ['blue', 'AI draft'], template: ['gray', 'template'], placeholder: ['amber', 'placeholder'], human: ['green', 'edited'], commercial_lead: ['green', 'commercial'] }

export default function Proposal({ state, api, act, role }) {
  const opp = state.opportunity, pv = state.proposal, can = useCan(state, role)
  const [edits, setEdits] = useState({})
  useEffect(() => setEdits({}), [pv?.version_no])
  const editRoles = ['proposal_manager', 'commercial_lead']
  const editable = pv && ['proposal_draft', 'commercial_review', 'final_approval'].includes(opp.status) && editRoles.includes(role)
  const dirty = Object.keys(edits).length > 0

  return (
    <>
      <div className={s.h2}>5 · Proposal preparation & AI drafting</div>
      <div className={s.sub}>Drafted from <b>verified findings only</b>, with citations to finding IDs. Team and fee sections stay as controlled placeholders - the AI never invents staff, experience or fees.</div>
      <Log messages={state.steps[4].messages} />
      {opp.status === 'proposal_processing' && <Banner kind="blue"><span className={s.spin}>⟳</span> Drafting the proposal…</Banner>}
      {!pv && opp.status !== 'proposal_processing' && <Banner kind="blue">Starts automatically once engineering validation (step 4) is approved.</Banner>}

      {pv && (
        <>
          <Banner kind="blue">Proposal <b>v{pv.version_no}</b> · {pv.status} · {pv.note}. Editing any section creates a new version and <b>invalidates</b> the content / commercial / final approvals that depended on the old one.</Banner>
          {state.proposal_versions.length > 1 && (
            <div className={s.note} style={{ marginBottom: 8 }}>Version history: {state.proposal_versions.map(v => `v${v.version_no} (${v.status})`).join(' → ')}</div>
          )}
          {pv.sections.map(sec => {
            const [c, l] = SRC[sec.source] || ['gray', sec.source]
            const locked = sec.key === 'commercial' && role !== 'commercial_lead'
            return (
              <div key={sec.key} className={s.sec}>
                <div className={s.secTitle}>{sec.number}. {sec.title} <Chip color={c}>{l}</Chip>
                  {sec.placeholder && <Chip color="amber">contains [AB to …] placeholder</Chip>}
                  {(sec.finding_ids || []).length > 0 && <span className={s.note}>sources: {sec.finding_ids.map(i => `F${i}`).join(', ')}</span>}
                  {sec.unsupported_citations?.length > 0 && <Chip color="red">removed citation to unverified item</Chip>}
                </div>
                {editable && !locked
                  ? <textarea className={s.textarea} style={{ minHeight: 110 }} value={edits[sec.key] ?? sec.content} onChange={e => setEdits({ ...edits, [sec.key]: e.target.value })} />
                  : <div className={s.secBody}>{sec.content}</div>}
              </div>
            )
          })}
          {editable && (
            <div className={s.row} style={{ marginBottom: 12 }}>
              <Btn kind="primary" disabled={!dirty} onClick={() => act(() => api.put(`/api/opportunities/${opp.id}/proposal/sections`, { version: opp.version, sections: Object.entries(edits).map(([key, content]) => ({ key, content })) }))}>Save as new version</Btn>
              <Btn disabled={!can('rerun_proposal')} onClick={() => window.confirm('Re-draft all AI sections from the verified findings? This creates a new version.') && act(() => api.post(`/api/opportunities/${opp.id}/run/proposal`, { version: opp.version }))}>↻ Re-draft</Btn>
            </div>
          )}

          <Card title={`Requirement compliance matrix (${pv.compliance.filter(c => c.status === 'addressed').length}/${pv.compliance.length} mapped)`} body={false}>
            <div className={s.tableWrap}><table className={s.table}>
              <thead><tr><th>Requirement</th><th>Mandatory</th><th>Source</th><th>Answered in section(s)</th><th>Status</th></tr></thead>
              <tbody>
                {pv.compliance.length === 0 && <tr><td colSpan={5} className={s.muted}>No verified requirements.</td></tr>}
                {pv.compliance.map(c => (
                  <tr key={c.requirement_id}><td>F{c.requirement_id} · {c.text}</td><td>{c.mandatory ? '⭐ yes' : ''}</td><td className={s.small}>{c.source}</td>
                    <td className={s.small}>{c.sections.join(', ') || '—'}</td><td><Chip color={c.status === 'addressed' ? 'green' : 'amber'}>{c.status}</Chip></td></tr>
                ))}
              </tbody>
            </table></div>
          </Card>

          {opp.status === 'proposal_draft' && (
            <GateBox title="Proposal content gate - proposal manager" approveLabel="✓ Content approved → commercial review" returnLabel="↩ Return for rework"
              canApprove={can('g_prop_approve') && !dirty} canReturn={can('g_prop_return')} hint={dirty ? 'Save your edits first' : needs(state, 'g_prop_approve')}
              onApprove={c => act(() => api.post(`/api/opportunities/${opp.id}/gate/g_prop`, { version: opp.version, action: 'approve', comment: c }))}
              onReturn={c => act(() => api.post(`/api/opportunities/${opp.id}/gate/g_prop`, { version: opp.version, action: 'return', comment: c }))} busy={state.busy} />
          )}
        </>
      )}
    </>
  )
}
