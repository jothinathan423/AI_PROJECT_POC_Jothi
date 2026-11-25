"""AI + rule steps: capability check (step 2) and technical analysis (step 3).

Design rules taken from the AB documents:
  * every finding carries source file + page, confidence and a status (Extracted / AI-suggested / Needs verification)
  * a quote only counts as a citation if it can be located in the cited page text (mechanical check)
  * no evidence -> "Insufficient historical evidence", never a guess
  * drawing scale/units are never trusted: measurements not read from the sheet are flagged, never certified
  * the capability recommendation (A/B/C/D) is computed from evidence by rules, not chosen by the LLM
"""
import asyncio
import base64
import json
import os
import re
from collections import defaultdict
from datetime import datetime

import fitz
from sqlalchemy import func
from sqlalchemy.orm import Session

import llm
from ingest import SCANNED_PAGE_CHARS, verify_quote
from models import PastProject
from models_v2 import CapabilityAssessment, FilePage, Finding, OppFile, Opportunity, RFI
from workflow import log

MAX_DRAWING_PAGES = int(os.getenv("MAX_DRAWING_PAGES", "12"))
RFQ_CHAR_BUDGET = 70000
CROSS_CHAR_BUDGET = 24000

DISCIPLINE_VOCAB = ["roadway", "stormwater", "utilities", "traffic_management", "pedestrian", "structural",
                    "architectural", "geotechnical", "survey", "bridge", "environmental"]
SYNONYMS = {"road": "roadway", "roads": "roadway", "highway": "roadway", "drainage": "stormwater",
            "storm_water": "stormwater", "utility": "utilities", "traffic": "traffic_management",
            "bridges": "bridge", "geotech": "geotechnical", "surveying": "survey"}


def norm_disc(d: str) -> str:
    d = re.sub(r"[\s\-/]+", "_", str(d).strip().lower())
    return SYNONYMS.get(d, d)


# ── shared loaders ──────────────────────────────────────────────────────────

def live_files(db: Session, opp_id: int, kinds: list[str] | None = None) -> list[OppFile]:
    q = db.query(OppFile).filter(OppFile.opp_id == opp_id, OppFile.superseded.is_(False), OppFile.duplicate_of.is_(None),
                                 OppFile.extract_status == "ready")
    rows = q.order_by(OppFile.id).all()
    return [f for f in rows if not kinds or f.kind in kinds]


def page_map(db: Session, files: list[OppFile]) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    for f in files:
        rows = db.query(FilePage).filter(FilePage.file_id == f.id).order_by(FilePage.page_no).all()
        out[f.filename] = {r.page_no: r.text for r in rows}
    return out


def render_text(files: list[OppFile], pmap: dict, budget: int) -> tuple[str, bool]:
    """Page-tagged text block for prompts. Returns (text, truncated)."""
    parts, used, truncated = [], 0, False
    for f in files:
        parts.append(f"\n=== FILE: {f.filename} (type={f.kind}; locator={f.locator_kind}) ===")
        for pn, text in pmap.get(f.filename, {}).items():
            if not text.strip():
                continue
            chunk = f"[[{f.filename} | {f.locator_kind} {pn}]]\n{text.strip()}"
            if used + len(chunk) > budget:
                truncated = True
                break
            parts.append(chunk)
            used += len(chunk)
        if truncated:
            break
    return "\n".join(parts), truncated


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Historical experience & capability assessment
# ═══════════════════════════════════════════════════════════════════════════

OVERVIEW_SYSTEM = """You read the start of a civil/construction RFQ and summarise what is being asked.
Return JSON: {"project_name": str, "client_name": str, "location": str, "project_type": str (e.g. road_rehabilitation,
stormwater, bridge, building), "disciplines": [str], "scope_summary": str (max 60 words), "standards": [str],
"complexity": "low|medium|high"}.
Disciplines MUST be chosen from this list when applicable: %s (add other short snake_case names only if none fit).
Use "" / [] when the text does not say."""

