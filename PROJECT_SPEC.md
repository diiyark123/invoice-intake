# PROJECT_SPEC.md — AI Invoice Intake for Accounts Payable

> **For the coding agent:** This file is the single source of truth for the project. Read it fully before writing code. Build one milestone at a time (Section 13), finish its acceptance criteria and tests, then stop and summarise what was done before starting the next. If something here is ambiguous, ask instead of guessing. Never break the rules in Section 2.

---

## 1. Project summary

A web app that takes vendor invoices (PDFs, scans, phone photos), extracts structured data with OCR + an LLM, validates it against business rules, scores confidence per field, and either auto-approves it or sends it to a human review queue. Approved invoices are stored in PostgreSQL with a full audit trail.

- **Client (simulated):** Meridian Supplies, a distributor receiving ~2,000 invoices/month from 150+ vendors.
- **Users:** AP clerks (upload, review) and an AP manager (dashboard, settings).
- **Builder:** one engineer, ~6 weeks, free/low-cost infrastructure.

---

## 2. Non-negotiable rules

1. **No unvalidated writes.** Nothing is written to the `invoices` or `invoice_line_items` tables unless it passed every validation check above the confidence threshold, or a logged-in user approved it. All other data lives in staging tables (`extractions`, `extracted_fields`).
2. **Traceability.** Every stored field value must record: source document id, page number, source OCR text, bounding box (if available), model name, and prompt version. Every human edit is written to `audit_log` with old value, new value, user and timestamp.
3. **Never lose an upload.** A failed step sets status `failed` with an error message; the file stays stored and can be retried.
4. **Secrets only in environment variables.** No API keys in code or in the repo.
5. **Money as Decimal.** Use `Decimal` in Python and `NUMERIC(14,2)` in PostgreSQL. Never `float` for amounts.

---

## 3. Tech stack (decided — do not substitute without asking)

| Layer | Choice |
| --- | --- |
| Language | Python 3.11 |
| Backend API | FastAPI + Uvicorn |
| ORM / migrations | SQLAlchemy 2.x + Alembic |
| Database | PostgreSQL 16 (Docker locally; free hosted tier in prod) |
| Frontend | Streamlit (multi-page app) calling the FastAPI backend |
| PDF handling | PyMuPDF (`fitz`) — text layer extraction + page rendering to images |
| Image pre-processing | OpenCV (`opencv-python-headless`) — deskew, denoise, contrast, blur check |
| OCR (word boxes) | Tesseract via `pytesseract` (`image_to_data` for word-level boxes) |
| Field extraction | Google Gemini API (default) or Anthropic Claude API, both vision + JSON output, behind a provider interface. Chosen by env var `LLM_PROVIDER` |
| Fuzzy matching | `rapidfuzz` |
| Auth | Users table with `bcrypt` hashed passwords; session token via FastAPI |
| Synthetic data | `Faker` + `reportlab` |
| Testing | `pytest` |
| Lint/format | `ruff` + `black` |
| Local infra | `docker-compose` (postgres + api + ui) |
| Hosting | Render / Railway / Fly.io (one container for API, one for UI) |
| File storage | Local `./storage` folder in dev; S3-compatible bucket in prod via a `Storage` interface |

---

## 4. Repository structure

