import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import Header from '../components/Header'
import { Row, Tag, RfiItem } from '../components/ResultCard'
import styles from './PipelinePage.module.css'

const API = 'http://localhost:8001'

const STEPS = [
  { id: 'g0',            num: 1,  label: 'Intake',         title: 'Intake Acceptance',       badge: 'Auto',          badgeType: 'auto' },
  { id: 'g1',            num: 2,  label: 'Quality Gate',   title: 'Package Quality Gate',    badge: 'Auto',          badgeType: 'auto' },
  { id: 'ai_rfq',        num: 3,  label: 'RFQ Analysis',   title: 'RFQ Document Analysis',   badge: 'AI',            badgeType: 'ai' },
  { id: 'ai_draw',       num: 4,  label: 'Drawings',       title: 'Drawing Register',        badge: 'AI Vision',     badgeType: 'ai' },
  { id: 'cross',         num: 5,  label: 'Cross-Doc',      title: 'Cross-Document Analysis', badge: 'AI',            badgeType: 'ai' },
  { id: 'bid_viability', num: 6,  label: 'Bid Viability',  title: 'Bid Viability Assessment',badge: 'AI + Portfolio', badgeType: 'ai' },
  { id: 'g_bid',         num: 7,  label: 'Go / No-Go',     title: 'Bid Go / No-Go Decision', badge: 'Human Gate',    badgeType: 'gate', gate: true,
    approveLabel: '✓ Go — Pursue Bid', returnLabel: '✗ No-Go — Decline' },
  { id: 'g2',            num: 8,  label: 'Eng. Validation',title: 'Engineering Validation',  badge: 'Human Gate',    badgeType: 'gate', gate: true },
  { id: 'proposal',      num: 9,  label: 'Proposal',       title: 'Proposal Assembly',       badge: 'AI + Template', badgeType: 'ai' },
  { id: 'g3',            num: 10, label: 'Commercial',     title: 'Commercial Review',       badge: 'Human Gate',    badgeType: 'gate', gate: true },
  { id: 'g4',            num: 11, label: 'Final QA',       title: 'Final QA & Release',      badge: 'Human Gate',    badgeType: 'gate', gate: true },
  { id: 'export',        num: 12, label: 'Export',         title: 'Export & Archive',        badge: 'Final',         badgeType: 'auto' },
]