CAP_SYSTEM = """You are a bid manager at AB Consultants writing a short capability note for management.
You are given the RFQ overview, a rule-computed discipline coverage table and the matched historical records
(each with an ID like P-003). Do NOT change the coverage levels or the recommendation.
Return JSON: {"narrative": str (max 110 words; cite record IDs in square brackets, e.g. [P-003]),
"gaps": [{"item": str, "kind": "partner|resource|evidence|standard", "note": str}],
"risks": [str], "relevant_ids": [str], "suggested_conditions": [str]}.
Only cite IDs from the supplied records. If evidence is thin say so plainly; never claim experience that is not in the records."""


def _evidence_type(p: PastProject) -> str:
    return "won_project" if (p.outcome or "").lower() == "won" else "proposal_only"


def compute_coverage(required: list[str], past: list[PastProject], project_type: str):
    this_year = datetime.utcnow().year
    coverage, by_id = [], {}
    for d in required:
        matches = [p for p in past if d in {norm_disc(x) for x in (p.disciplines or [])}]
        won = [p for p in matches if _evidence_type(p) == "won_project"]
        level = "Strong" if len(won) >= 2 else ("Partial" if (won or matches) else "No evidence")
        coverage.append({"discipline": d, "level": level, "won": len(won), "proposal_only": len(matches) - len(won),
                         "record_ids": [f"P-{p.id:03d}" for p in matches]})
        for p in matches:
            rec = by_id.setdefault(p.id, {
                "id": f"P-{p.id:03d}", "project_name": p.project_name, "year": p.year, "client": p.client,
                "project_type": p.project_type, "outcome": p.outcome, "evidence_type": _evidence_type(p),
                "profit_margin_pct": p.profit_margin_pct, "complexity": p.complexity,
                "notes": (p.notes or "")[:240], "matched_disciplines": [],
                "stale": bool(p.year and p.year < this_year - 5),
            })
            rec["matched_disciplines"].append(d)
    for p in past:   # same project type counts as supporting evidence even without discipline overlap
        if project_type and (p.project_type or "") == project_type and p.id not in by_id:
            by_id[p.id] = {
                "id": f"P-{p.id:03d}", "project_name": p.project_name, "year": p.year, "client": p.client,
                "project_type": p.project_type, "outcome": p.outcome, "evidence_type": _evidence_type(p),
                "profit_margin_pct": p.profit_margin_pct, "complexity": p.complexity, "notes": (p.notes or "")[:240],
                "matched_disciplines": [], "stale": bool(p.year and p.year < this_year - 5)}
    ranked = sorted(by_id.values(), key=lambda r: (-len(r["matched_disciplines"]), r["evidence_type"] != "won_project",
                                                    -(r["year"] or 0)))
    return coverage, ranked[:8]


def recommend(coverage: list[dict], n_records: int) -> tuple[str, str]:
    """A potentially capable / B conditional / C no-go recommendation / D insufficient evidence."""
    n = len(coverage)
    if n_records < 3 or n == 0:
        return "D", "low"
    strong = sum(1 for c in coverage if c["level"] == "Strong")
    none = sum(1 for c in coverage if c["level"] == "No evidence")
    if none == n and n_records >= 5:
        return "C", "medium"
    if none == n:
        return "D", "low"
    if strong == n:
        return "A", "high" if n_records >= 5 else "medium"
    return "B", "medium"


