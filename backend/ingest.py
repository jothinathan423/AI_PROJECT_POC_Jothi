"""Step 1 helpers: file classification, page-level text extraction, package manifest and quality status.

Every extracted unit is stored as a (file, page_no) row so each later finding can cite its source.
"""
import hashlib
import re
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from sqlalchemy.orm import Session

from models_v2 import FilePage, OppFile

UPLOADS_DIR = Path(__file__).parent / "uploads"
MAX_FILE_BYTES = 50 * 1024 * 1024
BLOCK_CHARS = 3000          # DOCX has no fixed pages -> pseudo-pages ("blocks") so citations stay meaningful
SCANNED_PAGE_CHARS = 30     # a PDF page with less text than this is treated as scanned / image-only

TEXT_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".txt"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
CAD_EXT = {".dwg", ".dxf", ".dgn", ".rvt"}   # reference attachments only (no CAD/BIM parsing in the baseline POC)
ALLOWED_EXT = TEXT_EXT | IMAGE_EXT | CAD_EXT

KINDS = ["rfq", "drawing", "spec", "boq", "addendum", "report", "cad", "other"]


def classify(filename: str) -> str:
    """Guess the document role from name + extension. The coordinator can change it afterwards."""
    name = filename.lower()
    ext = Path(name).suffix
    if ext in CAD_EXT:
        return "cad"
    if "addend" in name:
        return "addendum"
    if any(k in name for k in ("drawing", "dwg", "plan", "sheet", "layout")) or ext in IMAGE_EXT:
        return "drawing"
    if any(k in name for k in ("boq", "quantity", "bill_of", "bill of", "schedule of")) or ext in {".xlsx", ".csv"}:
        return "boq"
    if "spec" in name:
        return "spec"
    if any(k in name for k in ("geotech", "survey", "report", "utility", "topograph")):
        return "report"
    if any(k in name for k in ("rfq", "rfp", "request", "tender", "package", "itt")):
        return "rfq"
    return "other"


def safe_name(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name)[:120] or "file"


# ── Extraction ──────────────────────────────────────────────────────────────

def _extract_pdf(path: Path):
    doc = fitz.open(str(path))
    pages = [p.get_text("text").strip() for p in doc]
    doc.close()
    return pages, "page"


def _docx_blocks(path: Path) -> list[str]:
    doc = DocxDocument(str(path))
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = Paragraph(child, doc).text.strip()
            if t:
                lines.append(t)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells, seen = [], set()
                for c in row.cells:
                    if id(c._tc) in seen:     # merged cells repeat the same underlying element
                        continue
                    seen.add(id(c._tc))
                    if c.text.strip():
                        cells.append(c.text.strip().replace("\n", " "))
                if cells:
                    lines.append(" | ".join(cells))
    blocks, cur, size = [], [], 0
    for ln in lines:
        cur.append(ln)
        size += len(ln)
        if size >= BLOCK_CHARS:
            blocks.append("\n".join(cur))
            cur, size = [], 0
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _extract_xlsx(path: Path):
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    pages = []
    for ws in wb.worksheets:
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 2000:
                rows.append("[... truncated at 2000 rows ...]")
                break
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                rows.append(" | ".join(cells))
        pages.append(f"[Sheet: {ws.title}]\n" + "\n".join(rows))
    wb.close()
    return pages, "sheet"