```
invoice-intake/
├── PROJECT_SPEC.md
├── README.md
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── alembic/                     # migrations
├── app/
│   ├── main.py                  # FastAPI app factory
│   ├── config.py                # pydantic-settings, reads env vars
│   ├── db.py                    # engine, session
│   ├── models.py                # SQLAlchemy models (Section 6)
│   ├── schemas.py               # Pydantic request/response models
│   ├── auth.py                  # login, password hashing, role checks
│   ├── storage.py               # Storage interface: LocalStorage, S3Storage
│   ├── api/
│   │   ├── documents.py         # upload, list, retry
│   │   ├── review.py            # queue, get, correct, approve, reject
│   │   ├── dashboard.py         # metrics
│   │   └── settings.py          # threshold, vendors
│   ├── pipeline/
│   │   ├── orchestrator.py      # runs steps, sets statuses
│   │   ├── ingest.py            # file type detection, page rendering
│   │   ├── preprocess.py        # OpenCV cleanup + quality check
│   │   ├── ocr.py               # Tesseract words + boxes, or PDF text layer
│   │   ├── classify.py          # invoice / credit_note / multi_invoice / other
│   │   ├── extract.py           # LLM extraction
│   │   ├── llm/
│   │   │   ├── base.py          # LLMProvider interface
│   │   │   ├── gemini_provider.py      # default
│   │   │   ├── anthropic_provider.py   # alternative
│   │   │   └── factory.py       # picks the provider from LLM_PROVIDER
│   │   ├── prompts/             # versioned prompt files, e.g. extract_v1.txt
│   │   ├── grounding.py         # match values back to OCR words -> page, bbox, source_text
│   │   ├── normalize.py         # dates, amounts, invoice numbers, vendor names
│   │   ├── validate.py          # business rules (Section 8)
│   │   ├── duplicates.py        # duplicate detection (Section 9)
│   │   ├── confidence.py        # scoring (Section 10)
│   │   └── router.py            # auto-approve vs review decision
│   └── services/
│       ├── approval.py          # the ONLY code path that writes to invoices tables
│       └── audit.py
├── ui/
│   ├── Home.py                  # login
│   └── pages/
│       ├── 1_Upload.py
│       ├── 2_Review_Queue.py
│       ├── 3_Review_Invoice.py
│       ├── 4_Dashboard.py
│       └── 5_Settings.py
├── data/
│   ├── generator/               # synthetic invoice generator
│   ├── dev/                     # development invoices + labels
│   └── test/                    # held-out 50-invoice test set + labels (never used for tuning)
├── eval/
│   ├── run_eval.py              # runs pipeline on data/test, writes results
│   ├── metrics.py
│   └── report.ipynb             # charts for the evaluation report
├── docs/
│   ├── architecture.md
│   ├── clerk_guide.md
│   ├── admin_runbook.md
│   └── evaluation_report.md
└── tests/
```

---

## 5. Processing flow

```
Upload → store file → status=uploaded
  → ingest (detect type, split pages, render images)
  → preprocess + quality check   (fail → needs_review, reason=low_image_quality)
  → OCR (PDF text layer if present, else Tesseract) → words with boxes
  → classify document            (not a single invoice → needs_review, reason=<class>)
  → LLM extraction → raw JSON
  → normalize values
  → grounding (link each value to OCR words → page, bbox, source_text)
  → validate (Section 8) + duplicate check (Section 9)
  → confidence scoring (Section 10)
  → router:
        all checks pass AND every field ≥ threshold AND vendor known AND not duplicate
            → services/approval.py writes invoice → status=auto_approved
        otherwise → status=needs_review (with list of reasons)
Human review: correct fields → approve → services/approval.py → status=approved
                              → reject  → status=rejected (reason required)
Any exception → status=failed, error stored, Retry available
```

**Status values:** `uploaded`, `processing`, `failed`, `needs_review`, `auto_approved`, `approved`, `rejected`.

Processing runs as a FastAPI `BackgroundTasks` job (no queue system needed at this scale).

---

## 6. Data model

All tables have `id` (UUID, PK) and `created_at` (timestamptz). Amounts are `NUMERIC(14,2)`.

**users** — `email` (unique), `password_hash`, `role` (`clerk` | `manager`), `display_name`.

**vendors** — `name`, `normalized_name` (unique), `aliases` (text[]), `tax_id` (nullable), `is_active`.

**documents** — `filename`, `storage_key`, `mime_type`, `sha256`, `page_count`, `uploaded_by` (FK users), `status`, `review_reasons` (jsonb list), `error_message`, `processing_ms`, `updated_at`.

**extractions** (staging; one per processing run) — `document_id` (FK), `model_name`, `prompt_version`, `raw_llm_output` (jsonb), `doc_class`, `validation_results` (jsonb), `duplicate_of_invoice_id` (nullable FK invoices), `duplicate_of_document_id` (nullable FK documents; D2), `duplicate_score`, `overall_confidence`, `llm_input_tokens`, `llm_output_tokens`, `cost_usd` (NUMERIC(10,5)).

**extracted_fields** (staging) — `extraction_id` (FK), `field_name`, `value_text`, `normalized_value`, `confidence` (0–1), `page_number`, `bbox` (jsonb `{x0,y0,x1,y1}` in page pixel coords, nullable), `source_text`, `source_match` (0–1 grounding score; D17), `line_item_index` (nullable; null = header field).

**invoices** (final; written ONLY by `services/approval.py`) — `document_id` (FK, unique), `extraction_id` (FK), `vendor_id` (FK), `invoice_number`, `invoice_number_normalized`, `invoice_date`, `due_date`, `currency` (default `INR`/configurable; no conversion), `subtotal`, `tax`, `total`, `approval_type` (`auto` | `human`), `approved_by` (nullable FK users), `approved_at`.
Unique constraint: (`vendor_id`, `invoice_number_normalized`).