async def run_capability(db: Session, opp: Opportunity) -> CapabilityAssessment:
    files = live_files(db, opp.id, ["rfq", "addendum"])
    if not files:
        raise RuntimeError("No readable RFQ document - upload one and confirm the package again.")
    pmap = page_map(db, files)
    text, _ = render_text(files, pmap, 14000)

    log(db, opp.id, "capability", "Reading RFQ overview…")
    db.commit()
    vocab = sorted(set(DISCIPLINE_VOCAB) | {norm_disc(d) for p in db.query(PastProject).all() for d in (p.disciplines or [])})
    overview = await llm.chat_json(OVERVIEW_SYSTEM % ", ".join(vocab), text)
    required = []
    for d in overview.get("disciplines") or []:
        nd = norm_disc(d)
        if nd and nd not in required:
            required.append(nd)

    past = db.query(PastProject).all()
    log(db, opp.id, "capability", f"Searching {len(past)} historical records for {len(required)} required discipline(s)…")
    coverage, matched = compute_coverage(required, past, overview.get("project_type", ""))
    rec, conf = recommend(coverage, len(past))

    narrative, gaps, risks, conditions = "", [], [], []
    try:
        out = await llm.chat_json(CAP_SYSTEM, json.dumps({"overview": overview, "coverage": coverage,
                                                           "matched_records": matched, "records_in_library": len(past)}))
        valid = {m["id"] for m in matched}
        narrative = re.sub(r"\[(P-\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", out.get("narrative", ""))
        gaps = [g for g in out.get("gaps", []) if isinstance(g, dict)]
        risks = [str(r) for r in out.get("risks", [])]
        conditions = [str(c) for c in out.get("suggested_conditions", [])]
    except Exception as e:
        log(db, opp.id, "capability", f"AI narrative unavailable ({e}); showing rule-based result only.")

    for c in coverage:     # deterministic gaps, whatever the LLM says
        if c["level"] == "No evidence":
            gaps.append({"item": c["discipline"], "kind": "evidence", "note": "No matching record in AB's historical library."})
        elif c["level"] == "Partial":
            gaps.append({"item": c["discipline"], "kind": "evidence", "note": "Limited evidence (fewer than 2 won projects)."})
    if rec == "D":
        narrative = (narrative + " " if narrative else "") + (
            f"Insufficient historical evidence: only {len(past)} record(s) in the library. This is NOT a finding that AB lacks capability - management review is required.")

    run_no = (db.query(func.max(CapabilityAssessment.run_no)).filter(CapabilityAssessment.opp_id == opp.id).scalar() or 0) + 1
    ca = CapabilityAssessment(opp_id=opp.id, run_no=run_no, overview=overview, coverage=coverage, matched_projects=matched,
                              gaps=gaps, risks=risks, narrative=narrative, recommendation=rec, confidence=conf,
                              evidence_count=len(past))
    ca.decision_conditions = "; ".join(conditions)   # AI-suggested; the human decision overwrites it
    db.add(ca)
    # fill blank opportunity metadata from the overview
    for attr, key in (("project_name", "project_name"), ("client", "client_name"), ("location", "location")):
        if not getattr(opp, attr) and overview.get(key):
            setattr(opp, attr, str(overview[key])[:300])
    db.flush()
    return ca


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — RFQ + drawing + cross-document analysis
# ═══════════════════════════════════════════════════════════════════════════

RFQ_SYSTEM = """You extract structured information from civil-engineering RFQ/RFP documents. Text is tagged with
[[file | page N]] markers. For EVERY item give the file, page number and a SHORT VERBATIM quote (copied exactly from the text)
that supports it. Do not paraphrase inside "quote".
Return JSON:
{"fields": {"<name>": {"value": str, "file": str, "page": int, "quote": str, "confidence": "high|medium|low"}},
 "requirements": [{"text": str, "category": "scope|deliverable|submission|technical|commercial|legal|schedule|evaluation",
                   "mandatory": bool, "file": str, "page": int, "quote": str, "confidence": "high|medium|low"}]}
fields must use these names: project_name, client_name, location, rfq_reference, procurement_type, submission_deadline,
clarification_deadline, scope_summary, disciplines, key_deliverables, evaluation_criteria, submission_instructions,
contract_conditions, standards. Use value "Not specified" (and empty quote) if the documents do not say.
Include every mandatory ("shall", "must", "required") requirement. Max 60 requirements."""

