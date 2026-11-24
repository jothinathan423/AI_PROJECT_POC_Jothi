import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import Header from '../components/Header'
import PipelineStep from '../components/PipelineStep'
import ResultCard, { Row, Tag, RfiItem } from '../components/ResultCard'
import styles from './PipelinePage.module.css'

const API = 'http://localhost:8001'

const STEPS = [
  { id: 'g0',       label: 'G0',  title: 'Intake Acceptance',       badge: 'Auto',     badgeType: 'auto' },
  { id: 'g1',       label: 'G1',  title: 'Package Quality Gate',    badge: 'Auto',     badgeType: 'auto' },
  { id: 'ai_rfq',   label: 'AI',  title: 'RFQ Document Analysis',   badge: 'AI',       badgeType: 'ai' },
  { id: 'ai_draw',  label: 'AI',  title: 'Drawing Analysis',        badge: 'AI Vision',badgeType: 'ai' },
  { id: 'cross',    label: 'AI',  title: 'Cross-Document Analysis', badge: 'AI',       badgeType: 'ai' },
  { id: 'g2',       label: 'G2',  title: 'Engineering Validation',  badge: 'Human Gate',badgeType: 'gate', gate: true },
  { id: 'proposal', label: 'AI',  title: 'Proposal Assembly',       badge: 'AI + Template',badgeType: 'ai' },
  { id: 'g3',       label: 'G3',  title: 'Commercial Review',       badge: 'Human Gate',badgeType: 'gate', gate: true },
  { id: 'g4',       label: 'G4',  title: 'Final QA & Release',      badge: 'Human Gate',badgeType: 'gate', gate: true },
  { id: 'export',   label: '📤', title: 'Export & Archive',        badge: 'Final',    badgeType: 'auto' },
]

const STEP_DESC = {
  g0:       'Capture opportunity metadata and validate package manifest',
  g1:       'Check file readability, page counts and drawing revisions',
  ai_rfq:   'Extract project requirements, scope and submission rules via AI',
  ai_draw:  'Classify sheets and extract labels, notes and schedules via AI Vision',
  cross:    'Compare RFQ, drawings, specs and BOQ — flag conflicts and gaps',
  g2:       'Discipline lead validates drawing findings and assumptions',
  proposal: 'Map validated requirements to AB-approved proposal template',
  g3:       'Proposal manager reviews coverage, effort, fees and compliance',
  g4:       'Authorised AB approver checks mandatory sections and approvals',
  export:   'Generate approved DOCX proposal and full audit trail',
}

function initStepState() {
  const s = {}
  STEPS.forEach(step => { s[step.id] = { status: 'pending', messages: [], connActive: false } })
  return s
}

