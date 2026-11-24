from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from db import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id = Column(Integer, primary_key=True)
    status = Column(String(50), default="started")
    current_step = Column(String(50), default="g0")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RFQRequirement(Base):
    __tablename__ = "rfq_requirements"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer)
    field = Column(String(100))
    value = Column(Text)
    source_file = Column(String(200))
    source_page = Column(String(50))


class DrawingRegister(Base):
    __tablename__ = "drawing_register"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer)
    sheet_id = Column(String(100))
    title = Column(Text)
    discipline = Column(String(100))
    revision = Column(String(50))
    scale = Column(String(50))
    source_file = Column(String(200))
    findings = Column(JSON)


class Discrepancy(Base):
    __tablename__ = "discrepancies"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer)
    rfi_id = Column(String(20))
    issue = Column(Text)
    evidence = Column(Text)
    priority = Column(String(20))
    suggested_action = Column(Text)


class ProposalSection(Base):
    __tablename__ = "proposal_sections"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer)
    section_number = Column(Integer)
    section_title = Column(String(200))
    content = Column(Text)


class ApprovalLog(Base):
    __tablename__ = "approval_log"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer)
    gate = Column(String(10))
    action = Column(String(20))
    role = Column(String(100))
    comment = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    version = Column(Integer, default=1)
