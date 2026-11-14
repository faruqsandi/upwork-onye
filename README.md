# EHR Media Intelligence Platform

> **Clinical EHR Media Ingestion, HL7 FHIR R4 Normalization, AI Summarization & Semantic Search**  
> *Assessment Submission for the Onye 2026 AI Full-Stack Intern Code Assessment.*

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com)
[![HL7 FHIR R4](https://img.shields.io/badge/HL7_FHIR-R4_Compliant-orange.svg)](https://hl7.org/fhir/R4/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v3.0-38bdf8.svg)](https://tailwindcss.com)
[![Tests Passing](https://img.shields.io/badge/pytest-48%20passed-success.svg)](tests/)

---

## 1. Overview

Doctors and clinical staff lose hours every week digging through unstructured EHR notes—consultation CSVs, scanned PDFs, discharge summaries, and lab reports that live outside structured fields.

I built this platform to solve that problem. It ingests messy clinical files, converts them into standard HL7 FHIR R4 bundles, generates AI summaries under 200 words, and lets clinicians search everything in sub-seconds.

- **Messy File Ingestion & Cleaning:** Normalizes messy JSON dumps, CSV notes, and pathology texts with an immutable audit log.
- **HL7 FHIR R4 Bundles:** Maps cleaned records into validated `Patient`, `Encounter`, `DocumentReference`, and `DiagnosticReport` resources.
- **AI Clinical Summaries:** Produces structured 4-part summaries under 200 words, backed by SHA-256 caching (0ms repeated queries) and clinical disclaimers.
- **Semantic Vector Search:** Natural language search powered by local `all-MiniLM-L6-v2` embeddings and ChromaDB.
- **Clinician Dashboard:** Responsive UI with debounced search, patient detail drawers, URL bookmarking, and a HIPAA de-identification toggle.

For my detailed write-up covering architectural decisions, FHIR research, and AI validation, see [`docs/WRITEUP.md`](docs/WRITEUP.md).

---

## 2. Quickstart Guide

I designed setup to be completely friction-free. You don't need Docker, external database servers, or paid API keys. Everything runs locally on Python 3.11+.

### Step 1: Clone & Setup Environment

```bash
git clone https://github.com/faruqsandi/upwork-onye.git
cd upwork-onye

# Using uv (recommended)
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e .

# Or using standard pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Start the Platform

```bash
python run.py
# Or via uvicorn directly:
# uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser to:
- **Clinician Dashboard:** [http://localhost:8000](http://localhost:8000)
- **API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)

> **Zero Cold-Start:** I already pre-indexed 50 clinical records (`data/raw/p-200.*` to `p-249.*`) into the committed SQLite (`ehr_intelligence.db`) and ChromaDB (`chroma_data/`) stores (~1.6MB total). You can search and inspect records immediately without running an ingestion batch first.

---

## 3. Key Platform Features

- **Multi-Format Ingestion:** Ingests JSON exports, CSV notes, and raw text files. Sanitizes dirty MRNs, non-standard gender codes, and messy dates, recording every fix in an audit trail.
- **HL7 FHIR R4 Compliance:** Validates resources with `fhir.resources` and saves referentially intact collection bundles to SQLite.
- **Clinical AI Summarization:** Enforces prompt rules to keep summaries under 200 words across four structured sections. Supports local LLMs via LM Studio, offline rule-based mocks, or cloud APIs.
- **Semantic Vector Search:** Indexes notes and findings using `all-MiniLM-L6-v2` embeddings in ChromaDB, with metadata filtering by date and resource type.
- **Clinician Dashboard (Tailwind CSS):**
  - **URL Parameter Sync & Bookmarking:** Deep-linking (`?q=...&patient=...&anonymize=true`) with browser history navigation.
  - **HIPAA De-Identification Mode:** Instant toggle masking names, MRNs, and birth dates on screen for safe case presentations.
  - **Query Highlighting:** Visual `<mark>` chips highlight search terms in cards and clinical text.
  - **Drag-and-Drop Uploads:** Drop files directly into the UI dropzone for background processing.
- **Async Ingestion Queue:** A background SQLite worker processes uploads without freezing the UI (<50ms API response), indexing records progressively into ChromaDB.
- **Synthetic Data Generator (`data/llm_synthetic_generator.py`):** CLI tool using local LLMs to generate realistic, messy clinical test files across JSON, CSV, and TXT without touching real patient data.

---

## 4. Repository Structure

```text
onye-ehr-intelligence/
├── data/
│   ├── raw/                           # 50 Pre-indexed EHR sources (p-200 to p-249: JSON, CSV, TXT)
│   ├── unprocessed/                   # 50 Unprocessed test files (p-250 to p-299: JSON, CSV, TXT)
│   └── llm_synthetic_generator.py     # LLM synthetic EHR generator (JSON, CSV, TXT)
├── ehr_intelligence.db                # Pre-indexed SQLite DB (FHIR bundles, cache, queue) ~600KB
├── chroma_data/                       # Pre-indexed ChromaDB vector store embeddings ~1.5MB
├── src/
│   ├── config.py                      # Application settings (defaults to local/mock provider)
│   ├── ingestion/                     # Parsers, DataCleaner & Audit Trail
│   ├── fhir/                          # HL7 FHIR R4 mapping, validation & storage
│   ├── ai/                            # Clinical AI summarizer, prompt schemas & SHA-256 cache
│   ├── search/                        # SentenceTransformer embeddings & ChromaDB vector store
│   ├── queue/                         # Asynchronous SQLite queue manager & background worker
│   ├── api/                           # FastAPI REST routes and schemas
│   └── static/                        # Clinician Dashboard Frontend (Tailwind CSS, Vanilla ES6+)
│       ├── index.html                 # Search interface, dropzone, and detail drawer
│       ├── css/style.css              # Custom styling & query highlight chips
│       └── js/app.js                  # Search controller, URL router & queue poller
├── tests/                             # Comprehensive Automated Test Suite (48 Tests)
├── docs/
│   ├── WRITEUP.md                     # Technical assessment write-up (tradeoffs, design, clinical research)
│   └── ASSESSMENT_EXECUTION_PLAN.md   # Internal execution plan and milestones
├── run.py                             # Single-command server runner
├── pyproject.toml                     # Modern Python packaging specification
├── requirements.txt                   # Frozen dependencies
└── README.md
```

---

## 5. Running the Automated Test Suite

I wrote 48 automated tests covering every component of the platform. All tests run locally with `pytest` without needing external network access or paid API keys:

```bash
# Run the complete test suite (48 tests)
pytest -v

# Run with execution times
pytest -v --durations=5

# Run specifically the headless Playwright browser tests
pytest tests/test_playwright_frontend.py -v
```

### Test Coverage Breakdown:
- **`tests/test_ingestion.py`:** Tests messy date formats, dirty MRNs, gender normalization, duplicate merging, and unprocessed files.
- **`tests/test_fhir_mapping.py`:** Validates resources and collection bundles against HL7 FHIR R4 schema rules.
- **`tests/test_summarizer.py`:** Tests the `<200 words` ceiling, 4 clinical sections, safety disclaimers, and SHA-256 caching.
- **`tests/test_search.py`:** Tests semantic search accuracy, sub-2s latency, and metadata filtering.
- **`tests/test_queue.py`:** Tests queue persistence, deduplication, state transitions, and background worker processing.
- **`tests/test_ui.py`:** Tests static routes, patient listings, bundle endpoints, and data clearing.
- **`tests/test_playwright_frontend.py`:** Headless browser automation testing search input, keyword highlighting, drawer inspection, anonymization toggle, and URL deep-linking.
- **`tests/test_e2e_local_llm.py`:** Integration test verifying summarization against local LLMs.

---

## 6. REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `POST /search` | `POST` | Semantic search across indexed records with top matches and relevance scores. |
| `GET /patients` | `GET` | List all normalized patients with summary snippets and badges. |
| `GET /patients/{id}` | `GET` | Patient detail dossier with AI summary, linked records, and cleaning audit log. |
| `GET /bundles/{id}` | `GET` | Retrieve official HL7 FHIR R4 Bundle JSON. |
| `POST /ingest` | `POST` | Enqueues directory records into the SQLite ingestion queue for background processing. |
| `POST /upload` | `POST` | Multi-file drag-and-drop upload into the ingestion queue. |
| `POST /clear` | `POST` | Purges all FHIR bundles, vector embeddings, summary caches, and queue states. |
| `GET /queue/status` | `GET` | Real-time queue progress (pending, processing, successful, failed, duplicates). |
| `GET /health` | `GET` | System health status, bundle count, queue telemetry, and indexed vector counts. |

---

## 7. Submission & Assessment Notes

- **Technical Assessment Write-Up:** Available in markdown at [`docs/WRITEUP.md`](docs/WRITEUP.md).
- **Testing Ingestion:** I placed 50 unindexed records in `data/unprocessed/` (`p-250` to `p-299`) so you can test drag-and-drop batch uploads and deduplication.
- **Resetting State:** Click the red **"Clear Data"** button in the dashboard or call `POST /clear` to wipe everything and test the empty state.
- **Submission Recipient:** Emmanuel (`eobasuyi@onyeone.com`).
