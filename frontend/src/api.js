import axios from 'axios'

export const API = import.meta.env.VITE_API_URL || 'http://localhost:8001'

export const ROLES = [
  ['coordinator', 'Proposal coordinator'],
  ['management', 'Management (capability / Go-No-Go)'],
  ['discipline_lead', 'Discipline lead (engineering)'],
  ['proposal_manager', 'Proposal manager'],
  ['commercial_lead', 'Commercial lead'],
  ['approver', 'Final approver'],
  ['admin', 'System admin'],
]

export function loadActor() {
  try { return JSON.parse(localStorage.getItem('actor')) || { name: '', role: 'coordinator' } }
  catch { return { name: '', role: 'coordinator' } }
}
export function saveActor(a) { try { localStorage.setItem('actor', JSON.stringify(a)) } catch { /* ignore */ } }

export function client(actor) {
  return axios.create({ baseURL: API, headers: { 'X-Actor-Name': actor.name || '', 'X-Actor-Role': actor.role } })
}

export function errText(e) {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map(x => x.msg).join('; ')
  return e?.message || 'Request failed'
}

export const STATUS_LABEL = {
  draft: 'Draft / intake', capability_processing: 'Processing - capability check', capability_review: 'Capability review',
  closed_no_go: 'Closed - No-Go', analysis_processing: 'Processing - technical analysis',
  engineering_validation: 'Engineering validation', proposal_processing: 'Processing - proposal draft',
  proposal_draft: 'Proposal draft', commercial_review: 'Commercial review', final_approval: 'Final approval',
  approved_for_export: 'Approved for export', archived: 'Archived',
}
