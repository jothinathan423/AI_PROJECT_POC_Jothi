import { useState, useEffect } from 'react'
import { client, errText, loadActor, saveActor, ROLES, STATUS_LABEL } from './api'
import Header from './components/Header'
import { Banner, Btn, Chip, Card, fmt, s } from './components/ui'
import Workspace from './pages/Workspace'
import './App.css'

function OppList({ actor, onOpen }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const api = client(actor)
  const load = () => api.get('/api/opportunities').then(r => setRows(r.data)).catch(e => setErr(errText(e)))
  useEffect(() => { load() }, []) // eslint-disable-line
  async function create() {
    try { const { data } = await api.post('/api/opportunities', {}); onOpen(data.id) } catch (e) { setErr(errText(e)) }
  }
  return (
    <div className={s.main}><div className={s.wrap}>
      <div className={s.h2}>Opportunities</div>
      <div className={s.sub}>Each opportunity is one RFQ package taken through the 7-step workflow: intake → capability check → technical analysis → engineering review → proposal → approval → release & archive.</div>
      {err && <Banner kind="red">{err}</Banner>}
      <div className={s.row} style={{ marginBottom: 12 }}>
        <Btn kind="primary" disabled={!actor.name.trim() || actor.role !== 'coordinator'} onClick={create}>+ New opportunity</Btn>
        {(!actor.name.trim() || actor.role !== 'coordinator') && <span className={s.note}>Enter your name and choose the role "Proposal coordinator" to create one.</span>}
      </div>
      <Card title="All opportunities" body={false}>
        <div className={s.tableWrap}><table className={s.table}>
          <thead><tr><th>ID</th><th>Project</th><th>Client</th><th>Status</th><th>Package</th><th>Updated</th><th /></tr></thead>
          <tbody>
            {rows === null && <tr><td colSpan={7}>Loading…</td></tr>}
            {rows?.length === 0 && <tr><td colSpan={7} className={s.muted}>No opportunities yet.</td></tr>}
            {rows?.map(o => (
              <tr key={o.id}><td><b>{o.code}</b></td><td>{o.project_name || <i className={s.muted}>untitled</i>}</td><td>{o.client}</td>
                <td><Chip color={o.status === 'archived' || o.status === 'approved_for_export' ? 'green' : o.status === 'closed_no_go' ? 'red' : 'blue'}>{STATUS_LABEL[o.status] || o.status}</Chip></td>
                <td>{o.package_status}</td><td className={s.small}>{fmt(o.updated_at)}</td><td><Btn small onClick={() => onOpen(o.id)}>Open</Btn></td></tr>
            ))}
          </tbody>
        </table></div>
      </Card>
    </div></div>
  )
}

export default function App() {
  const [actor, setActor] = useState(loadActor)
  const [oppId, setOppId] = useState(() => { const v = localStorage.getItem('oppId'); return v ? +v : null })
  const [info, setInfo] = useState(null)
  useEffect(() => saveActor(actor), [actor])
  useEffect(() => { try { oppId ? localStorage.setItem('oppId', oppId) : localStorage.removeItem('oppId') } catch { /* ignore */ } }, [oppId])

  return (
    <div className={s.shell}>
      <Header statusLabel={info ? (STATUS_LABEL[info.opportunity.status] || info.opportunity.status) : 'Opportunities'} isActive={!!info?.busy} />
      <div className={s.actorBar}>
        <label>Acting as</label>
        <input className={s.input} placeholder="Your name" value={actor.name} onChange={e => setActor({ ...actor, name: e.target.value })} />
        <select className={s.select} value={actor.role} onChange={e => setActor({ ...actor, role: e.target.value })}>
          {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className={s.note}>Demo role switcher - not authentication. Every decision is recorded under this name and role; approvers must differ from earlier gate approvers.</span>
      </div>
      {oppId
        ? <Workspace key={oppId} oppId={oppId} actor={actor} onBack={() => { setOppId(null); setInfo(null) }} onStatus={setInfo} />
        : <OppList actor={actor} onOpen={setOppId} />}
    </div>
  )
}
