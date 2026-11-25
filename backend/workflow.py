"""Workflow engine: statuses, allowed moves, role checks, version-bound approvals and the append-only audit trail.

Pattern adapted from MIT-licensed maideps/ai-invoice-intake (status transition table, version-checked
decisions, append-only audit events) - see reference_code/invoice_intake_approvals.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models_v2 import Approval, AuditEvent, Opportunity, StepState

STEPS = ["intake", "capability", "analysis", "review", "proposal", "approval", "release"]
STEP_TITLES = {
    "intake": "Intake & package",
    "capability": "Historical capability check",
    "analysis": "Technical analysis",
    "review": "Engineering review",
    "proposal": "Proposal drafting",
    "approval": "Commercial & final approval",
    "release": "Release & archive",
}

ROLES = ["coordinator", "management", "discipline_lead", "proposal_manager", "commercial_lead", "approver", "admin"]

# Which stable status each step is "current" in (for the UI)
STATUS_STEP = {
    "draft": "intake", "capability_processing": "capability", "capability_review": "capability",
    "closed_no_go": "capability", "analysis_processing": "analysis", "engineering_validation": "review",
    "proposal_processing": "proposal", "proposal_draft": "proposal", "commercial_review": "approval",
    "final_approval": "approval", "approved_for_export": "release", "archived": "release",
}

# action -> allowed from-statuses, resulting status (None = stays), allowed roles (None = system only)
ACTIONS: dict[str, dict] = {
    "confirm_intake":       {"from": ["draft"], "to": "capability_processing", "roles": ["coordinator"]},
    "capability_done":      {"from": ["capability_processing"], "to": "capability_review", "roles": None},
    "capability_failed":    {"from": ["capability_processing"], "to": "draft", "roles": None},
    "rerun_capability":     {"from": ["capability_review"], "to": "capability_processing", "roles": ["coordinator", "management"]},
    "cap_go":               {"from": ["capability_review"], "to": "analysis_processing", "roles": ["management"]},
    "cap_conditional_go":   {"from": ["capability_review"], "to": "analysis_processing", "roles": ["management"]},
    "cap_no_go":            {"from": ["capability_review"], "to": "closed_no_go", "roles": ["management"]},
    "cap_request_evidence": {"from": ["capability_review"], "to": None, "roles": ["management"]},
    "analysis_done":        {"from": ["analysis_processing"], "to": "engineering_validation", "roles": None},
    "analysis_failed":      {"from": ["analysis_processing"], "to": "capability_review", "roles": None},
    "rerun_analysis":       {"from": ["engineering_validation"], "to": "analysis_processing", "roles": ["discipline_lead", "coordinator"]},
    "g2_approve":           {"from": ["engineering_validation"], "to": "proposal_processing", "roles": ["discipline_lead"]},
    "g2_return":            {"from": ["engineering_validation"], "to": None, "roles": ["discipline_lead"]},
    "proposal_done":        {"from": ["proposal_processing"], "to": "proposal_draft", "roles": None},
    "proposal_failed":      {"from": ["proposal_processing"], "to": "engineering_validation", "roles": None},
    "rerun_proposal":       {"from": ["proposal_draft"], "to": "proposal_processing", "roles": ["proposal_manager"]},
    "edit_proposal":        {"from": ["proposal_draft", "commercial_review", "final_approval"], "to": "proposal_draft", "roles": ["proposal_manager", "commercial_lead"]},
    "g_prop_approve":       {"from": ["proposal_draft"], "to": "commercial_review", "roles": ["proposal_manager"]},
    "g_prop_return":        {"from": ["proposal_draft"], "to": None, "roles": ["proposal_manager"]},
    "g3_approve":           {"from": ["commercial_review"], "to": "final_approval", "roles": ["commercial_lead"]},
    "g3_return":            {"from": ["commercial_review"], "to": "proposal_draft", "roles": ["commercial_lead"]},
    "g4_approve":           {"from": ["final_approval"], "to": "approved_for_export", "roles": ["approver"]},
    "g4_return":            {"from": ["final_approval"], "to": "commercial_review", "roles": ["approver"]},
    "archive":              {"from": ["approved_for_export"], "to": "archived", "roles": ["coordinator"]},
}

# Separation of duties: the actor of a gate may not also have made these earlier (still valid) approvals.
SEPARATION = {"g3": ["g_prop"], "g4": ["g2", "g_prop", "g3"]}


class WorkflowError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Actor:
    name: str = "system"
    role: str = "system"

    @property
    def is_system(self) -> bool:
        return self.role == "system"


SYSTEM = Actor("system", "system")


def audit(db: Session, opp_id: int, actor: Actor, action: str, *, step: str = "", from_status: str = "",
          to_status: str = "", reason: str = "", details: dict | None = None, proposal_version: int | None = None):
    seq = (db.query(func.max(AuditEvent.seq)).filter(AuditEvent.opp_id == opp_id).scalar() or 0) + 1
    db.add(AuditEvent(
        opp_id=opp_id, seq=seq, actor_name=actor.name, actor_role=actor.role, action=action, step=step,
        from_status=from_status, to_status=to_status, reason=reason or "", details=details or {},
        proposal_version=proposal_version,
    ))


def apply_action(db: Session, opp: Opportunity, action: str, actor: Actor, *, version: int | None = None,
                 reason: str = "", details: dict | None = None, proposal_version: int | None = None) -> Opportunity:
    """Validate (status, role, version) then move the opportunity and write the audit event."""
    spec = ACTIONS[action]
    if version is not None and version != opp.version:
        raise WorkflowError(409, f"This opportunity changed since you loaded it (now version {opp.version}, you had {version}). Reload and retry.")
    if opp.status not in spec["from"]:
        raise WorkflowError(409, f"'{action}' is not allowed while the opportunity is in status '{opp.status}'.")
    if spec["roles"] is None:
        if not actor.is_system:
            raise WorkflowError(403, f"'{action}' is a system action.")
    elif actor.role not in spec["roles"]:
        raise WorkflowError(403, f"Role '{actor.role}' cannot perform '{action}' (needs: {', '.join(spec['roles'])}).")
    if not actor.is_system and not actor.name.strip():
        raise WorkflowError(400, "Enter your name so the decision can be recorded.")

    old = opp.status
    if spec["to"]:
        opp.status = spec["to"]
    opp.version = (opp.version or 1) + 1
    opp.updated_at = datetime.utcnow()
    audit(db, opp.id, actor, action, step=STATUS_STEP.get(opp.status, ""), from_status=old, to_status=opp.status,
          reason=reason, details=details, proposal_version=proposal_version)
    return opp


def touch(db: Session, opp: Opportunity, actor: Actor, action: str, *, step: str = "", reason: str = "",
          details: dict | None = None, proposal_version: int | None = None):
    """Audited change that does not move the status (edits, uploads, review decisions)."""
    opp.version = (opp.version or 1) + 1
    opp.updated_at = datetime.utcnow()
    audit(db, opp.id, actor, action, step=step, from_status=opp.status, to_status=opp.status, reason=reason,
          details=details, proposal_version=proposal_version)


def check_separation(db: Session, opp_id: int, gate: str, actor: Actor):
    for other in SEPARATION.get(gate, []):
        prior = db.query(Approval).filter(Approval.opp_id == opp_id, Approval.gate == other,
                                          Approval.valid.is_(True), Approval.decision == "approved").all()
        if any(p.actor_name.strip().lower() == actor.name.strip().lower() for p in prior):
            raise WorkflowError(403, f"Separation of duties: '{actor.name}' already approved at gate '{other}' and cannot also approve '{gate}'.")


def record_approval(db: Session, opp: Opportunity, gate: str, decision: str, actor: Actor, comment: str = "",
                    proposal_version: int | None = None):
    db.add(Approval(opp_id=opp.id, gate=gate, decision=decision, actor_name=actor.name, actor_role=actor.role,
                    comment=comment or "", proposal_version=proposal_version))


def invalidate_approvals(db: Session, opp_id: int, gates: list[str] | None = None) -> int:
    q = db.query(Approval).filter(Approval.opp_id == opp_id, Approval.valid.is_(True), Approval.decision == "approved")
    if gates:
        q = q.filter(Approval.gate.in_(gates))
    rows = q.all()
    for r in rows:
        r.valid = False
    return len(rows)


# ── Step states ─────────────────────────────────────────────────────────────

def get_step(db: Session, opp_id: int, step: str) -> StepState:
    s = db.query(StepState).filter(StepState.opp_id == opp_id, StepState.step == step).first()
    if not s:
        s = StepState(opp_id=opp_id, step=step, status="not_started", messages=[])
        db.add(s)
        db.flush()
    return s


def set_step(db: Session, opp_id: int, step: str, status: str | None = None, **fields) -> StepState:
    s = get_step(db, opp_id, step)
    if status:
        s.status = status
    for k, v in fields.items():
        setattr(s, k, v)
    s.updated_at = datetime.utcnow()
    return s


def log(db: Session, opp_id: int, step: str, msg: str, reset: bool = False):
    s = get_step(db, opp_id, step)
    s.messages = ([] if reset else list(s.messages or [])) + [{"ts": datetime.utcnow().isoformat(timespec="seconds"), "msg": msg}]
    flag_modified(s, "messages")
    s.updated_at = datetime.utcnow()


def init_steps(db: Session, opp: Opportunity):
    for st in STEPS:
        get_step(db, opp.id, st)
    first = get_step(db, opp.id, "intake")
    if first.status == "not_started":
        first.status = "in_progress"
        first.owner = opp.owner


def mark_needs_refresh(db: Session, opp_id: int, after_step: str) -> list[str]:
    """A revised input arrived: downstream outputs may be stale. Their approvals no longer hold."""
    affected = []
    for st in STEPS[STEPS.index(after_step) + 1:]:
        s = get_step(db, opp_id, st)
        if s.status not in ("not_started",):
            s.status = "needs_refresh"
            affected.append(st)
    if affected:
        invalidate_approvals(db, opp_id)
    return affected
