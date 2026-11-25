"""Opportunity-based workflow models (7-step core flow from the AB workflow document).

The older run_id based tables in models.py are kept for reference but are no longer used.
Importing this module registers the tables on db.Base, so init_db() creates them.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint

from db import Base


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    client = Column(String(300), default="")
    project_name = Column(String(400), default="")
    rfq_reference = Column(String(200), default="")
    location = Column(String(300), default="")
    procurement_type = Column(String(200), default="")
    submission_deadline = Column(String(100), default="")
    clarification_deadline = Column(String(100), default="")  # after it closes, RFIs can no longer be asked
    owner = Column(String(200), default="")
    status = Column(String(50), default="draft")
    package_status = Column(String(20), default="Incomplete")  # Ready / Warning / Incomplete
    version = Column(Integer, default=1)  # bumped on every audited change (optimistic lock)
    close_reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OppFile(Base):
    __tablename__ = "opp_files"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    filename = Column(String(300))
    kind = Column(String(30), default="other")  # rfq / drawing / spec / boq / addendum / report / cad / other
    stored_path = Column(String(500))
    mime = Column(String(100), default="")
    size_bytes = Column(Integer, default=0)
    sha256 = Column(String(64), default="")
    page_count = Column(Integer, default=0)
    locator_kind = Column(String(10), default="page")  # page / block (docx) / sheet (xlsx)
    extract_status = Column(String(20), default="pending")  # ready / failed / reference_only
    extract_error = Column(Text, default="")
    scanned_pages = Column(Integer, default=0)
    revision_no = Column(Integer, default=1)  # n-th upload of the same filename; originals are never overwritten
    superseded = Column(Boolean, default=False)
    duplicate_of = Column(Integer, nullable=True)
    uploaded_by = Column(String(200), default="")
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class FilePage(Base):
    __tablename__ = "file_pages"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, index=True)
    page_no = Column(Integer)
    text = Column(Text, default="")


class StepState(Base):
    __tablename__ = "step_states"
    __table_args__ = (UniqueConstraint("opp_id", "step", name="uq_step_opp"),)
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    step = Column(String(30))
    # not_started / in_progress / awaiting_review / returned / approved / blocked / needs_refresh / archived
    status = Column(String(30), default="not_started")
    messages = Column(JSON, default=list)
    inputs = Column(Text, default="")
    ai_summary = Column(Text, default="")
    outputs = Column(Text, default="")
    owner = Column(String(200), default="")
    decided_by = Column(String(200), default="")
    decision = Column(String(100), default="")
    decided_at = Column(DateTime, nullable=True)
    ai_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Finding(Base):
    __tablename__ = "findings"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    run_no = Column(Integer, default=1)
    superseded = Column(Boolean, default=False)
    kind = Column(String(30))  # rfq_field / requirement / drawing_sheet / observation / risk
    key = Column(String(200), default="")
    value = Column(Text, default="")
    source_file = Column(String(300), default="")
    source_page = Column(Integer, nullable=True)
    quote = Column(Text, default="")
    quote_verified = Column(Boolean, default=False)  # quote was mechanically located in the source page text
    method = Column(String(30), default="read_from_source")  # read_from_source / ai_inferred / calculated / not_available / rule
    confidence = Column(String(10), default="medium")
    status = Column(String(30), default="needs_verification")  # extracted / ai_suggested / needs_verification
    review = Column(String(20), default="pending")  # pending / verified / corrected / disputed / assumption
    corrected_value = Column(Text, default="")
    critical = Column(Boolean, default=False)
    reviewer = Column(String(200), default="")
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, default="")
    data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class RFI(Base):
    __tablename__ = "rfis"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    rfi_no = Column(String(20))
    issue = Column(Text, default="")
    evidence = Column(Text, default="")
    priority = Column(String(10), default="Medium")
    suggested_action = Column(Text, default="")
    impact = Column(Text, default="")
    origin = Column(String(10), default="ai")  # ai / rule / manual
    owner = Column(String(200), default="")
    due_date = Column(String(50), default="")
    # draft / approved / sent / answered / closed / assumption / dismissed
    status = Column(String(20), default="draft")
    response = Column(Text, default="")
    superseded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CapabilityAssessment(Base):
    __tablename__ = "capability_assessments"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    run_no = Column(Integer, default=1)
    overview = Column(JSON, default=dict)
    coverage = Column(JSON, default=list)  # per discipline: level + matched record ids
    matched_projects = Column(JSON, default=list)
    gaps = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    narrative = Column(Text, default="")
    recommendation = Column(String(1), default="D")  # A / B / C / D
    confidence = Column(String(10), default="low")
    evidence_count = Column(Integer, default=0)
    decision = Column(String(20), default="")  # go / conditional_go / no_go / request_evidence
    decision_conditions = Column(Text, default="")
    decision_by = Column(String(200), default="")
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProposalVersion(Base):
    __tablename__ = "proposal_versions"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    version_no = Column(Integer)
    sections = Column(JSON, default=list)
    compliance = Column(JSON, default=list)
    commercial = Column(JSON, default=dict)  # human-entered only: {"lines": [...], "currency": ...}
    status = Column(String(20), default="draft")  # draft / in_review / approved / superseded
    note = Column(Text, default="")
    created_by = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    gate = Column(String(20))  # g_cap / g2 / g_prop / g3 / g4
    decision = Column(String(30))
    proposal_version = Column(Integer, nullable=True)
    actor_name = Column(String(200))
    actor_role = Column(String(50))
    comment = Column(Text, default="")
    valid = Column(Boolean, default=True)  # False once the approved version is edited / superseded
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
    """Append-only: rows are only ever inserted, never updated or deleted."""
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, index=True)
    seq = Column(Integer)
    ts = Column(DateTime, default=datetime.utcnow)
    actor_name = Column(String(200), default="system")
    actor_role = Column(String(50), default="system")
    action = Column(String(60))
    step = Column(String(30), default="")
    from_status = Column(String(50), default="")
    to_status = Column(String(50), default="")
    proposal_version = Column(Integer, nullable=True)
    reason = Column(Text, default="")
    details = Column(JSON, default=dict)


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True)
    opp_id = Column(Integer, unique=True, index=True)
    status = Column(String(20), default="not_submitted")  # not_submitted / submitted / acknowledged
    submitted_at = Column(String(50), default="")
    channel = Column(String(100), default="")
    receipt_ref = Column(String(200), default="")
    outcome = Column(String(20), default="")  # won / lost / withdrawn
    notes = Column(Text, default="")
    recorded_by = Column(String(200), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