**invoice_line_items** — `invoice_id` (FK), `line_no`, `description`, `quantity` (NUMERIC(12,3)), `unit_price`, `amount`.

**audit_log** — `entity_type`, `entity_id`, `action` (`field_corrected`, `approved`, `rejected`, `auto_approved`, `retry`, `settings_changed`), `field_name`, `old_value`, `new_value`, `user_id` (nullable for system), `note`.

**settings** (single row) — `confidence_threshold` (default 0.85), `require_review_for_new_vendor` (default true), `amount_tolerance` (default 0.01), `max_due_days` (default 180).

---

## 7. Extraction

### Fields

Header: `vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `subtotal`, `tax`, `total`, `currency`.
Line items: `description`, `quantity`, `unit_price`, `amount`.

### LLM call

- Provider interface `LLMProvider.extract(images: list[bytes], ocr_text: str, prompt: str) -> dict` so the model can be swapped.
- Two implementations: `GeminiProvider` (default) and `AnthropicProvider`. `LLM_PROVIDER` (`gemini` | `anthropic`) picks one; the rest of the pipeline never knows which is in use.
- Model from env var `LLM_MODEL` (a Gemini model when `LLM_PROVIDER=gemini`, a Claude model when `anthropic`). Log provider, model name and token usage on every call.
- Send page images **and** the OCR text. Ask for JSON only, matching this schema:

```json
{
  "vendor_name": "string|null",
  "invoice_number": "string|null",
  "invoice_date": "YYYY-MM-DD|null",
  "due_date": "YYYY-MM-DD|null",
  "currency": "string|null",
  "subtotal": "string|null",
  "tax": "string|null",
  "total": "string|null",
  "line_items": [
    {"description": "string", "quantity": "string|null", "unit_price": "string|null", "amount": "string|null"}
  ]
}
```

- Amounts returned as strings and parsed to `Decimal` in `normalize.py`.
- Instruct the model to return `null` rather than guess, and to copy values exactly as printed.
- Strip code fences before `json.loads`; on parse failure retry once, then mark `failed`.
- Prompts live in `app/pipeline/prompts/extract_vN.txt`; the version string is stored on every extraction.

### Classification (`classify.py`)

One cheap LLM call (or the same call with an extra field) returning one of `invoice`, `credit_note`, `multi_invoice`, `delivery_note`, `other`. Anything except `invoice` → `needs_review` with reason.

### Normalization (`normalize.py`)

- Dates: parse common formats (DD/MM/YYYY, DD-Mon-YYYY, YYYY-MM-DD, etc.) with `dateutil`; prefer day-first; store ISO.
- Amounts: remove currency symbols and thousands separators; handle `1.234,56` vs `1,234.56`.
- Invoice number: uppercase, strip spaces and the prefixes `INV`, `INVOICE`, `NO`, `#`, and leading zeros → `invoice_number_normalized` (keep the original too).
- Vendor: lowercase, remove punctuation and suffixes (`pvt`, `ltd`, `llc`, `inc`, `co`), collapse spaces; match to `vendors` by exact normalized name, then aliases, then `rapidfuzz.token_sort_ratio ≥ 90`.

### Grounding (`grounding.py`)

For each extracted value, find the best matching span of consecutive OCR words (normalized comparison, `rapidfuzz.ratio`). Store `page_number`, merged `bbox`, `source_text`, and the match score (`source_match`, 0–1) used in confidence. No match → `bbox=null`, `source_match=0`.

---

## 8. Validation rules (`validate.py`)

Each rule returns `{rule, passed, message, fields}`. Tolerance = `settings.amount_tolerance`.

| Rule id | Check |
| --- | --- |
| `required_fields` | vendor_name, invoice_number, invoice_date, total are present |
| `line_items_sum` | Σ line amounts = subtotal (± tolerance). Skipped if no line items, flagged as warning |
| `line_math` | For each line with qty and unit price: qty × unit_price = amount (± tolerance) |
| `totals_math` | subtotal + tax = total (± tolerance) |
| `positive_amounts` | total > 0 (credit notes are classified separately) |
| `date_valid` | invoice_date parses and is not in the future and not older than 2 years |
| `due_after_invoice` | due_date ≥ invoice_date and ≤ invoice_date + `max_due_days` |
| `vendor_known` | vendor matched to `vendors` table |
| `not_duplicate` | Section 9 |

