import asyncio
import json
import os
from datetime import datetime

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db, init_db
from models import AnalysisRun, RFQRequirement, DrawingRegister, Discrepancy, ProposalSection, ApprovalLog, PastProject
import pipeline as pl

app = FastAPI(title="RFQ Analysis POC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# run_state[run_id] = { "out": Queue, "in": Queue }
# out: pipeline → SSE → client
# in:  gate_action → pipeline
run_state: dict = {}


@app.on_event("startup")
def on_startup():
    init_db()


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/api/documents")
def get_documents():
    rfq, drawing = pl.find_documents()
    return {
        "rfq": {"name": rfq.name, "size": rfq.stat().st_size} if rfq else None,
        "drawing": {"name": drawing.name, "size": drawing.stat().st_size} if drawing else None,
    }


@app.post("/api/start")
async def start_analysis(db: Session = Depends(get_db)):
    run = AnalysisRun(status="started", current_step="g0")
    db.add(run)
    db.commit()
    db.refresh(run)
    run_state[run.id] = {
        "out": asyncio.Queue(),
        "in": asyncio.Queue(),
    }
    asyncio.create_task(run_pipeline(run.id))
    return {"run_id": run.id}


@app.get("/api/stream/{run_id}")
async def stream(run_id: int):
    async def event_generator():
        if run_id not in run_state:
            yield sse("error", {"message": "Run not found"})
            return
        out_q: asyncio.Queue = run_state[run_id]["out"]
        while True:
            try:
                event = await asyncio.wait_for(out_q.get(), timeout=30)
                yield event
                if "pipeline_done" in event:
                    break
            except asyncio.TimeoutError:
                yield sse("ping", {"ts": datetime.utcnow().isoformat()})
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class GateAction(BaseModel):
    action: str
    role: str = "Reviewer"
    comment: str = ""


@app.post("/api/gate/{run_id}/{gate}")
async def gate_action(run_id: int, gate: str, body: GateAction, db: Session = Depends(get_db)):
    db.add(ApprovalLog(
        run_id=run_id, gate=gate.upper(), action=body.action,
        role=body.role, comment=body.comment,
    ))
    db.commit()

    if run_id in run_state:
        # Put gate decision into the INPUT queue (pipeline reads this)
        await run_state[run_id]["in"].put({
            "gate": gate, "action": body.action, "comment": body.comment,
        })
        # Also notify SSE output so frontend knows the button was clicked
        await run_state[run_id]["out"].put(
            sse("gate_ack", {"gate": gate, "action": body.action})
        )

    return {"status": "ok"}


@app.get("/api/results/{run_id}")
def get_results(run_id: int, db: Session = Depends(get_db)):
    rfq = db.query(RFQRequirement).filter(RFQRequirement.run_id == run_id).all()
    drawings = db.query(DrawingRegister).filter(DrawingRegister.run_id == run_id).all()
    discrepancies = db.query(Discrepancy).filter(Discrepancy.run_id == run_id).all()
    proposal = db.query(ProposalSection).filter(ProposalSection.run_id == run_id).all()
    logs = db.query(ApprovalLog).filter(ApprovalLog.run_id == run_id).all()
    return {
        "rfq": [{"field": r.field, "value": r.value} for r in rfq],
        "drawings": [{"sheet_id": d.sheet_id, "title": d.title, "discipline": d.discipline,
                      "revision": d.revision, "findings": d.findings} for d in drawings],
        "discrepancies": [{"rfi_id": d.rfi_id, "issue": d.issue, "priority": d.priority,
                           "action": d.suggested_action} for d in discrepancies],
        "proposal": [{"number": p.section_number, "title": p.section_title, "content": p.content}
                     for p in proposal],
        "audit": [{"gate": l.gate, "action": l.action, "role": l.role,
                   "comment": l.comment, "timestamp": str(l.timestamp)} for l in logs],
    }


@app.get("/api/export/{run_id}/proposal")
def export_proposal(run_id: int, db: Session = Depends(get_db)):
    rfq_rows = db.query(RFQRequirement).filter(RFQRequirement.run_id == run_id).all()
    proposal_rows = db.query(ProposalSection).filter(ProposalSection.run_id == run_id).all()
    rfq_data = {r.field: r.value for r in rfq_rows}
    proposal_data = {"sections": [{"number": p.section_number, "title": p.section_title,
                                   "content": p.content} for p in proposal_rows]}
    path = pl.export_proposal_docx(run_id, rfq_data, proposal_data)
    return FileResponse(
        path,
        filename=f"AB_Proposal_Run{run_id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── Pipeline runner ──────────────────────────────────────────────────────────

async def run_pipeline(run_id: int):
    db_gen = get_db()
    db: Session = next(db_gen)

    out_q: asyncio.Queue = run_state[run_id]["out"]
    in_q: asyncio.Queue = run_state[run_id]["in"]

    rfq_data, drawing_data, cross_data = {}, {}, {}

    async def emit(step: str, msg: str, **extra):
        await out_q.put(sse("progress", {
            "step": step, "message": msg,
            "ts": datetime.utcnow().isoformat(), **extra
        }))

    async def wait_gate(gate_id: str):
        """Wait for human gate decision from in_q. Returns action string."""
        while True:
            decision = await in_q.get()
            if decision.get("gate") == gate_id:
                return decision["action"], decision.get("comment", "")

    async def keepalive(step: str, msg: str, task: asyncio.Task):
        """Send ping messages every 3s while an AI task is running."""
        dots = 0
        while not task.done():
            await asyncio.sleep(3)
            if not task.done():
                dots = (dots + 1) % 4
                await emit(step, f"{msg}{'.' * (dots + 1)}")

    try:
        # G0
        await emit("g0", "Capturing opportunity metadata…")
        g0 = await pl.step_g0_intake(run_id)
        await emit("g0", f"Manifest created · {g0['rfq_file']} · {g0['drawing_file']}", done=True)

        # G1
        await emit("g1", "Running package quality checks…")
        g1 = await pl.step_g1_quality(run_id)
        for c in g1["checks"]:
            await emit("g1", f"{'✓' if c['readable'] else '✗'} {c['file']} — {'OK' if c['readable'] else 'UNREADABLE'}")
        if g1["status"] == "fail":
            await emit("g1", "Quality gate FAILED — missing files", done=True, failed=True)
            await out_q.put(sse("pipeline_done", {"status": "failed"}))
            return
        await emit("g1", "Quality gate PASSED", done=True)

        # AI Analysis — RFQ + Drawing in parallel with keepalive pings
        await emit("ai_rfq", "Extracting RFQ requirements via AI…")
        await emit("ai_draw", "Analysing engineering drawings via AI Vision…")

        rfq_task = asyncio.create_task(pl.step_extract_rfq(run_id))
        draw_task = asyncio.create_task(pl.step_analyse_drawing(run_id))

        # Keepalive pings for both steps
        ka_rfq = asyncio.create_task(keepalive("ai_rfq", "Reading RFQ document", rfq_task))
        ka_draw = asyncio.create_task(keepalive("ai_draw", "Analysing drawing pages", draw_task))

        rfq_data, drawing_data = await asyncio.gather(rfq_task, draw_task)
        ka_rfq.cancel()
        ka_draw.cancel()

        # Save RFQ
        for field, value in rfq_data.items():
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            db.add(RFQRequirement(run_id=run_id, field=field, value=str(value), source_file=g0["rfq_file"]))
        db.commit()
        await emit("ai_rfq", f"RFQ extraction complete — {len(rfq_data)} fields extracted",
                   done=True, data=rfq_data)

        # Save Drawing
        for sheet in drawing_data.get("sheets", []):
            db.add(DrawingRegister(
                run_id=run_id,
                sheet_id=sheet.get("sheet_id") or sheet.get("drawing_number", ""),
                title=sheet.get("title", ""),
                discipline=sheet.get("discipline", ""),
                revision=sheet.get("revision", ""),
                scale=sheet.get("scale", ""),
                source_file=g0["drawing_file"],
                findings=sheet.get("observations", sheet.get("summary", "")),
            ))
        db.commit()
        await emit("ai_draw", f"Drawing analysis complete — {len(drawing_data.get('sheets', []))} sheet(s)",
                   done=True, data=drawing_data)

        # Cross-document
        await emit("cross", "Comparing RFQ vs drawings — finding gaps…")
        cross_task = asyncio.create_task(pl.step_cross_document(run_id, rfq_data, drawing_data))
        ka_cross = asyncio.create_task(keepalive("cross", "Running cross-document checks", cross_task))
        cross_data = await cross_task
        ka_cross.cancel()

        for d in cross_data.get("discrepancies", []):
            db.add(Discrepancy(
                run_id=run_id, rfi_id=d.get("rfi_id", ""),
                issue=d.get("issue", ""), evidence=d.get("evidence_basis", ""),
                priority=d.get("priority", "Medium"), suggested_action=d.get("suggested_action", ""),
            ))
        db.commit()
        await emit("cross", f"Cross-check done — {len(cross_data.get('discrepancies', []))} RFIs",
                   done=True, data=cross_data)

        # Bid Viability Assessment
        await emit("bid_viability", "Comparing project against historical portfolio…")
        past_rows = db.query(PastProject).all()
        past_projects_list = [
            {
                "project_name": p.project_name, "year": p.year, "project_type": p.project_type,
                "disciplines": p.disciplines, "corridor_length_km": p.corridor_length_km,
                "drawing_completeness": p.drawing_completeness, "rfi_count_at_tender": p.rfi_count_at_tender,
                "outcome": p.outcome, "profit_margin_pct": p.profit_margin_pct, "notes": p.notes,
            }
            for p in past_rows
        ]
        bid_task = asyncio.create_task(
            pl.step_bid_viability(run_id, rfq_data, drawing_data, cross_data, past_projects_list)
        )
        ka_bid = asyncio.create_task(keepalive("bid_viability", "Running portfolio comparison", bid_task))
        bid_data = await bid_task
        ka_bid.cancel()

        rec = bid_data.get("overall_recommendation", "pursue_with_conditions")
        score = bid_data.get("technical_match_score", 0)
        await emit("bid_viability",
                   f"Viability assessment complete — {score}% match · Recommendation: {rec.replace('_',' ').upper()}",
                   done=True, data=bid_data)

        # G_BID Gate — human Go / No-Go decision
        await emit("g_bid", "Awaiting manager Go / No-Go decision on bid", waiting=True)
        action, comment = await wait_gate("g_bid")
        if action == "return":
            await emit("g_bid", f"Bid DECLINED — {comment or 'No-Go decision by manager'}", declined=True)
            await out_q.put(sse("pipeline_done", {"status": "declined", "gate": "g_bid"}))
            return
        await emit("g_bid", "Bid APPROVED — Proceeding to engineering validation ✓", done=True)

        # G2 Gate
        await emit("g2", "Awaiting engineering validation from discipline lead", waiting=True)
        action, comment = await wait_gate("g2")
        if action == "return":
            await emit("g2", f"Returned for rework — {comment}", returned=True)
            await out_q.put(sse("pipeline_done", {"status": "returned", "gate": "g2"}))
            return
        await emit("g2", "Engineering validation APPROVED ✓", done=True)

        # Proposal Assembly
        await emit("proposal", "Assembling proposal from validated findings…")
        prop_task = asyncio.create_task(
            pl.step_generate_proposal(run_id, rfq_data, drawing_data, cross_data)
        )
        ka_prop = asyncio.create_task(keepalive("proposal", "Drafting proposal sections", prop_task))
        proposal_data = await prop_task
        ka_prop.cancel()

        for s in proposal_data.get("sections", []):
            db.add(ProposalSection(
                run_id=run_id, section_number=s["number"],
                section_title=s["title"], content=s["content"],
            ))
        db.commit()
        await emit("proposal", f"Proposal draft v1 ready — {len(proposal_data.get('sections', []))} sections",
                   done=True, data=proposal_data)

        # G3 Gate
        await emit("g3", "Awaiting commercial and management review", waiting=True)
        action, comment = await wait_gate("g3")
        if action == "return":
            await emit("g3", f"Returned for rework — {comment}", returned=True)
            await out_q.put(sse("pipeline_done", {"status": "returned", "gate": "g3"}))
            return
        await emit("g3", "Commercial review APPROVED ✓", done=True)

        # G4 Gate
        await emit("g4", "Awaiting final QA and release approval", waiting=True)
        action, comment = await wait_gate("g4")
        if action == "return":
            await emit("g4", f"Blocked and returned — {comment}", returned=True)
            await out_q.put(sse("pipeline_done", {"status": "returned", "gate": "g4"}))
            return
        await emit("g4", "Final release APPROVED ✓", done=True)

        # Export
        await emit("export", "Generating DOCX proposal and audit trail…")
        run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
        if run:
            run.status = "completed"
            db.commit()
        await emit("export", "Export ready — proposal available for download", done=True)
        await out_q.put(sse("pipeline_done", {"status": "complete"}))

    except Exception as e:
        await emit("g0", f"Pipeline error: {str(e)}", error=True)
        await out_q.put(sse("pipeline_done", {"status": "error", "message": str(e)}))
    finally:
        db.close()
