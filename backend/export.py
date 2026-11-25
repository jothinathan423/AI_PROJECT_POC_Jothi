"""DOCX export of the proposal package: proposal + compliance matrix + drawing register + RFI register + approvals/audit."""
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from sqlalchemy.orm import Session

from ingest import UPLOADS_DIR
from models_v2 import Approval, AuditEvent, Finding, Opportunity
from proposal import current_rfis, latest_version

EXPORTS_DIR = UPLOADS_DIR.parent / "exports"
FINAL_STATUSES = ("approved_for_export", "archived")


def _table(doc, headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = h
        for r in t.rows[0].cells[i].paragraphs[0].runs:
            r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v if v is not None else "")
    return t


def build_docx(db: Session, opp: Opportunity) -> tuple[str, bool]:
    EXPORTS_DIR.mkdir(exist_ok=True)
    pv = latest_version(db, opp.id)
    if not pv:
        raise ValueError("No proposal version exists yet.")
    final = opp.status in FINAL_STATUSES
    doc = Document()
    hdr = doc.sections[0].header.paragraphs[0]
    hdr.text = (f"FINAL - approved proposal v{pv.version_no}" if final else "DRAFT - NOT APPROVED FOR RELEASE")
    hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in hdr.runs:
        r.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x6F, 0x3A) if final else RGBColor(0xC0, 0x1F, 0x1F)

    doc.add_heading("AB CONSULTANTS", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_heading(opp.project_name or "Proposal", 2).alignment = WD_ALIGN_PARAGRAPH.CENTER
    for line in (f"Opportunity: OPP-{opp.id:04d}", f"Client: {opp.client}", f"RFQ reference: {opp.rfq_reference}",
                 f"Proposal version: v{pv.version_no}", f"Status: {opp.status.replace('_', ' ').title()}",
                 f"Generated: {datetime.utcnow():%d %B %Y %H:%M} UTC"):
        doc.add_paragraph(line)
    if not final:
        p = doc.add_paragraph("This document is an unapproved draft. It must not be sent to the client.")
        p.runs[0].bold = True

    for s in pv.sections:
        doc.add_heading(f"{s['number']}. {s['title']}", 1)
        for para in str(s.get("content", "")).split("\n"):
            doc.add_paragraph(para)

    doc.add_page_break()
    doc.add_heading("Appendix A - Requirement compliance matrix", 1)
    _table(doc, ["Requirement", "Mandatory", "Source", "Proposal section(s)", "Status"],
           [[c["text"], "Yes" if c["mandatory"] else "", c["source"], ", ".join(c["sections"]), c["status"]] for c in pv.compliance])

    doc.add_heading("Appendix B - Drawing register (as read from supplied files)", 1)
    sheets = db.query(Finding).filter(Finding.opp_id == opp.id, Finding.superseded.is_(False), Finding.kind == "drawing_sheet").all()
    _table(doc, ["Sheet", "Title", "Discipline", "Revision", "Scale", "Source", "Review"],
           [[s.data.get("sheet_id") or s.key, s.value, s.data.get("discipline"), s.data.get("revision"), s.data.get("scale"),
             f"{s.source_file} p.{s.source_page}", s.review] for s in sheets])

    doc.add_heading("Appendix C - Clarification / RFI register", 1)
    _table(doc, ["No.", "Priority", "Issue", "Status", "Response"],
           [[r.rfi_no, r.priority, r.issue, r.status, r.response] for r in current_rfis(db, opp.id)])

    doc.add_heading("Appendix D - Approval history", 1)
    appr = db.query(Approval).filter(Approval.opp_id == opp.id).order_by(Approval.id).all()
    _table(doc, ["Gate", "Decision", "By", "Role", "Version", "Valid", "Comment", "When (UTC)"],
           [[a.gate, a.decision, a.actor_name, a.actor_role, a.proposal_version or "", "yes" if a.valid else "superseded",
             a.comment, f"{a.created_at:%Y-%m-%d %H:%M}"] for a in appr])

    doc.add_heading("Appendix E - Audit trail", 1)
    ev = db.query(AuditEvent).filter(AuditEvent.opp_id == opp.id).order_by(AuditEvent.seq).all()
    _table(doc, ["#", "When (UTC)", "Actor", "Action", "From > To", "Reason"],
           [[e.seq, f"{e.ts:%Y-%m-%d %H:%M}", f"{e.actor_name} ({e.actor_role})", e.action,
             f"{e.from_status} > {e.to_status}" if e.from_status != e.to_status else "", e.reason] for e in ev])
    for p in doc.paragraphs:
        for r in p.runs:
            r.font.size = r.font.size or Pt(10.5)

    path = EXPORTS_DIR / f"proposal_opp{opp.id}_v{pv.version_no}_{'FINAL' if final else 'DRAFT'}.docx"
    doc.save(str(path))
    return str(path), final