export default function PipelinePage() {
  const [docs, setDocs] = useState(null)
  const [runId, setRunId] = useState(null)
  const [running, setRunning] = useState(false)
  const [complete, setComplete] = useState(false)
  const [statusLabel, setStatusLabel] = useState('Ready')
  const [stepState, setStepState] = useState(initStepState)
  const [results, setResults] = useState({ rfq: null, drawing: null, rfis: null, proposal: null })
  const esRef = useRef(null)
  const stepRefs = useRef({})

  // Auto-scroll to the currently active step
  function scrollToStep(id) {
    const el = stepRefs.current[id]
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  useEffect(() => {
    axios.get(`${API}/api/documents`).then(r => setDocs(r.data)).catch(() => {})
  }, [])

  function updateStep(id, patch) {
    setStepState(prev => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }

  function addMsg(id, msg) {
    setStepState(prev => ({
      ...prev,
      [id]: { ...prev[id], messages: [...(prev[id]?.messages || []), msg] }
    }))
  }

  async function startAnalysis() {
    if (running) return
    setRunning(true)
    setComplete(false)
    setStepState(initStepState())
    setResults({ rfq: null, drawing: null, rfis: null, proposal: null })
    setStatusLabel('Processing…')

    const { data } = await axios.post(`${API}/api/start`)
    const id = data.run_id
    setRunId(id)

    const es = new EventSource(`${API}/api/stream/${id}`)
    esRef.current = es

    es.addEventListener('progress', e => {
      const d = JSON.parse(e.data)
      const step = d.step

      if (d.waiting) {
        updateStep(step, { status: 'waiting' })
        setStatusLabel(`Awaiting ${step.toUpperCase()} approval`)
        return
      }
      if (d.returned) {
        updateStep(step, { status: 'returned' })
        addMsg(step, `↩ ${d.message}`)
        setRunning(false)
        setStatusLabel('Returned for rework')
        return
      }
      if (d.failed) {
        updateStep(step, { status: 'returned' })
        addMsg(step, `✗ ${d.message}`)
        setRunning(false)
        setStatusLabel('Quality check failed')
        return
      }

      updateStep(step, { status: d.done ? 'done' : 'running' })
      addMsg(step, d.message)
      scrollToStep(step)

      if (d.done) {
        const prevIdx = STEPS.findIndex(s => s.id === step)
        if (prevIdx >= 0) updateStep(step, { connActive: true })
        // scroll to next step
        const next = STEPS[prevIdx + 1]
        if (next) setTimeout(() => scrollToStep(next.id), 150)
      }

      // populate results as they arrive
      if (d.done && d.data) {
        if (step === 'ai_rfq') setResults(r => ({ ...r, rfq: d.data }))
        if (step === 'ai_draw') setResults(r => ({ ...r, drawing: d.data }))
        if (step === 'cross') setResults(r => ({ ...r, rfis: d.data }))
        if (step === 'proposal') setResults(r => ({ ...r, proposal: d.data }))
      }
    })

    es.addEventListener('pipeline_done', e => {
      const d = JSON.parse(e.data)
      es.close()
      if (d.status === 'complete') {
        setComplete(true)
        setRunning(false)
        setStatusLabel('Complete — Ready for Export')
      } else if (d.status === 'returned') {
        setRunning(false)
        setStatusLabel(`Returned at ${(d.gate || '').toUpperCase()} for rework`)
      } else if (d.status === 'failed') {
        setRunning(false)
        setStatusLabel('Quality gate failed')
      } else if (d.status === 'error') {
        setRunning(false)
        setStatusLabel(`Error: ${d.message || 'Unknown error'}`)
      }
    })

    // ping keeps connection alive — no UI action needed
    es.addEventListener('ping', () => {})

    // gate_ack confirms gate click registered
    es.addEventListener('gate_ack', e => {
      const d = JSON.parse(e.data)
      if (d.action === 'approve') {
        updateStep(d.gate, { status: 'done' })
      }
    })

    es.addEventListener('error', () => { es.close(); setRunning(false) })
  }

  async function handleGate(gate, action, comment = '') {
    await axios.post(`${API}/api/gate/${runId}/${gate}`, { action, role: 'Reviewer', comment })
    if (action === 'approve') {
      updateStep(gate, { status: 'done' })
      addMsg(gate, `✓ Approved`)
    }
  }

  function downloadProposal() {
    window.open(`${API}/api/export/${runId}/proposal`, '_blank')
  }

  const rfq = results.rfq || {}
  const drawing = results.drawing || {}
  const rfis = results.rfis?.discrepancies || []
  const proposalSections = results.proposal?.sections || []

  return (
    <div>
      <Header statusLabel={statusLabel} isActive={running} />

      <div className={styles.main}>
        {/* ── Left: docs + pipeline ── */}
        <div className={styles.left}>

          {/* Documents card */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardIcon}>📂</span>
              <span className={styles.cardTitle}>Pre-Loaded Package</span>
            </div>
            <div className={styles.cardBody}>
              <DocItem
                icon="📄"
                name={docs?.rfq?.name || 'Loading…'}
                meta={`RFQ Document · ${docs?.rfq ? Math.round(docs.rfq.size/1024) + ' KB' : ''}`}
                badge="RFQ"
                badgeCls={styles.badgeRfq}
              />
              <DocItem
                icon="📐"
                name={docs?.drawing?.name || 'Loading…'}
                meta={`Engineering Drawing · ${docs?.drawing ? Math.round(docs.drawing.size/1024) + ' KB' : ''}`}
                badge="Drawing"
                badgeCls={styles.badgeDraw}
              />
              <button
                className={styles.startBtn}
                onClick={startAnalysis}
                disabled={running || complete}
              >
                {running
                  ? <><span className={styles.spin}>⟳</span> Processing…</>
                  : complete
                  ? '✓ Analysis Complete'
                  : <><span>▶</span> START ANALYSIS</>}
              </button>
            </div>
          </div>

          {/* Pipeline card */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardIcon}>⚙️</span>
              <span className={styles.cardTitle}>Pipeline Progress</span>
            </div>
            <div className={styles.cardBody}>
              {STEPS.map((step, idx) => {
                const s = stepState[step.id]
                return (
                  <PipelineStep
                    key={step.id}
                    id={step.id}
                    label={step.label}
                    title={step.title}
                    badge={step.badge}
                    badgeType={step.badgeType}
                    description={STEP_DESC[step.id]}
                    messages={s.messages}
                    status={s.status}
                    showConnector={idx < STEPS.length - 1}
                    connectorActive={s.connActive}
                    gateActions={!!step.gate}
                    onApprove={() => handleGate(step.id, 'approve')}
                    onReturn={(comment) => handleGate(step.id, 'return', comment)}
                    stepRef={el => { stepRefs.current[step.id] = el }}
                  />
                )
              })}
            </div>
          </div>
        </div>

        {/* ── Right: results ── */}
        <div className={styles.right}>

          {/* Placeholder shown while pipeline hasn't produced results yet */}
          {!running && !complete && !results.rfq && (
            <div className={styles.placeholder}>
              <div className={styles.placeholderIcon}>📊</div>
              <div className={styles.placeholderText}>Analysis results will appear here as each step completes</div>
              <div className={styles.placeholderSub}>Click <strong>START ANALYSIS</strong> to begin</div>
            </div>
          )}
          {running && !results.rfq && (
            <div className={styles.placeholder}>
              <div className={styles.placeholderIcon} style={{animation:'spin 1.2s linear infinite',display:'inline-block'}}>⟳</div>
              <div className={styles.placeholderText}>Pipeline running — results will appear here as steps complete</div>
            </div>
          )}

          {/* RFQ Requirements */}
          <ResultCard icon="📋" title="RFQ Requirements" count={Object.keys(rfq).length || undefined} visible={!!results.rfq}>
            {Object.entries(rfq).map(([k, v]) => (
              <Row key={k} label={k.replace(/_/g,' ')} value={Array.isArray(v) ? v.join(', ') : v} />
            ))}
          </ResultCard>

          {/* Drawing Register */}
          <ResultCard icon="📐" title="Drawing Register" count={drawing.sheets?.length} visible={!!results.drawing}>
            {(drawing.sheets || []).map((sheet, i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <Row label="Sheet ID" value={sheet.sheet_id || '—'} />
                <Row label="Title" value={sheet.title || '—'} />
                <Row label="Discipline" value={sheet.discipline || '—'} />
                <Row label="Revision" value={sheet.revision || '—'} />
                <Row label="Scale" value={sheet.scale || '—'} />
                <Row label="Confidence" value={sheet.confidence || '—'} />
                <Row label="Status">
                  <Tag type={sheet.status === 'read_from_drawing' ? 'read' : sheet.status === 'ai_inferred' ? 'inferred' : 'na'}>
                    {sheet.status || '—'}
                  </Tag>
                </Row>
                {sheet.observations?.length > 0 && (
                  <Row label="Observations" value={sheet.observations.map(o =>
                    typeof o === 'string' ? o : (o.text || o.note || o.description || o.observation || JSON.stringify(o))
                  ).join(' · ')} />
                )}
              </div>
            ))}
            {drawing.overall_summary && (
              <Row label="Summary" value={drawing.overall_summary} />
            )}
          </ResultCard>

          {/* Gaps & RFIs */}
          <ResultCard icon="⚠️" title="Gaps & RFI Register" count={rfis.length} visible={!!results.rfis}>
            {rfis.map((r, i) => (
              <RfiItem key={i} id={r.rfi_id || `RFI-0${i+1}`} priority={r.priority}>
                <div style={{ marginBottom: 3 }}>{r.issue}</div>
                {r.suggested_action && <div style={{ color: '#6b7280', fontSize: 11 }}>→ {r.suggested_action}</div>}
              </RfiItem>
            ))}
          </ResultCard>

          {/* Proposal Draft */}
          <ResultCard icon="📝" title="Proposal Draft v1" count={proposalSections.length ? `${proposalSections.length} sections` : undefined} visible={!!results.proposal}>
            {proposalSections.map((s, i) => (
              <div key={i} className={styles.proposalSection}>
                <div className={styles.proposalTitle}>{s.number}. {s.title}</div>
                <div className={styles.proposalBody}>{s.content}</div>
              </div>
            ))}
          </ResultCard>

          {/* Export buttons */}
          {complete && (
            <div className={styles.exportRow}>
              <button className={`${styles.exportBtn} ${styles.btnProposal}`} onClick={downloadProposal}>
                📄 Download Proposal DOCX
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function DocItem({ icon, name, meta, badge, badgeCls }) {
  return (
    <div className={styles.docItem}>
      <div className={styles.docIcon}>{icon}</div>
      <div className={styles.docInfo}>
        <div className={styles.docName}>{name}</div>
        <div className={styles.docMeta}>{meta}</div>
      </div>
      <span className={`${styles.docBadge} ${badgeCls}`}>{badge}</span>
    </div>
  )
}
