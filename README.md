# AB Consultants — AI-Powered RFQ & Drawing Analysis · Proposal Workflow

A proof-of-concept pipeline that ingests a civil engineering RFQ package (DOCX + PDF drawings), runs AI analysis across multiple stages, compares the project against historical portfolio data, and assembles a draft proposal — with human gate decisions at key checkpoints.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Project Structure](#project-structure)
4. [Environment Setup](#environment-setup)
5. [Database Setup](#database-setup)
6. [Backend Setup](#backend-setup)
7. [Frontend Setup](#frontend-setup)
8. [Running the Application](#running-the-application)
9. [Pipeline Steps](#pipeline-steps)
10. [Database Tables](#database-tables)

---

## Architecture Overview

```
Frontend (React + Vite)          Backend (FastAPI + Python)
  localhost:5173            ←→     localhost:8001
  
  - 7-step workflow UI              - Background AI steps (UI polls)
  - Role-based gates                - OpenAI GPT-4o (text + vision)
  - Findings review + approvals     - PostgreSQL via SQLAlchemy
  - View complete process           - DOCX export via python-docx
```

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10 + | 3.12 recommended |
| Node.js | 18 + | For React frontend |
| PostgreSQL | 14 + | Local or remote instance |
| OpenAI API Key | — | GPT-4o access required |

---

## Project Structure

```
AI_PROJECT_POC/
├── backend/
│   ├── main.py               # FastAPI app + pipeline runner
│   ├── pipeline.py           # All AI pipeline step functions
│   ├── models.py             # SQLAlchemy ORM models
│   ├── db.py                 # DB connection + session factory
│   ├── seed_past_projects.py # Seeds 10 mock past projects
│   ├── documents/            # Sample RFQ + drawing for trials
│   ├── uploads/              # Files uploaded through the app (git-ignored)
│   └── exports/              # Generated DOCX proposals saved here
├── frontend/
│   ├── src/
│   │   ├── pages/PipelinePage.jsx   # Main pipeline UI
│   │   └── components/              # Header, ResultCard, etc.
│   └── package.json
├── example.env               # Template — copy to .env
├── requirements.txt          # Python dependencies
└── README.md
```

---

## Environment Setup

1. Copy the example env file and fill in your values:

```bash
cp example.env .env
```

2. Edit `.env`:

```env
# OpenAI
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_TEXT_MODEL=gpt-4o
OPENAI_VISION_MODEL=gpt-4o

# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=rfq_poc
DB_USER=postgres
DB_PASSWORD=your-db-password
```

> **Never commit `.env`** — it is listed in `.gitignore`.

---

## Database Setup

### 1. Create the PostgreSQL database

Connect to PostgreSQL and run:

```sql
CREATE DATABASE rfq_poc;
```

If your user is not `postgres`, also run:

```sql
CREATE USER your_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE rfq_poc TO your_user;
```

### 2. Create all tables

Tables are created automatically on first backend startup via SQLAlchemy's `create_all`. No manual migration needed.

The following tables are created:

| Table | Purpose |
|-------|---------|
| `analysis_runs` | Tracks each pipeline execution |
| `rfq_requirements` | AI-extracted RFQ fields |
| `drawing_register` | AI-extracted drawing sheet data |
| `discrepancies` | Cross-document gaps / RFI register |
| `proposal_sections` | AI-generated proposal draft sections |
| `approval_log` | Audit trail of all gate decisions |
| `past_projects` | Historical project portfolio for bid viability |

### 3. Seed past projects (required for Bid Viability step)

```bash
cd backend
python seed_past_projects.py
```

This inserts 10 mock historical projects. It is safe to re-run — skips if data already exists.

---

## Backend Setup

```bash
# From the project root
cd backend

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Frontend Setup

```bash
cd frontend
npm install
```

---

## Running the Application

### Start the backend

```bash
cd backend
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS / Linux

uvicorn main:app --port 8001 --reload
```

Backend runs at: `http://localhost:8001`

### Start the frontend

```bash
cd frontend
npm run dev
```

Frontend runs at: `http://localhost:5173`

### Add documents
Open the app, create an opportunity and upload the RFQ package in step 1 (files are stored under `backend/uploads/`, which is git-ignored). The sample files in `backend/documents/` can be used for a trial.

---

## Workflow (7 steps, 5 human gates)

| # | Step | Who / what |
|---|------|-----------|
| 1 | Intake & package | Coordinator creates an opportunity and uploads many files (RFQ, drawings, spec, BOQ, addenda). Manifest + package status (Ready / Warning / Incomplete). |
| 2 | Historical capability check | Rule-based discipline coverage from past projects + cited records → recommendation A/B/C/D. **Management gate:** Go / Conditional Go / No-Go / Request evidence. |
| 3 | Technical analysis | RFQ extraction, every drawing sheet read, rule checks, cross-check → findings (source page, confidence, status) + draft RFIs + risks. |
| 4 | Engineering review | Discipline lead verifies / corrects / disputes / assumes each finding; RFI register. **Gate G2** (blocked while critical items are open). |
| 5 | Proposal | Drafted from verified findings only; versioned; compliance matrix. **Gate:** proposal manager. |
| 6 | Commercial & final approval | Commercial lead enters fees (never AI). **Gate G3**, QA checklist, **Gate G4** (separation of duties). |
| 7 | Release & archive | DRAFT/FINAL DOCX package, manual submission record, archive. |

Roles are chosen in the top bar (demo switcher, **not authentication**). Approvals are bound to the proposal version; editing a proposal invalidates dependent approvals. All state is in PostgreSQL and every action goes to an append-only audit trail (`audit_events`).

### Backend modules
`main.py` (API + background steps) · `workflow.py` (statuses, roles, audit) · `ingest.py` (files, pages, package check) · `analysis.py` (capability + technical analysis) · `proposal.py` (review blockers, drafting, QA) · `export.py` (DOCX) · `llm.py` / `llm_mock.py` (OpenAI wrapper / offline mock) · `models_v2.py` (tables).

### Running without OpenAI credits
Start the backend with `LLM_MOCK=1` for canned AI output (demo/testing only - never for real bids).

## Database tables
Created automatically on startup: `opportunities`, `opp_files`, `file_pages`, `step_states`, `findings`, `rfis`, `capability_assessments`, `proposal_versions`, `approvals`, `audit_events`, `submissions`, plus `past_projects` (seed with `python seed_past_projects.py`). The older `analysis_runs`-based tables remain but are unused.

## Known limits
Real AI prompts need OpenAI credits to verify; no real login/SSO; no malware scan; scanned RFQ pages are not OCR-read; CAD/BIM files are reference only; DOCX export only; proposal template and capability data are placeholders until AB supplies real ones.
