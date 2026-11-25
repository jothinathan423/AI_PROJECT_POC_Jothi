import { useState } from 'react'
import { Card, Banner, Btn, StepChip, Log, fmt, s } from '../../components/ui'

/** "View complete process": at-a-glance 7-step view reachable from every opportunity screen. */
export default function ProcessView({ state, onOpen }) {
  const [openLog, setOpenLog] = useState(null)
  const refresh = state.steps.filter(x => x.status === 'needs_refresh')
  return (
    <>
      <div className={s.h2}>Complete process</div>
      <div className={s.sub}>Each step shows its inputs, the AI work done, the outputs, who decided and when. Open any step to see its detail or revisit it.</div>
      {refresh.length > 0 && <Banner kind="amber"><b>Needs refresh:</b> {refresh.map(r => r.title).join(', ')} - a revised input arrived after these were produced; re-run them and obtain fresh approval.</Banner>}
      <div className={s.procGrid}>
        {state.steps.map((st, i) => (
          <Card key={st.step} title={`${i + 1} · ${st.title}`} right={<StepChip status={st.status} />}>
            <div className={s.kv}>
              <div>Inputs</div><div>{st.inputs || '—'}</div>
              <div>AI work</div><div>{st.ai_summary || '—'}{st.ai_at && <div className={s.note}>{fmt(st.ai_at)}</div>}</div>
              <div>Outputs</div><div>{st.outputs || '—'}</div>
              <div>Owner</div><div>{st.owner || state.opportunity.owner || '—'}</div>
              <div>Decision</div><div>{st.decision ? <><b>{st.decision}</b> · {st.decided_by} · {fmt(st.decided_at)}</> : '—'}</div>
            </div>
            <div className={s.row} style={{ marginTop: 10 }}>
              <Btn small kind="primary" onClick={() => onOpen(st.step)}>Open step</Btn>
              {st.messages.length > 0 && <Btn small onClick={() => setOpenLog(openLog === st.step ? null : st.step)}>{openLog === st.step ? 'Hide' : 'Show'} activity</Btn>}
            </div>
            {openLog === st.step && <div style={{ marginTop: 8 }}><Log messages={st.messages} /></div>}
          </Card>
        ))}
      </div>
    </>
  )
}
