import os
import json
import base64
import asyncio
from pathlib import Path
from datetime import datetime

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-6-luna")
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-6-luna")

DOCS_DIR = Path(__file__).parent / "documents"
EXPORTS_DIR = Path(__file__).parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────

def find_documents():
    """Return (rfq_path, drawing_path) from the documents folder."""
    rfq_path = None
    drawing_path = None
    for f in DOCS_DIR.iterdir():
        name = f.name.lower()
        if f.suffix == ".docx" or ("rfq" in name or "request" in name or "package" in name):
            rfq_path = f
        elif f.suffix == ".pdf" or ("drawing" in name or "civil" in name or "plan" in name):
            drawing_path = f
    # fallback: first .docx is RFQ, first .pdf is drawing
    if not rfq_path or not drawing_path:
        for f in DOCS_DIR.iterdir():
            if f.suffix == ".docx" and not rfq_path:
                rfq_path = f
            elif f.suffix == ".pdf" and not drawing_path:
                drawing_path = f
    return rfq_path, drawing_path


def extract_text_from_docx(path: Path) -> str:
    doc = DocxDocument(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_text_from_pdf(path: Path) -> str:
    doc = fitz.open(str(path))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def pdf_pages_to_base64(path: Path, max_pages: int = 2) -> list[str]:
    """Convert PDF pages to base64 PNG for vision API."""
    doc = fitz.open(str(path))
    images = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append(base64.b64encode(img_bytes).decode())
    doc.close()
    return images


# ── Pipeline Steps ─────────────────────────────────────────────────────────

async def step_g0_intake(run_id: int) -> dict:
    rfq_path, drawing_path = find_documents()
    return {
        "status": "pass",
        "rfq_file": rfq_path.name if rfq_path else None,
        "drawing_file": drawing_path.name if drawing_path else None,
        "timestamp": datetime.utcnow().isoformat(),
    }


async def step_g1_quality(run_id: int) -> dict:
    rfq_path, drawing_path = find_documents()
    result = {"checks": [], "status": "pass"}

    if rfq_path and rfq_path.exists():
        result["checks"].append({"file": rfq_path.name, "readable": True, "type": "RFQ"})
    else:
        result["checks"].append({"file": "RFQ", "readable": False})
        result["status"] = "fail"

    if drawing_path and drawing_path.exists():
        doc = fitz.open(str(drawing_path))
        pages = len(doc)
        doc.close()
        result["checks"].append({"file": drawing_path.name, "readable": True, "pages": pages, "type": "Drawing"})
    else:
        result["checks"].append({"file": "Drawing", "readable": False})
        result["status"] = "fail"

    return result


async def step_extract_rfq(run_id: int) -> dict:
    rfq_path, _ = find_documents()
    if rfq_path.suffix == ".docx":
        text = extract_text_from_docx(rfq_path)
    else:
        text = extract_text_from_pdf(rfq_path)

    prompt = """You are an expert at analysing civil engineering RFQ documents.
Extract the following from the document text and return ONLY valid JSON:
{
  "project_name": "",
  "client_name": "",
  "location": "",
  "submission_deadline": "",
  "procurement_type": "",
  "scope_summary": "",
  "disciplines": [],
  "key_deliverables": [],
  "evaluation_criteria": [],
  "mandatory_requirements": [],
  "contract_conditions": "",
  "source_pages": "document pages referenced"
}
If a field is not found write "Not specified".
Document text:
""" + text[:8000]

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


async def step_analyse_drawing(run_id: int) -> dict:
    _, drawing_path = find_documents()
    images = pdf_pages_to_base64(drawing_path, max_pages=2)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": """You are an expert civil engineering drawing analyst.
Analyse these engineering drawing pages and return ONLY valid JSON:
{
  "sheets": [
    {
      "sheet_id": "",
      "title": "",
      "discipline": "",
      "revision": "",
      "date": "",
      "scale": "",
      "status": "read_from_drawing or ai_inferred or not_available",
      "observations": [],
      "labels_found": [],
      "notes_found": [],
      "confidence": "high or medium or low"
    }
  ],
  "overall_summary": "",
  "missing_information": []
}
Classify each finding as: read_from_drawing, ai_inferred, or not_available.
Do NOT calculate quantities or measurements without confirmed scale/units."""
                },
                *[
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
                    for img in images
                ],
            ],
        }
    ]

    response = await client.chat.completions.create(
        model=VISION_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        max_completion_tokens=2000,
    )
    return json.loads(response.choices[0].message.content)


async def step_cross_document(run_id: int, rfq_data: dict, drawing_data: dict) -> dict:
    prompt = f"""You are a senior civil engineering proposal analyst.
Compare the RFQ requirements with the drawing analysis below.
Identify gaps, missing information, inconsistencies and generate RFI questions.
Return ONLY valid JSON:
{{
  "discrepancies": [
    {{
      "rfi_id": "RFI-01",
      "issue": "",
      "evidence_basis": "",
      "priority": "High or Medium or Low",
      "suggested_action": ""
    }}
  ],
  "missing_documents": [],
  "cross_check_summary": ""
}}

RFQ Data:
{json.dumps(rfq_data, indent=2)[:3000]}

Drawing Data:
{json.dumps(drawing_data, indent=2)[:3000]}
"""
    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


async def step_generate_proposal(run_id: int, rfq_data: dict, drawing_data: dict, cross_data: dict) -> dict:
    prompt = f"""You are an expert civil engineering proposal writer for AB Consultants.
Using ONLY the validated information below, generate a professional proposal draft.
Return ONLY valid JSON:
{{
  "sections": [
    {{"number": 1, "title": "Executive Summary", "content": ""}},
    {{"number": 2, "title": "Project Understanding", "content": ""}},
    {{"number": 3, "title": "Scope of Services", "content": ""}},
    {{"number": 4, "title": "Technical Approach", "content": ""}},
    {{"number": 5, "title": "Key Deliverables", "content": ""}},
    {{"number": 6, "title": "Project Schedule", "content": ""}},
    {{"number": 7, "title": "Assumptions and Exclusions", "content": ""}},
    {{"number": 8, "title": "Fee Proposal", "content": "FEE NOT SET BY AI - Requires authorised AB commercial input"}}
  ]
}}

Important rules:
- Do NOT invent quantities, fees or certify any measurements
- Mark any unverified drawing observations as "subject to engineer validation"
- Section 8 Fee must always say fees require human authorised input

RFQ Data: {json.dumps(rfq_data, indent=2)[:2000]}
Drawing Data Summary: {json.dumps(drawing_data.get("overall_summary",""), indent=2)[:1000]}
Gaps/RFIs: {json.dumps(cross_data, indent=2)[:1500]}
"""
    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


async def step_bid_viability(
    run_id: int, rfq_data: dict, drawing_data: dict, cross_data: dict, past_projects: list
) -> dict:
    """Compare current project against historical portfolio to assess bid viability."""
    rfi_count = len(cross_data.get("discrepancies", []))
    high_rfis = sum(
        1 for d in cross_data.get("discrepancies", [])
        if d.get("priority", "").lower() == "high"
    )

    past_summary = [
        {
            "project_name": p.get("project_name"),
            "year": p.get("year"),
            "type": p.get("project_type"),
            "disciplines": p.get("disciplines"),
            "corridor_km": p.get("corridor_length_km"),
            "drawing_completeness": p.get("drawing_completeness"),
            "rfi_count_at_tender": p.get("rfi_count_at_tender"),
            "outcome": p.get("outcome"),
            "profit_margin_pct": p.get("profit_margin_pct"),
            "notes": p.get("notes"),
        }
        for p in past_projects
    ]

    prompt = f"""You are a senior bid manager at AB Consultants, a civil engineering firm.
Analyse this new project against our historical project portfolio and assess bid viability.

CURRENT PROJECT:
- Name: {rfq_data.get("project_name", "Not specified")}
- Client: {rfq_data.get("client_name", "Not specified")}
- Disciplines required: {rfq_data.get("disciplines", [])}
- Scope: {rfq_data.get("scope_summary", "")[:400]}
- Drawing completeness: illustrative / not for construction
- Total RFIs raised: {rfi_count} (of which {high_rfis} are HIGH severity)
- Drawing sheets analysed: {len(drawing_data.get("sheets", []))}

HISTORICAL PROJECT PORTFOLIO (all AB Consultants past bids):
{json.dumps(past_summary, indent=2)}

Based on this portfolio comparison, return ONLY valid JSON:
{{
  "technical_match_score": <integer 0-100 — how well our discipline history matches>,
  "rfi_risk_level": "low or medium or high",
  "rfi_risk_reason": "<one sentence explaining the risk level>",
  "overall_recommendation": "pursue or pursue_with_conditions or do_not_pursue",
  "recommendation_summary": "<2-3 sentence explanation of the recommendation>",
  "top_similar_projects": [
    {{
      "project_name": "",
      "year": 0,
      "outcome": "",
      "profit_margin_pct": "",
      "similarity_reason": "<why this past project is relevant>"
    }}
  ],
  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "key_strengths": ["<strength 1>", "<strength 2>", "<strength 3>"]
}}

Rules:
- top_similar_projects: pick the 3 most relevant entries from the portfolio above
- If rfi_count >= 9: set rfi_risk_level to "high"
- If we declined a nearly identical project before (Bay Road, 11 RFIs), factor that in
- If outcome of similar projects was mostly won with good margin: lean toward "pursue"
- do_not_pursue only if we clearly lack the disciplines OR risk is unacceptably high
"""
    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def export_proposal_docx(run_id: int, rfq_data: dict, proposal_data: dict) -> str:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Title
    title = doc.add_heading("AB CONSULTANTS", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_heading("AI-ASSISTED PROPOSAL DRAFT", 2)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"Project: {rfq_data.get('project_name', 'N/A')}")
    doc.add_paragraph(f"Client: {rfq_data.get('client_name', 'N/A')}")
    doc.add_paragraph(f"Generated: {datetime.utcnow().strftime('%d %B %Y')}")
    doc.add_paragraph("Status: DRAFT — Pending Final Approval")
    doc.add_paragraph("")

    for section in proposal_data.get("sections", []):
        doc.add_heading(f"{section['number']}. {section['title']}", 1)
        doc.add_paragraph(section.get("content", ""))
        doc.add_paragraph("")

    out_path = EXPORTS_DIR / f"proposal_run{run_id}.docx"
    doc.save(str(out_path))
    return str(out_path)