const STEP_DESC = {
  g0:            'Capture opportunity metadata and validate package manifest',
  g1:            'Check file readability, page counts and drawing revisions',
  ai_rfq:        'Extract project requirements, scope and submission rules via AI',
  ai_draw:       'Classify sheets and extract labels, notes and schedules via AI Vision',
  cross:         'Compare RFQ, drawings, specs and BOQ — flag conflicts and gaps',
  bid_viability: 'Compare against previous projects — assess technical match, RFI risk and profitability',
  g_bid:         'Manager reviews AI assessment and makes Go / No-Go bid decision',
  g2:            'Discipline lead validates drawing findings and assumptions',
  proposal:      'Map validated requirements to AB-approved proposal template',
  g3:            'Proposal manager reviews coverage, effort, fees and compliance',
  g4:            'Authorised AB approver checks mandatory sections and approvals',
  export:        'Generate approved DOCX proposal and full audit trail',
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
  const [statusLabel, setStatusLabel] = useState('Ready to Analyze')
  const [stepState, setStepState] = useState(initStepState)
  const [results, setResults] = useState({ rfq: null, drawing: null, rfis: null, bidViability: null, proposal: null })
  const [selectedStep, setSelectedStep] = useState('g0')
  const esRef = useRef(null)

  useEffect(() => {
    axios.get(`${API}/api/documents`).then(r => setDocs(r.data)).catch(() => {})
  }, [])

  function updateStep(id, patch) {
    setStepState(prev => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }
  function addMsg(id, msg) {
    setStepState(prev => ({ ...prev, [id]: { ...prev[id], messages: [...(prev[id]?.messages || []), msg] } }))
  }

  async function startAnalysis() {
    if (running) return
    setRunning(true)
    setComplete(false)
    setStepState(initStepState())
    setResults({ rfq: null, drawing: null, rfis: null, bidViability: null, proposal: null })
    setStatusLabel('Processing…')
    setSelectedStep('g0')

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
        setSelectedStep(step)
        setStatusLabel(`Awaiting ${step.toUpperCase()} approval`)
        return
      }
      if (d.declined) {
        updateStep(step, { status: 'returned' })
        addMsg(step, `✗ ${d.message}`)
        setRunning(false)
        setStatusLabel('Bid Declined')
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
      if (!d.done) setSelectedStep(step)

      if (d.done) {
        const idx = STEPS.findIndex(s => s.id === step)
        if (idx >= 0) updateStep(step, { connActive: true })
        const next = STEPS[idx + 1]
        if (next) setSelectedStep(next.id)
      }

      if (d.done && d.data) {
        if (step === 'ai_rfq')        setResults(r => ({ ...r, rfq: d.data }))
        if (step === 'ai_draw')       setResults(r => ({ ...r, drawing: d.data }))
        if (step === 'cross')         setResults(r => ({ ...r, rfis: d.data }))
        if (step === 'bid_viability') setResults(r => ({ ...r, bidViability: d.data }))
        if (step === 'proposal')      setResults(r => ({ ...r, proposal: d.data }))
      }
    })

    es.addEventListener('pipeline_done', e => {
      const d = JSON.parse(e.data)
      es.close()
      if (d.status === 'complete') {
        setComplete(true); setRunning(false)
        setStatusLabel('Complete — Ready for Export')
        setSelectedStep('export')
      } else if (d.status === 'declined') {
        setRunning(false); setStatusLabel('Bid Declined — Not Pursuing')
      } else if (d.status === 'returned') {
        setRunning(false); setStatusLabel(`Returned at ${(d.gate || '').toUpperCase()} for rework`)
      } else if (d.status === 'failed') {
        setRunning(false); setStatusLabel('Quality gate failed')
      } else {
        const msg = d.message || 'Unknown error'
        setRunning(false); setStatusLabel(`Error: ${msg.substring(0, 60)}${msg.length > 60 ? '…' : ''}`)
      }
    })

    es.addEventListener('ping', () => {})
    es.addEventListener('gate_ack', e => {
      const d = JSON.parse(e.data)
      if (d.action === 'approve') updateStep(d.gate, { status: 'done' })
    })
    es.addEventListener('error', () => { es.close(); setRunning(false) })
  }

  async function handleGate(gate, action, comment = '') {
    await axios.post(`${API}/api/gate/${runId}/${gate}`, { action, role: 'Reviewer', comment })
    if (action === 'approve') {
      updateStep(gate, { status: 'done' })
      addMsg(gate, '✓ Approved')
    }
  }

  function downloadProposal() {
    window.open(`${API}/api/export/${runId}/proposal`, '_blank')
  }

  const hasStarted = Object.values(results).some(Boolean) || running

  return (
    <div className={styles.pageShell}>
      <Header statusLabel={statusLabel} isActive={running} />

      {/* ── Top bar: docs + start button ── */}
      <div className={styles.topBar}>
       <div className={styles.topBarInner}>
        <div className={styles.docStrip}>
          <span className={styles.docStripLabel}>📂 Pre-Loaded Package</span>
          <div className={styles.docCards}>
            <div className={styles.docCard}>
              <span className={styles.docCardIcon}>📄</span>
              <div className={styles.docCardInfo}>
                <div className={styles.docCardName}>{docs?.rfq?.name || 'Loading…'}</div>
                <div className={styles.docCardMeta}>RFQ Document · {docs?.rfq ? Math.round(docs.rfq.size / 1024) + ' KB' : ''}</div>
              </div>
              <span className={`${styles.docBadge} ${styles.badgeRfq}`}>RFQ</span>
            </div>
            <div className={styles.docCard}>
              <span className={styles.docCardIcon}>📐</span>
              <div className={styles.docCardInfo}>
                <div className={styles.docCardName}>{docs?.drawing?.name || 'Loading…'}</div>
                <div className={styles.docCardMeta}>Engineering Drawing · {docs?.drawing ? Math.round(docs.drawing.size / 1024) + ' KB' : ''}</div>
              </div>
              <span className={`${styles.docBadge} ${styles.badgeDraw}`}>Drawing</span>
            </div>
          </div>
        </div>
        <button className={styles.startBtn} onClick={startAnalysis} disabled={running || complete}>
          {running
            ? <><span className={styles.spin}>⟳</span> Processing…</>
            : complete ? '✓ Analysis Complete'
            : <><span>▶</span> Start Analysis</>}
        </button>
       </div>
      </div>

      {/* ── Horizontal timeline ── */}
      <div className={styles.timelineWrapper}>
        <div className={styles.timeline}>
          {STEPS.map((step, idx) => {
            const s = stepState[step.id]
            const isSelected = selectedStep === step.id
            const circleCls =
              s.status === 'done'     ? styles.circleDone :
              s.status === 'running'  ? styles.circleRunning :
              s.status === 'waiting'  ? styles.circleWaiting :
              s.status === 'returned' ? styles.circleReturned :
              styles.circlePending

            return (
              <div key={step.id} className={styles.timelineItem}>
                {idx > 0 && (
                  <div className={`${styles.connector} ${stepState[STEPS[idx - 1].id]?.connActive ? styles.connectorActive : ''}`} />
                )}
                <div
                  className={`${styles.circleWrap} ${isSelected ? styles.circleWrapSelected : ''}`}
                  onClick={() => setSelectedStep(step.id)}
                  title={step.title}
                >
                  <div className={`${styles.circle} ${circleCls}`}>
                    {s.status === 'done' ? '✓' : s.status === 'returned' ? '✗' : s.status === 'waiting' ? '⏸' : step.num}
                  </div>
                  <div className={styles.stepLabel}>{step.label}</div>
                  <div className={`${styles.stepDot} ${styles['dot_' + step.badgeType]}`} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Content panel ── */}
      <div className={styles.contentPanel} style={{ flex: 1, overflowY: 'auto' }}>
        {!hasStarted ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>📋</div>
            <div className={styles.emptyTitle}>No Pipeline Activity Running</div>
            <div className={styles.emptyDesc}>
              Click the <strong>Start Analysis</strong> button in the top right to execute the AI
              pipeline and inspect each stage's extracted items.
            </div>
            <button className={styles.runNowBtn} onClick={startAnalysis} disabled={running}>
              Run Analysis Now →
            </button>
          </div>
        ) : (
          <StepContentPanel
            step={STEPS.find(s => s.id === selectedStep)}
            state={stepState[selectedStep] || { status: 'pending', messages: [] }}
            results={results}
            complete={complete}
            onGate={handleGate}
            onDownload={downloadProposal}
          />
        )}
      </div>
    </div>
  )
}

/* ── Step content panel ───────────────────────────────────────── */
function StepContentPanel({ step, state, results, complete, onGate, onDownload }) {
  if (!step) return null
  const { id } = step
  const { status, messages } = state

  const statusLabel = { done: 'Complete', running: 'Running', waiting: 'Awaiting Approval', returned: 'Returned', pending: 'Pending' }
  const statusColor = { done: '#16a34a', running: '#2563eb', waiting: '#d97706', returned: '#dc2626', pending: '#9ca3af' }

  return (
    <div className={styles.stepContent}>
      {/* Header */}
      <div className={styles.stepContentHeader}>
        <div className={styles.stepContentMeta}>
          <h2 className={styles.stepContentTitle}>{step.title}</h2>
          <span className={`${styles.badge} ${styles['badge_' + step.badgeType]}`}>{step.badge}</span>
          <span className={styles.statusChip} style={{ background: (statusColor[status] || '#9ca3af') + '18', color: statusColor[status] || '#9ca3af', border: `1px solid ${statusColor[status] || '#9ca3af'}40` }}>
            {status === 'running' && <span className={styles.spin}>⟳</span>} {statusLabel[status] || 'Pending'}
          </span>
        </div>
        <p className={styles.stepDesc}>{STEP_DESC[id]}</p>
      </div>

      {/* Activity log */}
      {messages.length > 0 && (
        <div className={styles.activityLog}>
          {messages.map((m, i) => (
            <div key={i} className={styles.logMsg}>
              <span className={styles.logDot} />
              {m}
            </div>
          ))}
        </div>
      )}

      {/* Step-specific result content */}
      <div className={styles.resultArea}>

        {/* RFQ Analysis */}
        {id === 'ai_rfq' && results.rfq && (
          <div className={styles.resultCard}>
            <div className={styles.resultCardHeader}><span>📋</span> RFQ Requirements <span className={styles.resultCount}>{Object.keys(results.rfq).length}</span></div>
            <div className={styles.resultCardBody}>
              {Object.entries(results.rfq).map(([k, v]) => (
                <Row key={k} label={k.replace(/_/g, ' ')} value={Array.isArray(v) ? v.join(', ') : v} />
              ))}
            </div>
          </div>
        )}

        {/* Drawing Register */}
        {id === 'ai_draw' && results.drawing && (
          <div className={styles.resultCard}>
            <div className={styles.resultCardHeader}><span>📐</span> Drawing Register <span className={styles.resultCount}>{results.drawing.sheets?.length}</span></div>
            <div className={styles.resultCardBody}>
              {(results.drawing.sheets || []).map((sheet, i) => (
                <div key={i} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: i < results.drawing.sheets.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                  <Row label="Sheet ID" value={sheet.sheet_id || '—'} />
                  <Row label="Title" value={sheet.title || '—'} />
                  <Row label="Discipline" value={sheet.discipline || '—'} />
                  <Row label="Revision" value={sheet.revision || '—'} />
                  <Row label="Scale" value={sheet.scale || '—'} />
                  <Row label="Confidence" value={sheet.confidence || '—'} />
                  <Row label="Status">
                    <Tag type={sheet.status === 'read_from_drawing' ? 'read' : sheet.status === 'ai_inferred' ? 'inferred' : 'na'}>{sheet.status || '—'}</Tag>
                  </Row>
                  {sheet.observations?.length > 0 && (
                    <Row label="Observations" value={sheet.observations.map(o =>
                      typeof o === 'string' ? o : (o.text || o.note || o.description || o.observation || JSON.stringify(o))
                    ).join(' · ')} />
                  )}
                </div>
              ))}
              {results.drawing.overall_summary && <Row label="Summary" value={results.drawing.overall_summary} />}
            </div>
          </div>
        )}

        {/* Cross-Document / RFI Register */}
        {id === 'cross' && results.rfis && (
          <div className={styles.resultCard}>
            <div className={styles.resultCardHeader}><span>⚠️</span> Gaps & RFI Register <span className={styles.resultCount}>{results.rfis.discrepancies?.length}</span></div>
            <div className={styles.resultCardBody}>
              {(results.rfis.discrepancies || []).map((r, i) => (
                <RfiItem key={i} id={r.rfi_id || `RFI-0${i + 1}`} priority={r.priority}>
                  <div style={{ marginBottom: 3 }}>{r.issue}</div>
                  {r.suggested_action && <div style={{ color: '#6b7280', fontSize: 11 }}>→ {r.suggested_action}</div>}
                </RfiItem>
              ))}
            </div>
          </div>
        )}

        {/* Bid Viability */}
        {(id === 'bid_viability' || id === 'g_bid') && results.bidViability && (
          <BidViabilityCard data={results.bidViability} />
        )}

        {/* Proposal Assembly */}
        {id === 'proposal' && results.proposal && (
          <div className={styles.resultCard}>
            <div className={styles.resultCardHeader}><span>📝</span> Proposal Draft v1 <span className={styles.resultCount}>{results.proposal.sections?.length} sections</span></div>
            <div className={styles.resultCardBody}>
              {(results.proposal.sections || []).map((s, i) => (
                <div key={i} className={styles.proposalSection}>
                  <div className={styles.proposalSectionTitle}>{s.number}. {s.title}</div>
                  <div className={styles.proposalSectionBody}>{s.content}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Export */}
        {id === 'export' && complete && (
          <div className={styles.exportArea}>
            <div className={styles.exportIcon}>📄</div>
            <div className={styles.exportTitle}>Proposal ready for download</div>
            <div className={styles.exportSub}>AI-assisted proposal draft approved through all gates</div>
            <button className={styles.downloadBtn} onClick={onDownload}>📄 Download Proposal DOCX</button>
          </div>
        )}

        {/* Gate panel — shown when step is waiting for human decision */}
        {step.gate && status === 'waiting' && (
          <GatePanel step={step} onGate={onGate} />
        )}

        {/* Pending state */}
        {status === 'pending' && messages.length === 0 && (
          <div className={styles.pendingState}>
            <span className={styles.pendingIcon}>⏱</span>
            Waiting for pipeline to reach this step…
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Gate panel ───────────────────────────────────────────────── */
function GatePanel({ step, onGate }) {
  const [returning, setReturning] = useState(false)
  const [comment, setComment] = useState('')

  const approveLabel = step.approveLabel || '✓ Approve'
  const returnLabel  = step.returnLabel  || '↩ Return for Rework'

  return (
    <div className={styles.gatePanel}>
      <div className={styles.gatePanelTitle}>⚡ Gate Decision Required</div>
      {returning ? (
        <div className={styles.gateForm}>
          <input
            className={styles.gateInput}
            placeholder={step.returnLabel ? 'Decline reason (optional)…' : 'Return reason (optional)…'}
            value={comment}
            onChange={e => setComment(e.target.value)}
            autoFocus
          />
          <div className={styles.gateBtnRow}>
            <button className={styles.btnReturn} onClick={() => { onGate(step.id, 'return', comment); setReturning(false) }}>
              {returnLabel}
            </button>
            <button className={styles.btnCancel} onClick={() => setReturning(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className={styles.gateBtnRow}>
          <button className={styles.btnApprove} onClick={() => onGate(step.id, 'approve')}>{approveLabel}</button>
          <button className={styles.btnReturn} onClick={() => setReturning(true)}>{returnLabel}</button>
        </div>
      )}
    </div>
  )
}

/* ── Bid Viability Card ───────────────────────────────────────── */
function BidViabilityCard({ data }) {
  const rec = data.overall_recommendation || 'pursue_with_conditions'
  const recColor = rec === 'pursue' ? '#16a34a' : rec === 'do_not_pursue' ? '#dc2626' : '#d97706'
  const recLabel = rec === 'pursue' ? '✓ PURSUE' : rec === 'do_not_pursue' ? '✗ DO NOT PURSUE' : '⚠ PURSUE WITH CONDITIONS'
  const rfiColor = data.rfi_risk_level === 'high' ? '#dc2626' : data.rfi_risk_level === 'medium' ? '#d97706' : '#16a34a'
  const score = data.technical_match_score || 0

  return (
    <div className={styles.resultCard}>
      <div className={styles.resultCardHeader}><span>⚖️</span> Bid Viability Assessment</div>
      <div className={styles.resultCardBody}>
        <div className={styles.bidRecBanner} style={{ background: recColor }}>
          <span className={styles.bidRecLabel}>{recLabel}</span>
        </div>
        {data.recommendation_summary && <p className={styles.bidRecSummary}>{data.recommendation_summary}</p>}

        <div className={styles.bidScoreRow}>
          <div className={styles.bidScoreItem}>
            <div className={styles.bidScoreLabel}>Technical Match</div>
            <div className={styles.bidScoreBar}>
              <div className={styles.bidScoreFill} style={{ width: `${score}%`, background: score >= 70 ? '#16a34a' : score >= 40 ? '#d97706' : '#dc2626' }} />
            </div>
            <div className={styles.bidScorePct}>{score}%</div>
          </div>
          <div className={styles.bidScoreItem}>
            <div className={styles.bidScoreLabel}>RFI Risk Level</div>
            <div className={styles.bidRfiBadge} style={{ background: rfiColor + '22', color: rfiColor, border: `1px solid ${rfiColor}` }}>
              {(data.rfi_risk_level || 'medium').toUpperCase()}
            </div>
            <div className={styles.bidRfiReason}>{data.rfi_risk_reason}</div>
          </div>
        </div>

        {data.top_similar_projects?.length > 0 && (
          <>
            <div className={styles.bidSectionTitle}>Similar Past Projects</div>
            {data.top_similar_projects.map((p, i) => (
              <div key={i} className={styles.bidProjectItem}>
                <div className={styles.bidProjectName}>{p.project_name} <span style={{ color: '#9ca3af' }}>({p.year})</span></div>
                <div style={{ display: 'flex', gap: 6, marginTop: 3, flexWrap: 'wrap' }}>
                  <span className={styles.bidProjectTag} style={{
                    background: p.outcome === 'won' ? '#dcfce7' : p.outcome === 'declined' ? '#fef3c7' : '#fee2e2',
                    color: p.outcome === 'won' ? '#16a34a' : p.outcome === 'declined' ? '#d97706' : '#dc2626'
                  }}>{p.outcome?.toUpperCase()}</span>
                  {p.profit_margin_pct && p.profit_margin_pct !== 'N/A' && (
                    <span className={styles.bidProjectTag} style={{ background: '#eff4ff', color: '#2563eb' }}>Margin: {p.profit_margin_pct}%</span>
                  )}
                </div>
                {p.similarity_reason && <div className={styles.bidProjectReason}>{p.similarity_reason}</div>}
              </div>
            ))}
          </>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
          {data.key_risks?.length > 0 && (
            <div>
              <div className={styles.bidSectionTitle} style={{ color: '#dc2626' }}>Key Risks</div>
              <ul className={styles.bidList}>{data.key_risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          )}
          {data.key_strengths?.length > 0 && (
            <div>
              <div className={styles.bidSectionTitle} style={{ color: '#16a34a' }}>Key Strengths</div>
              <ul className={styles.bidList}>{data.key_strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