DRAWING_SYSTEM = """You are a civil-engineering drawing register clerk. You see ONE drawing sheet (image) plus its text layer (if any).
Read only what is visible. Return JSON:
{"sheet": {"sheet_id": str, "title": str, "discipline": str, "revision": str, "date": str, "scale": str,
           "status": "read_from_drawing|ai_inferred|not_available", "confidence": "high|medium|low"},
 "observations": [{"text": str, "category": "note|label|dimension|schedule|callout|stationing|legend|other",
                   "method": "read_from_drawing|calculated|ai_inferred|not_available",
                   "units": str, "region": str, "confidence": "high|medium|low"}],
 "referenced_sheets": [str], "legible": bool, "issues": [str]}
RULES: Copy text exactly when method is read_from_drawing. NEVER measure lengths/areas/quantities from the image: scale and
units are not validated - report such values only if printed on the sheet, otherwise use method not_available.
Use empty string when a title-block field is not legible. Max 25 observations."""

CROSS_SYSTEM = """You are a senior proposal analyst. Compare the RFQ requirements, the drawing register/observations and the
specification/BOQ excerpts. Items carry IDs like F123. Report only POTENTIAL discrepancies - a reviewer decides if real.
Return JSON:
{"discrepancies": [{"issue": str, "evidence_basis": str (cite F-ids or file/page), "priority": "High|Medium|Low",
                    "suggested_action": str, "impact": str}],
 "risks": [{"risk": str, "severity": "high|medium|low", "source": str}],
 "summary": str}
Look for: missing referenced information, revision conflicts, scope vs BOQ mismatches, spec vs drawing-note inconsistencies,
missing survey/geotechnical/utility data, unclear responsibilities. Write each as a draft clarification question where suitable.
Max 15 discrepancies, 8 risks."""


def _status_for(method: str, confidence: str, verified: bool) -> str:
    if method in ("not_available",) or confidence == "low":
        return "needs_verification"
    if method in ("ai_inferred", "calculated"):
        return "ai_suggested"
    return "extracted" if verified else "needs_verification"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def analyse_rfq(db: Session, opp: Opportunity, run_no: int, pmap_all: dict) -> int:
    files = live_files(db, opp.id, ["rfq", "addendum"])
    if not files:
        return 0
    pmap = {f.filename: pmap_all[f.filename] for f in files}
    text, truncated = render_text(files, pmap, RFQ_CHAR_BUDGET)
    if truncated:
        log(db, opp.id, "analysis", "⚠ RFQ text exceeded the analysis budget - later pages were not read.")
    out = await llm.chat_json(RFQ_SYSTEM, text, max_tokens=8000)
    n = 0
    for name, item in (out.get("fields") or {}).items():
        if not isinstance(item, dict):
            continue
        val = item.get("value", "")
        val = "; ".join(map(str, val)) if isinstance(val, list) else str(val)
        ok, pg, fn = verify_quote(item.get("quote", ""), pmap, item.get("file", ""), item.get("page"))
        absent = val.strip().lower() in ("", "not specified")
        method = "not_available" if absent else "read_from_source"
        db.add(Finding(opp_id=opp.id, run_no=run_no, kind="rfq_field", key=name, value=val, source_file=fn,
                       source_page=pg or _int(item.get("page")), quote=item.get("quote", ""), quote_verified=ok,
                       method=method, confidence=item.get("confidence", "medium"),
                       status=_status_for(method, item.get("confidence", "medium"), ok)))
        n += 1
        for attr, fld in (("project_name", "project_name"), ("client", "client_name"), ("location", "location"),
                          ("rfq_reference", "rfq_reference"), ("procurement_type", "procurement_type"),
                          ("submission_deadline", "submission_deadline"), ("clarification_deadline", "clarification_deadline")):
            if name == fld and not absent and not getattr(opp, attr):
                setattr(opp, attr, val[:300])
    for r in (out.get("requirements") or [])[:60]:
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            continue
        ok, pg, fn = verify_quote(r.get("quote", ""), pmap, r.get("file", ""), r.get("page"))
        mand = bool(r.get("mandatory"))
        db.add(Finding(opp_id=opp.id, run_no=run_no, kind="requirement", key=str(r.get("category", "scope")),
                       value=str(r["text"]).strip(), source_file=fn, source_page=pg or _int(r.get("page")),
                       quote=r.get("quote", ""), quote_verified=ok, method="read_from_source",
                       confidence=r.get("confidence", "medium"), critical=mand,
                       status=_status_for("read_from_source", r.get("confidence", "medium"), ok), data={"mandatory": mand}))
        n += 1
    db.flush()
    return n


