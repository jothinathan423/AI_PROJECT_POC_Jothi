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


class PastProject(Base):
    __tablename__ = "past_projects"
    id = Column(Integer, primary_key=True)
    project_name = Column(String(300))
    year = Column(Integer)
    client = Column(String(200))
    project_type = Column(String(100))          # road_rehabilitation, stormwater, bridge, building, etc.
    disciplines = Column(JSON)                  # list of strings
    corridor_length_km = Column(String(20))     # nullable, stored as string e.g. "2.1" or "N/A"
    drawing_completeness = Column(String(50))   # complete / partial / illustrative
    rfi_count_at_tender = Column(Integer)
    outcome = Column(String(20))                # won / lost / declined
    profit_margin_pct = Column(String(10))      # "18" or "N/A"
    complexity = Column(String(20))             # low / medium / high
    active_road = Column(String(10))            # yes / no
    notes = Column(Text)