Any failed rule → `needs_review` with the rule id as a reason, and the related fields highlighted in the review screen.

---

## 9. Duplicate detection (`duplicates.py`)

Compare against `invoices` (approved) **and** documents currently in `needs_review` / `processing`.

1. **Exact file:** same `sha256` → duplicate.
2. **Strong match:** same vendor + same `invoice_number_normalized` → duplicate.
3. **Fuzzy match:** same vendor AND total equal AND invoice_date within ±3 days AND `rapidfuzz.ratio(invoice numbers) ≥ 85` → likely duplicate.
4. **Weak match:** different vendor match but same total + same date + invoice number ratio ≥ 90 → likely duplicate.

Any match → `needs_review`, reason `possible_duplicate`, with the matching record linked so the reviewer sees both side by side. Duplicates are **never** auto-approved. Target: catch 100% of seeded duplicates in the test set.

---

## 10. Confidence scoring (`confidence.py`)

Start with this explainable heuristic; tune it in Milestone 5 using dev data only.

For each field:

```
base         = source_match            # 0–1 from grounding
format_ok    = 1 if value parses for its type (date/amount/text) else 0
rule_penalty = 0.5 if the field is involved in a failed validation rule else 1
confidence   = base * (0.5 + 0.5 * format_ok) * rule_penalty
```

Missing required field → confidence 0.
`overall_confidence` = minimum confidence across header fields.

**Router auto-approves only if:** every validation rule passes, not a duplicate, vendor is known (or `require_review_for_new_vendor` is false), and every header field confidence ≥ `settings.confidence_threshold`.

---

## 11. API endpoints (FastAPI)