def _render_pdf_page(path: str, page_index: int) -> str:
    doc = fitz.open(path)
    try:
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(1.6, 1.6))
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


async def analyse_drawings(db: Session, opp: Opportunity, run_no: int, pmap_all: dict) -> dict:
    files = live_files(db, opp.id, ["drawing"])
    jobs = []   # (file, page_no, image_b64 loader)
    skipped = 0
    for f in files:
        if f.stored_path.lower().endswith(".pdf"):
            total = f.page_count or 0
            for i in range(min(total, MAX_DRAWING_PAGES)):
                jobs.append((f, i + 1))
            skipped += max(0, total - MAX_DRAWING_PAGES)
        else:
            jobs.append((f, 1))
    sem = asyncio.Semaphore(3)

    async def one(f: OppFile, pn: int):
        async with sem:
            if f.stored_path.lower().endswith(".pdf"):
                img = await asyncio.to_thread(_render_pdf_page, f.stored_path, pn - 1)
            else:
                img = base64.b64encode(open(f.stored_path, "rb").read()).decode()
            layer = (pmap_all.get(f.filename, {}).get(pn) or "")[:3500]
            user = f"File: {f.filename}, page {pn}.\nText layer of this page (may be empty):\n{layer or '(none)'}"
            try:
                return f, pn, await llm.chat_json(DRAWING_SYSTEM, user, images=[img], max_tokens=3500), None
            except Exception as e:
                return f, pn, None, str(e)

    results = await asyncio.gather(*[one(f, pn) for f, pn in jobs])
    stats = {"sheets": 0, "observations": 0, "failed_pages": 0, "skipped_pages": skipped}
    for f, pn, out, err in results:
        if err or not out:
            stats["failed_pages"] += 1
            db.add(RFI(opp_id=opp.id, rfi_no="", issue=f"Drawing page {f.filename} p.{pn} could not be analysed.",
                       evidence=err or "empty response", priority="Medium", origin="rule",
                       suggested_action="Re-run the analysis, or supply a clearer / searchable copy of this sheet."))
            continue
        sh = out.get("sheet") or {}
        layer = pmap_all.get(f.filename, {}).get(pn) or ""
        conf = sh.get("confidence", "medium")
        sid = (sh.get("sheet_id") or "").strip()
        db.add(Finding(
            opp_id=opp.id, run_no=run_no, kind="drawing_sheet", key=sid or f"{f.filename} p.{pn}",
            value=sh.get("title", ""), source_file=f.filename, source_page=pn, method=sh.get("status", "read_from_drawing"),
            confidence=conf, status=_status_for(sh.get("status", "read_from_drawing"), conf, bool(sid and sid.lower() in layer.lower())),
            data={**{k: sh.get(k, "") for k in ("sheet_id", "discipline", "revision", "date", "scale")},
                  "referenced_sheets": out.get("referenced_sheets") or [], "legible": out.get("legible", True),
                  "issues": out.get("issues") or [], "has_text_layer": len(layer) >= SCANNED_PAGE_CHARS}))
        stats["sheets"] += 1
        if out.get("legible") is False:
            db.add(RFI(opp_id=opp.id, rfi_no="", issue=f"{f.filename} p.{pn} is not fully legible ({'; '.join(out.get('issues') or []) or 'poor scan'}).",
                       evidence="Vision read flagged as not legible.", priority="Medium", origin="rule",
                       suggested_action="Request a higher-resolution or native-PDF copy of this sheet."))
        for ob in (out.get("observations") or [])[:25]:
            if not isinstance(ob, dict) or not str(ob.get("text", "")).strip():
                continue
            t, method, c = str(ob["text"]).strip(), ob.get("method", "read_from_drawing"), ob.get("confidence", "medium")
            verified = bool(layer) and verify_quote(t, {f.filename: {pn: layer}}, f.filename, pn)[0]
            data = {"units": ob.get("units", ""), "region": ob.get("region", ""), "category": ob.get("category", "other")}
            status = _status_for(method, c, verified)
            if method in ("ai_inferred", "calculated") and re.search(r"\d", t):
                data["measurement_warning"] = "Not reliably measurable from supplied file - engineer verification required."
                status = "needs_verification"
            db.add(Finding(opp_id=opp.id, run_no=run_no, kind="observation", key=data["category"], value=t,
                           source_file=f.filename, source_page=pn, quote=t if verified else "", quote_verified=verified,
                           method=method, confidence=c, status=status, data=data))
            stats["observations"] += 1
    db.flush()
    return stats