def extract_pages(path: Path) -> tuple[list[str], str]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _docx_blocks(path), "block"
    if ext == ".xlsx":
        return _extract_xlsx(path)
    if ext in {".csv", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        return [text[i:i + BLOCK_CHARS * 2] for i in range(0, max(len(text), 1), BLOCK_CHARS * 2)], "block"
    raise ValueError(f"no text extractor for {ext}")


def store_file(db: Session, opp_id: int, filename: str, data: bytes, uploader: str, mime: str = "") -> OppFile:
    """Save an uploaded file (originals are immutable), extract its pages, return the OppFile row."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"File type {ext or '(none)'} is not supported. Allowed: {', '.join(sorted(ALLOWED_EXT))}")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    if not data:
        raise ValueError("File is empty")

    sha = hashlib.sha256(data).hexdigest()
    existing = db.query(OppFile).filter(OppFile.opp_id == opp_id).all()
    dup = next((f for f in existing if f.sha256 == sha), None)
    same_name = [f for f in existing if f.filename == filename]

    folder = UPLOADS_DIR / str(opp_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{sha[:10]}_{safe_name(filename)}"
    if not stored.exists():
        stored.write_bytes(data)

    f = OppFile(
        opp_id=opp_id, filename=filename, kind=classify(filename), stored_path=str(stored),
        mime=mime, size_bytes=len(data), sha256=sha, uploaded_by=uploader,
        revision_no=len(same_name) + 1, duplicate_of=dup.id if dup else None,
    )
    if same_name:
        for old in same_name:     # keep the old file, but mark it superseded by the new revision
            old.superseded = True
    db.add(f)
    db.flush()

    if ext in CAD_EXT:
        f.extract_status = "reference_only"
        f.extract_error = "CAD/BIM file kept as a reference attachment; not parsed in this POC."
    elif ext in IMAGE_EXT:
        f.extract_status, f.page_count, f.locator_kind, f.scanned_pages = "ready", 1, "page", 1
    elif dup:
        f.extract_status, f.extract_error = "ready", f"Duplicate of file #{dup.id}; pages not re-extracted."
        f.page_count, f.locator_kind = dup.page_count, dup.locator_kind
    else:
        try:
            pages, loc = extract_pages(stored)
            f.locator_kind, f.page_count = loc, len(pages)
            f.scanned_pages = sum(1 for t in pages if len(t) < SCANNED_PAGE_CHARS) if ext == ".pdf" else 0
            for i, t in enumerate(pages, 1):
                db.add(FilePage(file_id=f.id, page_no=i, text=t))
            f.extract_status = "ready" if pages else "failed"
            if not pages:
                f.extract_error = "No content could be extracted."
        except Exception as e:  # corrupt / password-protected / unsupported content
            f.extract_status, f.extract_error = "failed", f"{type(e).__name__}: {e}"[:400]
    db.flush()
    return f


# ── Manifest & package quality ──────────────────────────────────────────────

def file_issues(f: OppFile) -> list[str]:
    issues = []
    if f.extract_status == "failed":
        issues.append(f"Unreadable: {f.extract_error}")
    if f.duplicate_of:
        issues.append(f"Duplicate of file #{f.duplicate_of}")
    if f.superseded:
        issues.append("Superseded by a newer revision of this file")
    if f.extract_status == "reference_only":
        issues.append("Reference only (not parsed)")
    if f.scanned_pages and f.kind != "drawing":
        issues.append(f"{f.scanned_pages} page(s) have no text layer (scanned) - not read in this POC")
    return issues


def package_check(files: list[OppFile]) -> dict:
    """Return {status, missing, warnings, counts}. Gate G0/G1: core RFQ + drawing must be readable."""
    live = [f for f in files if not f.superseded and not f.duplicate_of]
    readable = lambda kind: [f for f in live if f.kind == kind and f.extract_status == "ready"]
    missing, warnings = [], []

    if not readable("rfq"):
        missing.append("RFQ / RFP document (readable)")
    if not readable("drawing"):
        missing.append("Engineering drawings (readable)")
    for kind, label in (("spec", "Technical specifications"), ("boq", "BOQ / quantity schedule")):
        if not readable(kind):
            warnings.append(f"No {label} supplied - related cross-checks will be skipped")
    for f in live:
        if f.extract_status == "failed":
            warnings.append(f"{f.filename}: unreadable - {f.extract_error}")
        elif f.scanned_pages and f.kind in ("rfq", "spec", "boq", "addendum", "report"):
            warnings.append(f"{f.filename}: {f.scanned_pages} scanned page(s) with no text layer")
        if f.kind == "other":
            warnings.append(f"{f.filename}: document type unclassified - set its type so it is analysed")
    for f in files:
        if f.duplicate_of:
            warnings.append(f"{f.filename}: duplicate upload ignored")
    status = "Incomplete" if missing else ("Warning" if warnings else "Ready")
    return {
        "status": status, "missing": missing, "warnings": warnings,
        "counts": {"files": len(live), "pages": sum(f.page_count or 0 for f in live)},
    }


# ── Quote verification (a citation only counts if the quote exists in the cited page) ──

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def verify_quote(quote: str, file_pages: dict[str, dict[int, str]], file: str, page) -> tuple[bool, int | None, str]:
    """Locate `quote` in the pages of `file`. Returns (verified, page_no_found, resolved_filename)."""
    q = _norm(quote)
    if len(q) < 12:
        return False, None, file
    candidates = [file] + [k for k in file_pages if k != file]
    for fname in candidates:
        pages = file_pages.get(fname)
        if not pages:
            continue
        order = list(pages.keys())
        try:
            if fname == file and page is not None and int(page) in pages:
                order.remove(int(page))
                order.insert(0, int(page))
        except (TypeError, ValueError):
            pass
        for pn in order:
            if q in _norm(pages[pn]):
                return True, pn, fname
    return False, None, file