All except `/auth/login` require a session token. Manager-only routes are marked (M).

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/login` | Email + password → token |
| POST | `/documents` | Upload one or more files (PDF, JPG, PNG; max 15 MB each); starts processing |
| GET | `/documents` | List with filters: status, date range, vendor |
| GET | `/documents/{id}` | Status, reasons, extraction, fields |
| GET | `/documents/{id}/pages/{n}` | Rendered page image |
| POST | `/documents/{id}/retry` | Re-run pipeline for failed docs |
| GET | `/review/queue` | `needs_review` documents, oldest first |
| PATCH | `/review/{document_id}/fields` | Correct field values (writes audit_log) |
| POST | `/review/{document_id}/approve` | Re-run validation on corrected values; if checks pass (duplicates may be overridden with a note) → approval service |
| POST | `/review/{document_id}/reject` | Reject with reason |
| GET | `/dashboard/metrics` (M) | See Section 12 |
| GET/PUT | `/settings` (M) | Threshold and rule settings |
| GET/POST/PUT | `/vendors` (M) | Manage vendor list |

---

## 12. UI screens (Streamlit)

Design for non-technical users: plain labels, no jargon, clear status colours (green approved, amber needs review, red failed).

1. **Login.**
2. **Upload.** Drag-and-drop multiple files; table of recent uploads with live status; Retry button on failed rows.
3. **Review queue.** Table: vendor, invoice number, total, reasons, age. Click to open.
4. **Review invoice.** Left: page image with bounding boxes drawn (PIL) around each field's source; selected field highlighted. Right: editable form of header fields + line items table, each field showing a confidence badge and any failed rule message. Buttons: Approve, Reject (reason required). Duplicate case shows the matching invoice side by side.
5. **Dashboard (manager).** Invoices processed (today / this week / this month), auto-approval rate, review queue size and oldest item age, failure count, average processing time, corrections per field (which fields humans fix most), estimated LLM cost per invoice and monthly projection.
6. **Settings (manager).** Confidence threshold slider, rule toggles/tolerances, vendor list editor. Changes logged to `audit_log`.

---

## 13. Milestones and acceptance criteria

Work through these in order. Each milestone ends with passing tests and a short summary.

### M1 — Project skeleton and dataset (Week 1)
- Repo structure, `docker-compose` (postgres, api, ui), `.env.example`, Alembic initial migration with all Section 6 tables, seed script for 2 users and 15 vendors.
- Synthetic generator in `data/generator/`: ≥ 5 visually different layouts, random vendors/line items/tax, outputs PDF + matching label JSON. Option to rasterise with noise, rotation and blur to mimic scans.
- Label format identical to the extraction schema in Section 7.
- `data/test/`: 50 invoices (≈25 synthetic, ≈15 public-dataset hand-labelled, ≈10 phone photos), including **5 seeded duplicates** listed in `data/test/duplicates.json`.
- **Accept:** `docker compose up` runs; migrations apply; generator produces 20 invoices with labels.

### M2 — Extraction pipeline (Week 2)
- `ingest`, `preprocess`, `ocr`, `classify`, `extract`, `normalize`, `grounding`; orchestrator sets statuses; failures captured.
- Upload endpoint + background processing; results stored in staging tables.
- **Accept:** uploading a dev invoice produces an `extractions` row and `extracted_fields` rows with page + source_text; unit tests for normalize and grounding.

### M3 — Validation, duplicates, confidence, routing + baseline eval (Week 3)
- Sections 8, 9, 10; `router.py`; `services/approval.py` as the single writer to `invoices`.
- `eval/run_eval.py`: runs the full pipeline on `data/test/`, outputs per-field accuracy, overall field accuracy, auto-approval rate, wrong-fields-in-auto-approved rate, duplicates caught, avg processing time, cost per invoice → `eval/results/<timestamp>.json`.
- Field is "correct" if normalized extracted value equals normalized label (amounts exact to 2 dp; text via case-insensitive exact match after normalization).
- **Accept:** unit tests for every validation rule and duplicate case; a test proves `invoices` cannot be written outside `approval.py`; **baseline eval results saved** (do not tune on test set).

### M4 — Review UI and audit (Week 4)
- Login, Upload, Review queue, Review invoice screens; corrections, approve, reject; audit log entries.
- **Accept:** a clerk can fix a flagged invoice and approve it in under 2 minutes; every edit appears in `audit_log`.

### M5 — Iteration, dashboard, settings (Week 5)
- Analyse baseline errors on **dev data** (not test); improve prompts (new version file), normalization, grounding, scoring.
- Dashboard and Settings screens.
- Threshold sweep in eval: auto-approval rate and error rate at thresholds 0.6–0.95 (step 0.05).
- **Accept:** second eval run saved; targets in Section 14 checked and reported honestly whether met or not.

### M6 — Deploy and document (Week 6)
- Deploy API + UI + database; demo login (clerk and manager) in README.
- `docs/`: architecture (with diagram), clerk guide (1 page), admin runbook, evaluation report (before/after table + threshold chart + cost), design trade-offs, next steps.
- **Accept:** deployed URL works end to end on a fresh invoice; README lets someone else run it locally in < 10 minutes.

---

## 14. Success metrics (measured on `data/test/`)

| Metric | Target |
| --- | --- |
| Field-level extraction accuracy | ≥ 90% |
| Invoices auto-approved with no human edits | ≥ 70% |
| Wrong fields among auto-approved invoices | ≤ 1% |
| Seeded duplicates caught | 5 / 5 |
| Handling time, auto-approved invoice | < 1 min |
| Handling time, reviewed invoice | < 2 min |
| Extraction cost per invoice | Reported + monthly projection for 2,000 invoices |

Baseline manual entry time is measured by hand (time 10 manual entries) and recorded in the evaluation report.

---

## 15. Environment variables (`.env.example`)

```
DATABASE_URL=postgresql+psycopg://invoice:invoice@db:5432/invoice
LLM_PROVIDER=gemini           # gemini | anthropic
GEMINI_API_KEY=
ANTHROPIC_API_KEY=            # only needed when LLM_PROVIDER=anthropic
LLM_MODEL=gemini-3.5-flash-lite
LLM_MAX_TOKENS=8000
STORAGE_BACKEND=local          # local | s3
STORAGE_LOCAL_PATH=./storage
S3_ENDPOINT_URL=
S3_BUCKET=
S3_ACCESS_KEY=
S3_SECRET_KEY=
SESSION_SECRET=
API_BASE_URL=http://api:8000
TESSERACT_CMD=/usr/bin/tesseract
```

---

## 16. Coding conventions

- Type hints everywhere; Pydantic models at API boundaries.
- Small pure functions in `pipeline/` so they are unit-testable without the database or the LLM.
- Mock the LLM provider in tests; never call the real API from `pytest`.
- Log each pipeline step with document id and duration.
- Keep the test set untouched during development; only `eval/run_eval.py` reads it.

---

## 17. Out of scope

Payment processing, ERP integration, purchase order matching, multi-currency conversion, automatic email ingestion, auto-splitting of multi-invoice files (stretch goal only), real client data.