def rule_checks(db: Session, opp: Opportunity, run_no: int) -> list[dict]:
    """Deterministic discrepancy checks that need no LLM: revision conflicts + references to sheets not supplied."""
    sheets = db.query(Finding).filter(Finding.opp_id == opp.id, Finding.run_no == run_no, Finding.kind == "drawing_sheet").all()
    by_id = defaultdict(set)
    where = {}
    for s in sheets:
        sid = (s.data or {}).get("sheet_id", "").strip().upper()
        if sid:
            by_id[sid].add(((s.data or {}).get("revision") or "").strip() or "(blank)")
            where.setdefault(sid, f"{s.source_file} p.{s.source_page}")
    found = []
    for sid, revs in by_id.items():
        if len(revs - {"(blank)"}) > 1:
            found.append({"issue": f"Sheet {sid} appears with conflicting revisions: {', '.join(sorted(revs))}. Which is the governing revision?",
                          "evidence_basis": f"Title blocks read at {where[sid]}.", "priority": "High",
                          "suggested_action": "Ask the client to confirm the governing revision and issue the current set.",
                          "impact": "Wrong revision could change scope or quantities."})
    for s in sheets:
        for ref in (s.data or {}).get("referenced_sheets") or []:
            r = str(ref).strip().upper()
            if r and r not in by_id and r != ((s.data or {}).get("sheet_id") or "").strip().upper():
                found.append({"issue": f"Sheet {r} is referenced on {s.source_file} p.{s.source_page} but is not in the supplied drawing set.",
                              "evidence_basis": f"Reference read from {s.source_file} p.{s.source_page}.", "priority": "Medium",
                              "suggested_action": f"Request sheet {r} or confirm it is not part of the package.",
                              "impact": "Information needed to scope the work may be missing."})
    # de-duplicate on the issue text
    seen, out = set(), []
    for d in found:
        if d["issue"] not in seen:
            seen.add(d["issue"])
            out.append(d)
    return out


