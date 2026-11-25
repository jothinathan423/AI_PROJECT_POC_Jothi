"""Offline stand-in for the LLM, enabled with LLM_MOCK=1 (demos and tests without API credits).

It returns deterministic JSON in the same shape as the real prompts. Quotes are copied from the supplied text so the
mechanical citation check can be exercised. It is NOT an analysis of the documents - never use it for real bids.
"""
import json
import re


def _pages(user: str):
    """[(file, page, first_lines)] from '[[file | page N]]' tagged text."""
    out = []
    for m in re.finditer(r"\[\[(.+?) \| \w+ (\d+)\]\]\n(.*?)(?=\n\[\[|\n=== FILE|\Z)", user, re.S):
        lines = [l.strip() for l in m.group(3).split("\n") if len(l.strip()) > 25]
        out.append((m.group(1), int(m.group(2)), lines))
    return out


def mock_response(system: str, user: str, images) -> dict:
    s = system.lower()
    if "start of a civil/construction rfq" in s:
        return {"project_name": "Mock Roadway & Stormwater Improvements", "client_name": "Mock Public Works", "location": "Mock City",
                "project_type": "road_rehabilitation", "disciplines": ["roadway", "stormwater", "geotechnical"],
                "scope_summary": "Mock overview for offline testing.", "standards": [], "complexity": "medium"}
    if "writing a short capability note" in s:
        data = json.loads(user)
        ids = [m["id"] for m in data.get("matched_records", [])][:2]
        return {"narrative": f"Mock note: AB has relevant roadway/stormwater history {' '.join(f'[{i}]' for i in ids)}.",
                "gaps": [{"item": "geotechnical", "kind": "partner", "note": "Would need a geotechnical partner."}],
                "risks": ["Mock risk: limited geotechnical record."], "relevant_ids": ids, "suggested_conditions": ["Engage a geotechnical sub-consultant"]}
    if "extract structured information from civil-engineering rfq" in s:
        pages = _pages(user)
        f, p, lines = pages[0]
        fields = {"project_name": {"value": "Mock Roadway & Stormwater Improvements", "file": f, "page": p, "quote": lines[0][:80], "confidence": "high"},
                  "client_name": {"value": "Mock Public Works", "file": f, "page": p, "quote": lines[1][:80] if len(lines) > 1 else "", "confidence": "medium"},
                  "submission_deadline": {"value": "Not specified", "file": f, "page": p, "quote": "", "confidence": "low"}}
        reqs = [{"text": f"Mock requirement {i + 1}: " + ln[:90], "category": "scope", "mandatory": i == 0, "file": f, "page": p, "quote": ln[:80],
                 "confidence": "high"} for i, ln in enumerate(lines[2:5])]
        reqs.append({"text": "Mock requirement with a quote that is not in the document", "category": "legal", "mandatory": True, "file": f, "page": p,
                     "quote": "this sentence does not appear anywhere in the source", "confidence": "medium"})
        return {"fields": fields, "requirements": reqs}
    if "drawing register clerk" in s:
        m = re.search(r"page (\d+)\.", user)
        pn = int(m.group(1)) if m else 1
        layer = user.split("Text layer of this page (may be empty):", 1)[-1].strip()
        first = next((l.strip() for l in layer.split("\n") if len(l.strip()) > 15), "")
        return {"sheet": {"sheet_id": f"C-{100 + pn}" if pn != 3 else "C-103", "title": f"Mock sheet {pn}", "discipline": "Civil",
                          "revision": "B" if pn == 5 else "A", "date": "", "scale": "1:500", "status": "read_from_drawing", "confidence": "high"},
                "observations": [{"text": first, "category": "note", "method": "read_from_drawing", "units": "", "region": "title block", "confidence": "high"},
                                 {"text": "Pipe length approx 42 m", "category": "dimension", "method": "ai_inferred", "units": "m", "region": "", "confidence": "medium"}],
                "referenced_sheets": ["C-999"] if pn == 1 else [], "legible": pn != 7, "issues": ["scan quality poor"] if pn == 7 else []}
    if "senior proposal analyst" in s:
        return {"discrepancies": [{"issue": "Mock: confirm governing drawing revision.", "evidence_basis": "F1", "priority": "High",
                                   "suggested_action": "Ask client.", "impact": "Scope"},
                                  {"issue": "Mock: BOQ basis unclear.", "evidence_basis": "F2", "priority": "Medium", "suggested_action": "Ask client.", "impact": ""}],
                "risks": [{"risk": "Mock: utilities unlocated.", "severity": "high", "source": "F3"}], "summary": "mock"}
    if "draft sections of a civil-engineering proposal" in s:
        data = json.loads(user)
        items = data["verified_items"]
        ids = [i["id"] for i in items][:2]
        req = [i["id"] for i in items if i["kind"] == "requirement"]
        cite = " ".join(f"[F{i}]" for i in ids) + " [F99999]"   # one bogus id to exercise citation stripping
        keys = re.search(r"exactly these keys, in order: ([^.]+)\.", system).group(1).split(", ")
        return {"sections": [{"key": k, "content": f"Mock {k} section {cite}. Subject to confirmation.", "requirement_ids": req[: 1 + (n % 2) * 2]}
                             for n, k in enumerate(keys)]}
    return {}
