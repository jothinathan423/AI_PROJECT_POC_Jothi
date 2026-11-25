import { useState, useEffect, useRef } from 'react'
import { Card, Banner, Chip, Btn, Log, useCan, needs, s, cx } from '../../components/ui'

const KINDS = ['rfq', 'drawing', 'spec', 'boq', 'addendum', 'report', 'cad', 'other']
const FIELDS = [['client', 'Client'], ['project_name', 'Project name'], ['rfq_reference', 'RFQ reference'], ['location', 'Location'],
  ['procurement_type', 'Procurement type'], ['owner', 'Internal owner'], ['submission_deadline', 'Submission deadline'], ['clarification_deadline', 'Clarification deadline']]

export default function Intake({ state, api, act, role }) {
  const opp = state.opportunity
  const can = useCan(state, role)
  const draft = opp.status === 'draft'
  const canEdit = draft && role === 'coordinator'
  const [form, setForm] = useState({})
  const [drag, setDrag] = useState(false)
  const fileRef = useRef()
  const step = state.steps[0]

  useEffect(() => { setForm(Object.fromEntries(FIELDS.map(([k]) => [k, opp[k] || '']))) }, [opp.id, opp.version]) // eslint-disable-line

  async function upload(fileList) {
    if (!fileList?.length) return
    const fd = new FormData()
    ;[...fileList].forEach(f => fd.append('files', f))
    const r = await act(() => api.post(`/api/opportunities/${opp.id}/files`, fd))
    const bad = r?.data?.results?.filter(x => !x.ok)
    if (bad?.length) alert(bad.map(b => `${b.filename}: ${b.error}`).join('\n'))
  }
  const pkg = state.package
  const pkgKind = pkg.status === 'Ready' ? 'green' : pkg.status === 'Warning' ? 'amber' : 'red'

  return (
    <>
      <div className={s.h2}>1 · RFQ intake & package upload</div>
      <div className={s.sub}>Create the opportunity and collect the client's RFQ package in one version-controlled workspace. Originals are never overwritten; a re-upload becomes a new revision.</div>
      <Log messages={step.messages} />

      <Card title="Opportunity details" right={canEdit && <Btn small kind="primary" onClick={() => act(() => api.patch(`/api/opportunities/${opp.id}`, form))}>Save details</Btn>}>
        <div className={s.grid2}>
          {FIELDS.map(([k, label]) => (
            <label key={k} className={s.field}>{label}
              <input className={s.input} value={form[k] ?? ''} disabled={!canEdit} onChange={e => setForm({ ...form, [k]: e.target.value })} />
            </label>
          ))}
        </div>
        {!canEdit && draft && <div className={s.note} style={{ marginTop: 8 }}>Only the proposal coordinator edits these details. Blank fields are filled from the RFQ during analysis.</div>}
      </Card>

      <Card title={`Package manifest · ${pkg.counts.files} file(s) · ${pkg.counts.pages} page(s)`} right={<Chip color={pkgKind}>Package: {pkg.status}</Chip>}>
        {opp.status !== 'draft' && opp.status !== 'closed_no_go' && opp.status !== 'archived' && opp.status !== 'approved_for_export' &&
          <Banner kind="amber">Uploading a new or revised file after intake marks the downstream steps <b>needs refresh</b> and invalidates approvals; the old file is preserved as a superseded revision.</Banner>}
        {pkg.missing.length > 0 && <Banner kind="red"><b>Cannot proceed - missing:</b><ul>{pkg.missing.map(m => <li key={m}>{m}</li>)}</ul></Banner>}
        {pkg.warnings.length > 0 && <Banner kind="amber"><b>Warnings</b><ul>{pkg.warnings.map((m, i) => <li key={i}>{m}</li>)}</ul></Banner>}

        {!['approved_for_export', 'archived', 'closed_no_go'].includes(opp.status) && !opp.status.endsWith('_processing') && (
          <div className={cx(s.drop, drag && s.dropOn)}
            onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}>
            Drag RFQ, drawings, specifications, BOQ, addenda and reports here, or{' '}
            <Btn small onClick={() => fileRef.current.click()}>choose files</Btn>
            <input ref={fileRef} type="file" multiple hidden onChange={e => { upload(e.target.files); e.target.value = '' }} />
            <div className={s.note} style={{ marginTop: 4 }}>PDF · DOCX · XLSX/CSV · images · CAD (kept as reference only) · max 50 MB each</div>
          </div>
        )}

        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead><tr><th>File</th><th>Type</th><th>Pages</th><th>Rev</th><th>Status</th><th>Issues</th></tr></thead>
            <tbody>
              {state.files.length === 0 && <tr><td colSpan={6} className={s.muted}>No files uploaded yet.</td></tr>}
              {state.files.map(f => (
                <tr key={f.id} style={f.superseded || f.duplicate_of ? { opacity: .55 } : null}>
                  <td><b>{f.filename}</b><div className={cx(s.muted, s.small)}>{(f.size_bytes / 1024).toFixed(0)} KB · {f.uploaded_by}</div></td>
                  <td>
                    <select className={s.select} value={f.kind} disabled={!draft} onChange={e => act(() => api.patch(`/api/files/${f.id}`, { kind: e.target.value }))}>
                      {KINDS.map(k => <option key={k}>{k}</option>)}
                    </select>
                  </td>
                  <td>{f.page_count} <span className={s.muted}>{f.locator_kind}{f.page_count === 1 ? '' : 's'}</span></td>
                  <td>v{f.revision_no}{f.superseded ? ' (superseded)' : ''}</td>
                  <td><Chip color={f.extract_status === 'ready' ? 'green' : f.extract_status === 'failed' ? 'red' : 'gray'}>{f.extract_status.replace('_', ' ')}</Chip></td>
                  <td className={s.small}>{f.issues.join(' · ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {draft && (
          <div className={s.row} style={{ marginTop: 12 }}>
            <Btn kind="primary" disabled={!can('confirm_intake') || pkg.status === 'Incomplete' || state.busy}
              title={can('confirm_intake') ? '' : needs(state, 'confirm_intake')}
              onClick={() => act(() => api.post(`/api/opportunities/${opp.id}/confirm-intake`, { version: opp.version }))}>
              Confirm package & run historical capability check →
            </Btn>
            {!can('confirm_intake') && <span className={s.note}>{needs(state, 'confirm_intake')}</span>}
          </div>
        )}
      </Card>
    </>
  )
}
