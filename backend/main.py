"""RFQ & drawing analysis POC - 7-step opportunity workflow API (FastAPI).

Steps: 1 Intake -> 2 Capability check -> 3 Technical analysis -> 4 Engineering review -> 5 Proposal ->
       6 Commercial & final approval -> 7 Release & archive.
All state lives in the database; AI steps run as background tasks and the UI polls GET /api/opportunities/{id}.
"""
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import analysis
import export
import ingest
import models_v2  # noqa: F401  (registers tables on Base)
import proposal as prop
from db import SessionLocal, get_db, init_db
from models import PastProject
from models_v2 import (RFI, Approval, AuditEvent, CapabilityAssessment, Finding, FilePage, OppFile, Opportunity,
                       ProposalVersion, StepState, Submission)
from workflow import (ACTIONS, ROLES, STATUS_STEP, STEP_TITLES, STEPS, SYSTEM, Actor, WorkflowError, apply_action,
                      audit, check_separation, get_step, init_steps, invalidate_approvals, log, mark_needs_refresh,
                      record_approval, set_step, touch)

app = FastAPI(title="RFQ Analysis POC")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"],
                   allow_methods=["*"], allow_headers=["*"])

running: set[tuple[int, str]] = set()
MAIN_LOOP: asyncio.AbstractEventLoop | None = None   # endpoints are sync (thread pool); background steps run on this loop


@app.on_event("startup")
async def on_startup():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    init_db()
    db = SessionLocal()
    try:   # background work cannot survive a restart: put interrupted opportunities back into a re-runnable state
        for status, action, step in (("capability_processing", "capability_failed", "capability"),
                                     ("analysis_processing", "analysis_failed", "analysis"),
                                     ("proposal_processing", "proposal_failed", "proposal")):
            for opp in db.query(Opportunity).filter(Opportunity.status == status).all():
                apply_action(db, opp, action, SYSTEM, reason="Interrupted by server restart")
                log(db, opp.id, step, "⚠ Interrupted by a server restart - run this step again.")
                set_step(db, opp.id, step, "returned")
        db.commit()
    finally:
        db.close()


# ── helpers ─────────────────────────────────────────────────────────────────

def actor_of(x_actor_name: str = Header(default=""), x_actor_role: str = Header(default="")) -> Actor:
    if x_actor_role not in ROLES:
        raise HTTPException(400, f"Choose a role (one of: {', '.join(ROLES)}).")
    return Actor(x_actor_name.strip(), x_actor_role)


def get_opp(db: Session, opp_id: int) -> Opportunity:
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    return opp


