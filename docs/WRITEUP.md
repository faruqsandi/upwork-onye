# EHR Media Intelligence Platform: Technical Assessment Write-Up

**Candidate Assessment Submission:** Onye 2026 AI Full-Stack Intern Code Assessment  
**Applicant:** Faruq Sandi (`faruqsandi@gmail.com`)  
**Target Recipient:** Emmanuel (`eobasuyi@onyeone.com`)  
**Repository:** [github.com/faruqsandi/upwork-onye](https://github.com/faruqsandi/upwork-onye)  

---

## 1. Architectural Decisions & Tradeoffs

Here is my thinking behind the tech stack, focusing on practical tradeoffs over textbook dogma:

1. **Embedded SQLite vs. Postgres / MongoDB:**  
   *Decision:* Local SQLite with WAL mode.  
   *Why:* You shouldn't have to spin up Docker or configure a database just to test my submission. SQLite lives in the repo (`ehr_intelligence.db`), queries run in under 1ms, and WAL mode easily handles concurrent background writes.

2. **Local ChromaDB + MiniLM vs. Cloud Embeddings:**  
   *Decision:* Local ChromaDB with `all-MiniLM-L6-v2` running on CPU.  
   *Why:* Cloud vector DBs cost money and add network latency. More importantly, sending clinical notes to cloud APIs leaks Protected Health Information (PHI). Running locally keeps patient data private, costs nothing, and returns queries in sub-seconds.

3. **In-Process SQLite Queue vs. Celery / Redis:**  
   *Decision:* An async SQLite task queue driven by a background worker in FastAPI.  
   *Why:* Batch-processing 50–100 files at once causes HTTP timeouts if done synchronously. But Celery needs Redis and extra terminal workers, which is overkill here. My SQLite queue acknowledges uploads in <50ms, survives restarts, and indexes records progressively so you can search them right away.

4. **Vanilla JS & Tailwind vs. React / Next.js:**  
   *Decision:* Plain HTML5, ES6 JavaScript, and Tailwind CSS.  
   *Why:* I avoided a 300MB `node_modules` folder and fragile build scripts. Vanilla JS loads instantly, has zero build steps, and let me focus on what clinicians care about: fast search, clean patient drawers, and bookmarkable URLs.

---

## 2. Features Added Beyond Baseline Requirements & Why I Added Them

The assessment gave a solid baseline, but as I built and tested the system, I added a few practical features to make it feel like a real product:

1. **URL Sync & Deep Linking (`?q=...&patient=...`):**  
   *Why:* I wanted every search, filter, and open patient drawer to sync to the browser URL. You can bookmark it, refresh the page, or send the link to a colleague without losing your spot.

2. **Async Ingestion Queue & Progressive Indexing:**  
   *Why:* Embedding and summarizing dozens of records takes real CPU time. The async queue prevents UI freezes and HTTP timeouts, indexing records one by one so they show up in search immediately.

3. **Pre-Indexed Records & Segregated Test Data (`data/unprocessed/`):**  
   *Why:* I don't like cloning a repo only to wait minutes for batch jobs to finish before testing search. I pre-indexed 50 records so search works on first boot, and put 50 unindexed records in `data/unprocessed/` so you can test drag-and-drop ingestion right away.

4. **Resilient Patient Lookup & FHIR Reconstruction:**  
   *Why:* Real EHR IDs are messy—some are padded (`P-000261`), some aren't (`P-261`). A strict string match throws 404 errors. I built a fallback that normalizes digits and reconstructs the patient view straight from the SQLite FHIR bundle if the cache misses.

5. **HIPAA Safe Harbor De-Identification Toggle:**  
   *Why:* Clinicians often share screens during conferences or grand rounds. I added a quick "Hide Names & Details" toggle in the UI that masks names, MRNs, and birth dates on the fly without touching the underlying database.

6. **Query Keyword Highlighting (`<mark>`):**  
   *Why:* Scanning long medical notes is tiring. Highlighting search keywords directly in the result cards and drawer helps you spot why a record matched instantly.

7. **Clear Data Button (`POST /clear`):**  
   *Why:* I wanted an easy way to test the empty state and re-ingest data from scratch without manually deleting database files.

8. **Synthetic Clinical Data Generator (`data/llm_synthetic_generator.py`):**  
   *Why:* Real patient data is illegal to use here, but simple fake data is too clean. I built a generator using local LLMs to produce realistic, messy clinical records across JSON, CSV, and text notes.

9. **Local LLM Support:**  
   *Why:* Patient records shouldn't leave the premises. I added support for local models via LM Studio (like Gemma 3 or Llama 3.2) so summarization can run completely offline.

---

## 3. FHIR R4 & Clinical Concepts Researched

1. **Referential Linkage:**  
   Linked related resources with relative references (`DocumentReference.subject -> Patient/ID`, `DiagnosticReport.encounter -> Encounter/ID`) and verified schema rules with `fhir.resources`.
2. **DocumentReference vs. DiagnosticReport:**  
   Kept clinical notes and summaries in `DocumentReference`, while structured lab panels and impressions go into `DiagnosticReport`.
3. **LOINC Coding:**  
   Researched and used real LOINC codes (like `4548-4` for HbA1c, `10834-0` for Troponin, and `34108-1` for notes) so the test data mirrors real hospitals.
4. **Data Normalization & Audit Log:**  
   Cleaned inconsistent gender values (`"cis-male"`, `"M"`) into valid FHIR codes (`male`, `female`, `other`, `unknown`) and logged every edit in an audit trail.

---

## 4. AI Summary Validation & Safety Guardrails

1. **Structured 4-Part Output:**  
   Locked the prompt into four clear sections: Chief Concern, Key Diagnoses, Recent Media/Labs, and Flagged Anomalies.
2. **Word Count Bounds (<200 words):**  
   Enforced strict `<200 words` ceilings in prompt instructions and verified them with unit tests (`assert summary.word_count < 200`) across multiple clinical conditions.
3. **Smart SQLite Caching:**  
   Cached summaries by `(patient_id, SHA256(content))` in SQLite. Repeated requests take 0ms and cost zero tokens.
4. **Mandatory Clinical Disclaimer:**  
   Every summary shows a clear notice that it is AI-generated and must be verified by a licensed clinician.
5. **Local-First Provider Setup:**  
   Works out of the box with offline mock summaries, connects to local LLMs via LM Studio for privacy, or can use Claude/OpenAI if configured.

---

## 5. Future Improvements With More Time

1. **Better Pipeline & Task Orchestration:**  
   For a distributed production system, I'd replace the in-process SQLite queue with Temporal.io or River Queue for distributed retries and multi-node scaling.
2. **Dedicated FHIR Microservice:**  
   Under HIPAA rules, isolating patient PHI into its own dedicated FHIR service creates a clean security perimeter and makes compliance audits much easier.
3. **Layout-Aware Vision OCR:**  
   Real hospital records often arrive as scanned PDFs or faxes. I'd add a vision model (like DocTR) to extract text from scanned paper directly.