async def cross_check(db: Session, opp: Opportunity, run_no: int, pmap_all: dict, rule_items: list[dict]) -> tuple[int, int]:
    rows = db.query(Finding).filter(Finding.opp_id == opp.id, Finding.run_no == run_no).all()
    compact = {
        "rfq_fields": [f"F{r.id} {r.key}: {r.value[:1500]} ({r.source_file} p.{r.source_page})" for r in rows if r.kind == "rfq_field"],
        "requirements": [f"F{r.id} [{'MANDATORY' if r.critical else 'optional'}] {r.value[:1500]} ({r.source_file} p.{r.source_page})" for r in rows if r.kind == "requirement"],
        "drawing_register": [f"F{r.id} {r.key} '{r.value}' rev={r.data.get('revision')} disc={r.data.get('discipline')} scale={r.data.get('scale')} ({r.source_file} p.{r.source_page})" for r in rows if r.kind == "drawing_sheet"],
        "drawing_observations": [f"F{r.id} [{r.method}] {r.value[:200]} ({r.source_file} p.{r.source_page})" for r in rows if r.kind == "observation"][:120],
    }
    other = live_files(db, opp.id, ["spec", "boq", "report"])
    sb_text, _ = render_text(other, {f.filename: pmap_all[f.filename] for f in other}, CROSS_CHAR_BUDGET)
    present = {f.kind for f in live_files(db, opp.id)}
    missing = [k for k in ("spec", "boq") if k not in present]
    user = json.dumps(compact)[:40000] + f"\n\nSPEC/BOQ/REPORT EXCERPTS:\n{sb_text or '(none supplied)'}\n\nNot supplied at all: {missing or 'nothing'}\nAlready found by rule checks (do not repeat): {[d['issue'] for d in rule_items]}"
    out = await llm.chat_json(CROSS_SYSTEM, user, max_tokens=6000)
    ai_items = [d for d in (out.get("discrepancies") or []) if isinstance(d, dict) and d.get("issue")][:15]

    for d, origin in [(x, "rule") for x in rule_items] + [(x, "ai") for x in ai_items]:
        pr = str(d.get("priority", "Medium")).capitalize()
        db.add(RFI(opp_id=opp.id, rfi_no="", issue=d["issue"], evidence=d.get("evidence_basis", ""),
                   priority=pr if pr in ("High", "Medium", "Low") else "Medium", suggested_action=d.get("suggested_action", ""),
                   impact=d.get("impact", ""), origin=origin))
    db.flush()
    current = db.query(RFI).filter(RFI.opp_id == opp.id, RFI.superseded.is_(False)).order_by(RFI.id).all()
    for i, r in enumerate(current, 1):     # number the current register RFI-01.. (illegible-page RFIs included)
        r.rfi_no = f"RFI-{i:02d}"
    n_rfi = len(current)
    n_risk = 0
    for r in (out.get("risks") or [])[:8]:
        if isinstance(r, dict) and r.get("risk"):
            sev = str(r.get("severity", "medium")).lower()
            db.add(Finding(opp_id=opp.id, run_no=run_no, kind="risk", key=sev, value=str(r["risk"]), source_file=str(r.get("source", ""))[:290],
                           method="ai_inferred", confidence="medium", status="ai_suggested", critical=(sev == "high")))
            n_risk += 1
    db.flush()
    return n_rfi, n_risk


async def run_analysis(db: Session, opp: Opportunity) -> dict:
    files = live_files(db, opp.id)
    pmap = page_map(db, files)
    run_no = (db.query(func.max(Finding.run_no)).filter(Finding.opp_id == opp.id).scalar() or 0) + 1
    # earlier outputs are preserved but marked superseded
    db.query(Finding).filter(Finding.opp_id == opp.id, Finding.superseded.is_(False)).update({"superseded": True})
    db.query(RFI).filter(RFI.opp_id == opp.id, RFI.superseded.is_(False)).update({"superseded": True})
    db.commit()

    log(db, opp.id, "analysis", "Extracting RFQ requirements and reading drawing sheets in parallel…")
    db.commit()
    n_rfq, dstats = await asyncio.gather(analyse_rfq(db, opp, run_no, pmap), analyse_drawings(db, opp, run_no, pmap))
    log(db, opp.id, "analysis", f"RFQ: {n_rfq} items extracted · Drawings: {dstats['sheets']} sheet(s), {dstats['observations']} observation(s)"
        + (f" · {dstats['failed_pages']} page(s) failed" if dstats["failed_pages"] else "")
        + (f" · {dstats['skipped_pages']} page(s) beyond the {MAX_DRAWING_PAGES}-page limit not read" if dstats["skipped_pages"] else ""))
    db.commit()
    rules = rule_checks(db, opp, run_no)
    log(db, opp.id, "analysis", f"Rule checks found {len(rules)} revision/reference issue(s). Cross-checking RFQ vs drawings vs spec/BOQ…")
    db.commit()
    n_rfi, n_risk = await cross_check(db, opp, run_no, pmap, rules)
    log(db, opp.id, "analysis", f"Cross-check complete: {n_rfi} draft RFI(s), {n_risk} risk(s). Awaiting engineering review.")
    return {"run_no": run_no, "rfq_items": n_rfq, **dstats, "rfis": n_rfi, "risks": n_risk}