def wf(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except WorkflowError as e:
        raise HTTPException(e.code, e.message)


def code(opp: Opportunity) -> str:
    return f"OPP-{opp.created_at.year}-{opp.id:03d}"


def recompute_package(db: Session, opp: Opportunity) -> dict:
    pc = ingest.package_check(db.query(OppFile).filter(OppFile.opp_id == opp.id).order_by(OppFile.id).all())
    opp.package_status = pc["status"]
    return pc


# Step-state side effects of each workflow action: (step, status[, decision text])
EFFECTS = {
    "confirm_intake": [("intake", "approved", "Package confirmed"), ("capability", "in_progress")],
    "capability_done": [("capability", "awaiting_review")],
    "capability_failed": [("capability", "returned"), ("intake", "in_progress")],
    "cap_go": [("capability", "approved", "Go"), ("analysis", "in_progress")],
    "cap_conditional_go": [("capability", "approved", "Conditional Go"), ("analysis", "in_progress")],
    "cap_no_go": [("capability", "archived", "No-Go")],
    "cap_request_evidence": [("capability", "returned", "More evidence requested")],
    "analysis_done": [("analysis", "awaiting_review"), ("review", "awaiting_review")],
    "analysis_failed": [("analysis", "returned"), ("capability", "awaiting_review")],
    "rerun_analysis": [("analysis", "in_progress"), ("review", "not_started"), ("proposal", "needs_refresh"), ("approval", "needs_refresh")],
    "rerun_capability": [("capability", "in_progress")],
    "g2_approve": [("review", "approved", "Engineering validated"), ("analysis", "approved"), ("proposal", "in_progress")],
    "g2_return": [("review", "returned", "Returned for rework")],
    "proposal_done": [("proposal", "awaiting_review")],
    "proposal_failed": [("proposal", "returned"), ("review", "awaiting_review")],
    "rerun_proposal": [("proposal", "in_progress"), ("approval", "needs_refresh")],
    "g_prop_approve": [("proposal", "approved", "Content approved"), ("approval", "awaiting_review")],
    "g_prop_return": [("proposal", "returned", "Returned for rework")],
    "g3_approve": [("approval", "awaiting_review", "Commercial approved - awaiting final release approval")],
    "g3_return": [("approval", "returned", "Commercial review returned"), ("proposal", "in_progress")],
    "g4_approve": [("approval", "approved", "Final release approved"), ("release", "in_progress")],
    "g4_return": [("approval", "returned", "Final approval returned")],
    "archive": [("release", "archived", "Archived")],
    "edit_proposal": [("proposal", "in_progress"), ("approval", "needs_refresh")],
}


def advance(db: Session, opp: Opportunity, action: str, actor: Actor, *, version=None, reason="", details=None, pv=None):
    wf(apply_action, db, opp, action, actor, version=version, reason=reason, details=details, proposal_version=pv)
    for eff in EFFECTS.get(action, []):
        kw = {}
        if len(eff) > 2:
            kw = {"decision": eff[2], "decided_by": actor.name, "decided_at": datetime.utcnow()}
        set_step(db, opp.id, eff[0], eff[1], **kw)


# ── serialisers ─────────────────────────────────────────────────────────────

def f_dict(f: Finding) -> dict:
    return {"id": f.id, "kind": f.kind, "key": f.key, "value": f.value, "effective_value": prop.effective_value(f),
            "source_file": f.source_file, "source_page": f.source_page, "quote": f.quote, "quote_verified": f.quote_verified,
            "method": f.method, "confidence": f.confidence, "status": f.status, "review": f.review,
            "corrected_value": f.corrected_value, "critical": f.critical, "reviewer": f.reviewer,
            "review_comment": f.review_comment, "data": f.data or {}}


def file_dict(f: OppFile) -> dict:
    return {"id": f.id, "filename": f.filename, "kind": f.kind, "size_bytes": f.size_bytes, "page_count": f.page_count,
            "locator_kind": f.locator_kind, "extract_status": f.extract_status, "revision_no": f.revision_no,
            "superseded": f.superseded, "duplicate_of": f.duplicate_of, "issues": ingest.file_issues(f),
            "uploaded_by": f.uploaded_by, "uploaded_at": f.uploaded_at.isoformat()}


def opp_state(db: Session, opp: Opportunity) -> dict:
    steps = {s.step: s for s in db.query(StepState).filter(StepState.opp_id == opp.id).all()}
    files = db.query(OppFile).filter(OppFile.opp_id == opp.id).order_by(OppFile.id).all()
    cap = db.query(CapabilityAssessment).filter(CapabilityAssessment.opp_id == opp.id).order_by(CapabilityAssessment.run_no.desc()).first()
    pv = prop.latest_version(db, opp.id)
    versions = db.query(ProposalVersion).filter(ProposalVersion.opp_id == opp.id).order_by(ProposalVersion.version_no).all()
    sub = db.query(Submission).filter(Submission.opp_id == opp.id).first()
    aud = db.query(AuditEvent).filter(AuditEvent.opp_id == opp.id).order_by(AuditEvent.seq.desc()).limit(300).all()
    appr = db.query(Approval).filter(Approval.opp_id == opp.id).order_by(Approval.id).all()
    allowed = [{"action": a, "roles": s["roles"]} for a, s in ACTIONS.items() if s["roles"] and opp.status in s["from"]]
    show_qa = opp.status in ("commercial_review", "final_approval", "approved_for_export", "archived")
    return {
        "opportunity": {"id": opp.id, "code": code(opp), "client": opp.client, "project_name": opp.project_name,
                        "rfq_reference": opp.rfq_reference, "location": opp.location, "procurement_type": opp.procurement_type,
                        "submission_deadline": opp.submission_deadline, "clarification_deadline": opp.clarification_deadline,
                        "owner": opp.owner, "status": opp.status, "package_status": opp.package_status, "version": opp.version,
                        "close_reason": opp.close_reason, "updated_at": opp.updated_at.isoformat(),
                        "current_step": STATUS_STEP.get(opp.status, "intake")},
        "allowed": allowed,
        "busy": any(k[0] == opp.id for k in running),
        "steps": [{"step": s, "title": STEP_TITLES[s], "status": steps[s].status if s in steps else "not_started",
                   "messages": (steps[s].messages or [])[-40:] if s in steps else [], "inputs": steps[s].inputs if s in steps else "",
                   "ai_summary": steps[s].ai_summary if s in steps else "", "outputs": steps[s].outputs if s in steps else "",
                   "owner": steps[s].owner if s in steps else "", "decision": steps[s].decision if s in steps else "",
                   "decided_by": steps[s].decided_by if s in steps else "",
                   "decided_at": steps[s].decided_at.isoformat() if s in steps and steps[s].decided_at else None,
                   "ai_at": steps[s].ai_at.isoformat() if s in steps and steps[s].ai_at else None} for s in STEPS],
        "files": [file_dict(f) for f in files],
        "package": ingest.package_check(files),
        "capability": None if not cap else {
            "run_no": cap.run_no, "overview": cap.overview, "coverage": cap.coverage, "matched_projects": cap.matched_projects,
            "gaps": cap.gaps, "risks": cap.risks, "narrative": cap.narrative, "recommendation": cap.recommendation,
            "confidence": cap.confidence, "evidence_count": cap.evidence_count, "decision": cap.decision,
            "decision_conditions": cap.decision_conditions, "decision_by": cap.decision_by},
        "findings": [f_dict(f) for f in prop.current_findings(db, opp.id)],
        "rfis": [{"id": r.id, "rfi_no": r.rfi_no, "issue": r.issue, "evidence": r.evidence, "priority": r.priority,
                  "suggested_action": r.suggested_action, "impact": r.impact, "origin": r.origin, "owner": r.owner,
                  "due_date": r.due_date, "status": r.status, "response": r.response} for r in prop.current_rfis(db, opp.id)],
        "g2_blockers": prop.g2_blockers(db, opp.id) if opp.status == "engineering_validation" else [],
        "proposal": None if not pv else {"version_no": pv.version_no, "sections": pv.sections, "compliance": pv.compliance,
                                         "commercial": pv.commercial, "totals": prop.commercial_total(pv.commercial),
                                         "status": pv.status, "note": pv.note, "created_by": pv.created_by},
        "proposal_versions": [{"version_no": v.version_no, "status": v.status, "note": v.note, "created_by": v.created_by,
                               "created_at": v.created_at.isoformat()} for v in versions],
        "qa": prop.qa_checklist(db, opp) if show_qa else [],
        "approvals": [{"gate": a.gate, "decision": a.decision, "actor_name": a.actor_name, "actor_role": a.actor_role,
                       "proposal_version": a.proposal_version, "valid": a.valid, "comment": a.comment,
                       "created_at": a.created_at.isoformat()} for a in appr],
        "submission": None if not sub else {"status": sub.status, "submitted_at": sub.submitted_at, "channel": sub.channel,
                                            "receipt_ref": sub.receipt_ref, "outcome": sub.outcome, "notes": sub.notes},
        "audit": [{"seq": e.seq, "ts": e.ts.isoformat(), "actor_name": e.actor_name, "actor_role": e.actor_role, "action": e.action,
                   "step": e.step, "from_status": e.from_status, "to_status": e.to_status, "reason": e.reason,
                   "proposal_version": e.proposal_version} for e in aud],
    }


# ── background steps ────────────────────────────────────────────────────────

async def _bg(opp_id: int, step: str, runner, done: str, failed: str):
    key = (opp_id, step)
    if key in running:
        return
    running.add(key)
    db = SessionLocal()
    try:
        opp = db.get(Opportunity, opp_id)
        set_step(db, opp_id, step, "in_progress", ai_at=None)
        log(db, opp_id, step, "Started…", reset=True)
        db.commit()
        try:
            summary = await runner(db, opp)
            set_step(db, opp_id, step, ai_summary=summary[0], outputs=summary[1], ai_at=datetime.utcnow(), inputs=summary[2])
            advance(db, opp, done, SYSTEM)
        except Exception as e:
            db.rollback()
            opp = db.get(Opportunity, opp_id)
            log(db, opp_id, step, f"✗ Failed: {e}")
            advance(db, opp, failed, SYSTEM, reason=str(e)[:300])
        db.commit()
    finally:
        db.close()
        running.discard(key)


async def _capability_runner(db, opp):
    ca = await analysis.run_capability(db, opp)
    cov = ", ".join(f"{c['discipline']}: {c['level']}" for c in ca.coverage) or "no disciplines identified"
    log(db, opp.id, "capability", f"Assessment ready - recommendation {ca.recommendation} ({cov}). Awaiting management decision.")
    return (f"Recommendation {ca.recommendation} (confidence {ca.confidence}); {ca.evidence_count} historical records searched.",
            f"Capability report run #{ca.run_no}", "Opportunity RFQ overview + historical project library")


async def _analysis_runner(db, opp):
    s = await analysis.run_analysis(db, opp)
    return (f"{s['rfq_items']} RFQ items, {s['sheets']} drawing sheets, {s['observations']} observations, {s['rfis']} draft RFIs, {s['risks']} risks.",
            f"Technical analysis run #{s['run_no']}", "All readable package files (RFQ, drawings, spec, BOQ)")


async def _proposal_runner(db, opp):
    pv = await prop.run_proposal(db, opp)
    return (f"Proposal draft v{pv.version_no} from verified findings only.", f"Proposal v{pv.version_no} + compliance matrix",
            "Verified/corrected findings, RFIs, capability conditions, template")


RUNNERS = {"capability": (_capability_runner, "capability_done", "capability_failed"),
           "analysis": (_analysis_runner, "analysis_done", "analysis_failed"),
           "proposal": (_proposal_runner, "proposal_done", "proposal_failed")}


def start_bg(opp_id: int, step: str):
    r = RUNNERS[step]
    asyncio.run_coroutine_threadsafe(_bg(opp_id, step, *r), MAIN_LOOP)


# ── opportunities & intake ──────────────────────────────────────────────────

class OppIn(BaseModel):
    client: str = ""
    project_name: str = ""
    rfq_reference: str = ""
    location: str = ""
    procurement_type: str = ""
    submission_deadline: str = ""
    clarification_deadline: str = ""
    owner: str = ""


@app.get("/api/roles")
def roles():
    return {"roles": ROLES}


@app.get("/api/opportunities")
def list_opps(db: Session = Depends(get_db)):
    rows = db.query(Opportunity).order_by(Opportunity.updated_at.desc()).all()
    return [{"id": o.id, "code": code(o), "project_name": o.project_name, "client": o.client, "status": o.status,
             "package_status": o.package_status, "updated_at": o.updated_at.isoformat()} for o in rows]


@app.post("/api/opportunities")
def create_opp(body: OppIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    if not actor.name:
        raise HTTPException(400, "Enter your name first.")
    data = body.model_dump()
    data["owner"] = body.owner or actor.name
    opp = Opportunity(**data)
    db.add(opp)
    db.flush()
    init_steps(db, opp)
    audit(db, opp.id, actor, "opportunity_created", step="intake", to_status="draft", details=body.model_dump())
    db.commit()
    return {"id": opp.id}


@app.get("/api/opportunities/{opp_id}")
def get_state(opp_id: int, db: Session = Depends(get_db)):
    return opp_state(db, get_opp(db, opp_id))


@app.patch("/api/opportunities/{opp_id}")
def patch_opp(opp_id: int, body: OppIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    if actor.role not in ("coordinator", "admin"):
        raise HTTPException(403, "Only the proposal coordinator edits opportunity details.")
    if opp.status in ("approved_for_export", "archived", "closed_no_go"):
        raise HTTPException(409, "This opportunity is locked.")
    changes = {k: v for k, v in body.model_dump().items() if v != getattr(opp, k)}
    for k, v in changes.items():
        setattr(opp, k, v)
    if changes:
        touch(db, opp, actor, "details_edited", step="intake", details=changes)
    db.commit()
    return {"ok": True}


@app.post("/api/opportunities/{opp_id}/files")
async def upload_files(opp_id: int, files: list[UploadFile] = File(...), actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    if opp.status in ("approved_for_export", "archived", "closed_no_go"):
        raise HTTPException(409, "This opportunity is locked - start a new opportunity for new files.")
    if (opp.status.endswith("_processing")):
        raise HTTPException(409, "A step is running; wait for it to finish before uploading.")
    results = []
    for up in files:
        try:
            f = await asyncio.to_thread(ingest.store_file, db, opp_id, up.filename or "file", await up.read(), actor.name, up.content_type or "")
            results.append({"filename": f.filename, "ok": True, "issues": ingest.file_issues(f)})
        except ValueError as e:
            results.append({"filename": up.filename, "ok": False, "error": str(e)})
    pc = recompute_package(db, opp)
    ok_names = [r["filename"] for r in results if r["ok"]]
    if ok_names:
        affected = []
        if opp.status != "draft":     # revised input after analysis has started: old outputs may be stale
            affected = mark_needs_refresh(db, opp.id, "intake")
        touch(db, opp, actor, "files_uploaded", step="intake", details={"files": ok_names, "package_status": pc["status"], "needs_refresh": affected})
    db.commit()
    return {"results": results, "package": pc}


class FileKind(BaseModel):
    kind: str


@app.patch("/api/files/{file_id}")
def set_kind(file_id: int, body: FileKind, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    f = db.get(OppFile, file_id)
    if not f:
        raise HTTPException(404, "File not found")
    if body.kind not in ingest.KINDS:
        raise HTTPException(400, f"kind must be one of {ingest.KINDS}")
    opp = get_opp(db, f.opp_id)
    if opp.status != "draft":
        raise HTTPException(409, "Document types can only be changed during intake.")
    f.kind = body.kind
    recompute_package(db, opp)
    touch(db, opp, actor, "file_type_changed", step="intake", details={"file": f.filename, "kind": body.kind})
    db.commit()
    return {"ok": True}


class VersionIn(BaseModel):
    version: Optional[int] = None


@app.post("/api/opportunities/{opp_id}/confirm-intake")
def confirm_intake(opp_id: int, body: VersionIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    pc = recompute_package(db, opp)
    if pc["status"] == "Incomplete":
        raise HTTPException(409, "Package incomplete: " + "; ".join(pc["missing"]))
    advance(db, opp, "confirm_intake", actor, version=body.version, details={"package": pc["status"], "warnings": pc["warnings"]})
    set_step(db, opp.id, "intake", inputs=f"{pc['counts']['files']} files, {pc['counts']['pages']} pages", outputs=f"Package status: {pc['status']}")
    db.commit()
    start_bg(opp.id, "capability")
    return {"ok": True}


@app.post("/api/opportunities/{opp_id}/run/{step}")
def rerun(opp_id: int, step: str, body: VersionIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    action = {"capability": "rerun_capability", "analysis": "rerun_analysis", "proposal": "rerun_proposal"}.get(step)
    if not action:
        raise HTTPException(400, "step must be capability, analysis or proposal")
    gates = {"analysis": ["g2", "g_prop", "g3", "g4"], "proposal": ["g_prop", "g3", "g4"], "capability": []}[step]
    advance(db, opp, action, actor, version=body.version)
    invalidate_approvals(db, opp.id, gates or None) if gates else None
    db.commit()
    start_bg(opp.id, step)
    return {"ok": True}


# ── step 2: capability decision ─────────────────────────────────────────────

class CapDecision(BaseModel):
    version: Optional[int] = None
    decision: str            # go / conditional_go / no_go / request_evidence
    comment: str = ""
    conditions: str = ""


@app.post("/api/opportunities/{opp_id}/capability-decision")
def capability_decision(opp_id: int, body: CapDecision, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    action = {"go": "cap_go", "conditional_go": "cap_conditional_go", "no_go": "cap_no_go", "request_evidence": "cap_request_evidence"}.get(body.decision)
    if not action:
        raise HTTPException(400, "decision must be go, conditional_go, no_go or request_evidence")
    if body.decision == "conditional_go" and not body.conditions.strip():
        raise HTTPException(400, "Conditional Go needs the named conditions/actions.")
    if body.decision in ("no_go", "request_evidence") and not body.comment.strip():
        raise HTTPException(400, "Give a reason for this decision.")
    cap = db.query(CapabilityAssessment).filter(CapabilityAssessment.opp_id == opp_id).order_by(CapabilityAssessment.run_no.desc()).first()
    if not cap:
        raise HTTPException(409, "No capability assessment exists yet.")
    if body.decision == "go" and cap.recommendation == "D":
        pass   # allowed: management may decide with insufficient evidence, but the audit shows the system said D
    advance(db, opp, action, actor, version=body.version, reason=body.comment,
            details={"recommendation": cap.recommendation, "conditions": body.conditions})
    cap.decision, cap.decision_by, cap.decided_at = body.decision, actor.name, datetime.utcnow()
    cap.decision_conditions = body.conditions if body.decision == "conditional_go" else ("" if body.decision != "request_evidence" else cap.decision_conditions)
    record_approval(db, opp, "g_cap", body.decision, actor, body.comment)
    if body.decision == "no_go":
        opp.close_reason = body.comment
    db.commit()
    if body.decision in ("go", "conditional_go"):
        start_bg(opp.id, "analysis")
    return {"ok": True}


class PastIn(BaseModel):
    project_name: str
    year: int
    client: str = ""
    project_type: str = ""
    disciplines: list[str] = []
    outcome: str = "won"
    complexity: str = "medium"
    notes: str = ""


@app.post("/api/past-projects")
def add_past(body: PastIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    if actor.role not in ("management", "coordinator", "admin"):
        raise HTTPException(403, "Only management / coordinator / admin can add historical evidence.")
    from analysis import norm_disc
    db.add(PastProject(project_name=body.project_name, year=body.year, client=body.client, project_type=body.project_type,
                       disciplines=[norm_disc(d) for d in body.disciplines if d.strip()], outcome=body.outcome,
                       complexity=body.complexity, notes=body.notes, corridor_length_km="N/A", drawing_completeness="unknown",
                       rfi_count_at_tender=0, profit_margin_pct="N/A", active_road="no"))
    db.commit()
    return {"ok": True}


# ── step 4: engineering review ──────────────────────────────────────────────

class FindingReview(BaseModel):
    review: str
    corrected_value: str = ""
    comment: str = ""


class BulkReview(BaseModel):
    ids: list[int]
    review: str


def _can_review(actor: Actor, opp: Opportunity):
    if actor.role != "discipline_lead":
        raise HTTPException(403, "Only the discipline lead validates findings.")
    if opp.status != "engineering_validation":
        raise HTTPException(409, "Findings can only be reviewed during engineering validation.")
    if not actor.name:
        raise HTTPException(400, "Enter your name first.")


def _apply_review(f: Finding, review: str, actor: Actor, corrected="", comment=""):
    if review not in ("pending", "verified", "corrected", "disputed", "assumption"):
        raise HTTPException(400, "Invalid review value")
    if review == "corrected" and not corrected.strip():
        raise HTTPException(400, "Provide the corrected value.")
    if review in ("disputed", "assumption") and not comment.strip():
        raise HTTPException(400, f"Add a comment explaining why this is {review}.")
    f.review, f.reviewer, f.reviewed_at = review, actor.name, datetime.utcnow()
    f.corrected_value = corrected if review == "corrected" else ""
    f.review_comment = comment


@app.patch("/api/findings/{fid}")
def review_finding(fid: int, body: FindingReview, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    f = db.get(Finding, fid)
    if not f or f.superseded:
        raise HTTPException(404, "Finding not found")
    opp = get_opp(db, f.opp_id)
    _can_review(actor, opp)
    _apply_review(f, body.review, actor, body.corrected_value, body.comment)
    touch(db, opp, actor, "finding_reviewed", step="review", reason=body.comment,
          details={"finding": fid, "review": body.review, "value": f.value[:120], "corrected": body.corrected_value[:200]})
    db.commit()
    return {"ok": True}


@app.post("/api/opportunities/{opp_id}/findings/bulk")
def bulk_review(opp_id: int, body: BulkReview, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    _can_review(actor, opp)
    if body.review not in ("verified", "pending"):
        raise HTTPException(400, "Bulk action supports verified / pending only.")
    rows = db.query(Finding).filter(Finding.opp_id == opp_id, Finding.id.in_(body.ids), Finding.superseded.is_(False)).all()
    for f in rows:
        _apply_review(f, body.review, actor)
    touch(db, opp, actor, "findings_bulk_reviewed", step="review", details={"count": len(rows), "review": body.review})
    db.commit()
    return {"updated": len(rows)}


class RfiEdit(BaseModel):
    status: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    response: Optional[str] = None
    priority: Optional[str] = None
    issue: Optional[str] = None


class RfiNew(BaseModel):
    issue: str
    priority: str = "Medium"
    evidence: str = ""
    suggested_action: str = ""


RFI_ROLES = ("coordinator", "discipline_lead", "proposal_manager")
RFI_STATES = ("draft", "approved", "sent", "answered", "closed", "assumption", "dismissed")


@app.patch("/api/rfis/{rid}")
def edit_rfi(rid: int, body: RfiEdit, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    r = db.get(RFI, rid)
    if not r or r.superseded:
        raise HTTPException(404, "RFI not found")
    opp = get_opp(db, r.opp_id)
    if actor.role not in RFI_ROLES:
        raise HTTPException(403, f"Roles allowed to edit RFIs: {', '.join(RFI_ROLES)}.")
    if opp.status in ("draft", "approved_for_export", "archived", "closed_no_go") or opp.status.endswith("_processing"):
        raise HTTPException(409, "RFIs cannot be edited in the current status.")
    ch = {k: v for k, v in body.model_dump().items() if v is not None and v != getattr(r, k)}
    if ch.get("status") and ch["status"] not in RFI_STATES:
        raise HTTPException(400, f"status must be one of {RFI_STATES}")
    new_status = ch.get("status", r.status)
    if new_status in ("assumption", "dismissed") and not (ch.get("response", r.response) or "").strip():
        raise HTTPException(400, "Record the reason in the response field when carrying as an assumption or dismissing.")
    if ch.get("priority") and ch["priority"] not in ("High", "Medium", "Low"):
        raise HTTPException(400, "priority must be High / Medium / Low")
    for k, v in ch.items():
        setattr(r, k, v)
    if ch:
        touch(db, opp, actor, "rfi_updated", step="review", details={"rfi": r.rfi_no, **{k: str(v)[:150] for k, v in ch.items()}})
    db.commit()
    return {"ok": True}


@app.post("/api/opportunities/{opp_id}/rfis")
def add_rfi(opp_id: int, body: RfiNew, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    if actor.role not in RFI_ROLES:
        raise HTTPException(403, f"Roles allowed to add RFIs: {', '.join(RFI_ROLES)}.")
    if opp.status not in ("engineering_validation", "proposal_draft", "capability_review"):
        raise HTTPException(409, "RFIs can be added during review stages only.")
    n = len(prop.current_rfis(db, opp_id)) + 1
    db.add(RFI(opp_id=opp_id, rfi_no=f"RFI-{n:02d}", issue=body.issue, priority=body.priority, evidence=body.evidence,
               suggested_action=body.suggested_action, origin="manual", owner=actor.name))
    touch(db, opp, actor, "rfi_added", step="review", details={"issue": body.issue[:150]})
    db.commit()
    return {"ok": True}


# ── gates ───────────────────────────────────────────────────────────────────

class GateIn(BaseModel):
    version: Optional[int] = None
    action: str            # approve / return
    comment: str = ""


@app.post("/api/opportunities/{opp_id}/gate/{gate}")
def gate(opp_id: int, gate: str, body: GateIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    if gate not in ("g2", "g_prop", "g3", "g4") or body.action not in ("approve", "return"):
        raise HTTPException(400, "gate must be g2/g_prop/g3/g4 and action approve/return")
    opp = get_opp(db, opp_id)
    pv = prop.latest_version(db, opp_id)
    if body.action == "return" and not body.comment.strip():
        raise HTTPException(400, "A comment is required when returning for rework.")
    name = f"{gate}_{'approve' if body.action == 'approve' else 'return'}"
    verno = pv.version_no if (pv and gate != "g2") else None

    if body.action == "approve":
        if gate == "g2":
            blockers = prop.g2_blockers(db, opp_id)
            if blockers:
                raise HTTPException(409, "Cannot approve - unresolved: " + " | ".join(blockers[:5]))
            if not prop.usable(db, opp_id):
                raise HTTPException(409, "Verify at least the key RFQ findings before approving - nothing verified yet.")
        elif gate == "g3":
            if not pv or prop.commercial_total(pv.commercial)["total"] <= 0:
                raise HTTPException(409, "Fees must be entered by the commercial lead before commercial approval.")
        elif gate == "g4":
            bad = [q for q in prop.qa_checklist(db, opp) if q["status"] == "fail"]
            if bad:
                raise HTTPException(409, "Final QA failed: " + " | ".join(f"{q['label']} {q['detail']}".strip() for q in bad))
        wf(check_separation, db, opp_id, gate, actor)
    advance(db, opp, name, actor, version=body.version, reason=body.comment, pv=verno)
    record_approval(db, opp, gate, "approved" if body.action == "approve" else "returned", actor, body.comment, verno)

    if body.action == "return":   # earlier approvals that depended on the returned work no longer hold
        invalidate_approvals(db, opp_id, {"g2": ["g2", "g_prop", "g3", "g4"], "g_prop": ["g_prop", "g3", "g4"],
                                          "g3": ["g_prop", "g3", "g4"], "g4": ["g3", "g4"]}[gate])
    elif gate == "g3" and pv:
        secs = [dict(s) for s in pv.sections]
        for s in secs:
            if s["key"] == "commercial":
                s["content"] = prop.commercial_text(pv.commercial)
                s["source"], s["placeholder"] = "commercial_lead", False
        pv.sections = secs
        pv.status = "in_review"
    elif gate == "g4" and pv:
        pv.status = "approved"
    db.commit()
    if gate == "g2" and body.action == "approve":
        start_bg(opp_id, "proposal")
    return {"ok": True}


# ── step 5/6: proposal & commercial ─────────────────────────────────────────

class SectionEdit(BaseModel):
    key: str
    content: str


class ProposalEdit(BaseModel):
    version: Optional[int] = None
    sections: list[SectionEdit]
    note: str = ""


@app.put("/api/opportunities/{opp_id}/proposal/sections")
def edit_sections(opp_id: int, body: ProposalEdit, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    pv = prop.latest_version(db, opp_id)
    if not pv:
        raise HTTPException(409, "No proposal exists yet.")
    edits = {e.key: e.content for e in body.sections}
    secs = [dict(s) for s in pv.sections]
    changed = []
    for s in secs:
        if s["key"] in edits and edits[s["key"]] != s["content"]:
            if s["key"] == "commercial" and actor.role != "commercial_lead":
                raise HTTPException(403, "Only the commercial lead edits the commercial section.")
            s["content"], s["source"], s["edited_by"] = edits[s["key"]], "human", actor.name
            s["placeholder"] = bool(prop.PLACEHOLDER.search(s["content"]))
            changed.append(s["key"])
    if not changed:
        return {"changed": []}
    advance(db, opp, "edit_proposal", actor, version=body.version, reason=body.note, details={"sections": changed})
    invalidate_approvals(db, opp_id, ["g_prop", "g3", "g4"])   # a material edit invalidates dependent approvals
    new = prop.create_version(db, opp, secs, pv.compliance, actor.name, body.note or f"Edited by {actor.name}: {', '.join(changed)}")
    audit(db, opp.id, actor, "proposal_version_created", step="proposal", proposal_version=new.version_no, details={"sections": changed})
    db.commit()
    return {"changed": changed, "version_no": new.version_no}


class CommercialIn(BaseModel):
    version: Optional[int] = None
    lines: list[dict] = []
    expenses: list[dict] = []
    currency: str = "USD"
    tax_pct: float = 0


@app.put("/api/opportunities/{opp_id}/commercial")
def set_commercial(opp_id: int, body: CommercialIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    if actor.role != "commercial_lead":
        raise HTTPException(403, "Only the commercial lead enters fees, hours and rates.")
    if opp.status not in ("proposal_draft", "commercial_review"):
        raise HTTPException(409, "Fees can be edited during proposal drafting or commercial review only (return the approval first).")
    if body.version is not None and body.version != opp.version:
        raise HTTPException(409, f"This opportunity changed (now version {opp.version}). Reload and retry.")
    pv = prop.latest_version(db, opp_id)
    if not pv:
        raise HTTPException(409, "No proposal exists yet.")
    clean = {"lines": [{"desc": str(l.get("desc", ""))[:200], "hours": float(l.get("hours") or 0), "rate": float(l.get("rate") or 0)}
                       for l in body.lines if l.get("desc")],
             "expenses": [{"desc": str(e.get("desc", ""))[:200], "amount": float(e.get("amount") or 0)} for e in body.expenses if e.get("desc")],
             "currency": body.currency[:5] or "USD", "tax_pct": body.tax_pct, "entered_by": actor.name}
    pv.commercial = clean
    invalidate_approvals(db, opp_id, ["g3", "g4"])
    touch(db, opp, actor, "commercial_updated", step="approval", proposal_version=pv.version_no, details=prop.commercial_total(clean))
    db.commit()
    return {"totals": prop.commercial_total(clean)}


# ── step 7: release, submission, archive ────────────────────────────────────

@app.get("/api/opportunities/{opp_id}/export")
def export_docx(opp_id: int, db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    try:
        path, final = export.build_docx(db, opp)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(db, opp.id, SYSTEM, "exported", step="release", details={"final": final})
    db.commit()
    return FileResponse(path, filename=path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class SubmissionIn(BaseModel):
    status: str = "not_submitted"
    submitted_at: str = ""
    channel: str = ""
    receipt_ref: str = ""
    outcome: str = ""
    notes: str = ""


@app.put("/api/opportunities/{opp_id}/submission")
def set_submission(opp_id: int, body: SubmissionIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    if actor.role not in ("coordinator", "approver"):
        raise HTTPException(403, "Only the coordinator or approver records submission details.")
    if opp.status not in ("approved_for_export", "archived"):
        raise HTTPException(409, "Only an approved proposal can be marked as submitted.")
    if body.status not in ("not_submitted", "submitted", "acknowledged") or body.outcome not in ("", "won", "lost", "withdrawn"):
        raise HTTPException(400, "Invalid status or outcome")
    if body.status != "not_submitted" and not (body.submitted_at and body.channel):
        raise HTTPException(400, "Record the submission date and channel.")
    sub = db.query(Submission).filter(Submission.opp_id == opp_id).first() or Submission(opp_id=opp_id)
    prev_outcome = sub.outcome
    for k, v in body.model_dump().items():
        setattr(sub, k, v)
    sub.recorded_by = actor.name
    db.add(sub)
    if body.outcome in ("won", "lost") and prev_outcome != body.outcome:   # index into the historical library
        ov = db.query(CapabilityAssessment).filter(CapabilityAssessment.opp_id == opp_id).order_by(CapabilityAssessment.run_no.desc()).first()
        discs = [c["discipline"] for c in (ov.coverage if ov else [])]
        db.add(PastProject(project_name=opp.project_name, year=datetime.utcnow().year, client=opp.client,
                           project_type=(ov.overview or {}).get("project_type", "") if ov else "", disciplines=discs, outcome=body.outcome,
                           complexity=(ov.overview or {}).get("complexity", "medium") if ov else "medium", corridor_length_km="N/A",
                           drawing_completeness="n/a", rfi_count_at_tender=len(prop.current_rfis(db, opp_id)), profit_margin_pct="N/A",
                           active_road="no", notes=f"Auto-indexed from {code(opp)} on outcome recording."))
    touch(db, opp, actor, "submission_recorded", step="release", details=body.model_dump())
    db.commit()
    return {"ok": True}


@app.post("/api/opportunities/{opp_id}/archive")
def archive(opp_id: int, body: VersionIn, actor: Actor = Depends(actor_of), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id)
    sub = db.query(Submission).filter(Submission.opp_id == opp_id).first()
    if not sub or sub.status == "not_submitted":
        raise HTTPException(409, "Record the submission (date, channel, receipt) before archiving.")
    advance(db, opp, "archive", actor, version=body.version)
    db.commit()
    return {"ok": True}
