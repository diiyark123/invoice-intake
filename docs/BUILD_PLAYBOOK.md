# Build playbook

A companion to `PROJECT_SPEC.md`. The spec says **what** to build; this file says **in what order**, and records the **decisions** that fill gaps in the spec.
Each milestone section ends with a "Done when" checklist and a prompt you can paste into Claude.

---

## Decisions (gaps in the spec, settled up front)

Items marked **(confirm)** change something in the spec. Claude should confirm these with the user at the start of the milestone that needs them.

| # | Topic | Decision |
|---|---|---|
| D1 | Login tokens | Signed tokens using `itsdangerous.URLSafeTimedSerializer(SESSION_SECRET)`, holding the user id and role, valid for 8 hours. No sessions table. Sent as `Authorization: Bearer <token>`. Streamlit keeps the token in `st.session_state`. |
| D2 | Linking duplicates to un-approved documents (confirmed with user 2026-10-26) | The spec's `extractions.duplicate_of_invoice_id` can only point at approved invoices, but §9 also compares against documents still in review. Add a nullable `extractions.duplicate_of_document_id` (FK documents). |
| D3 | Classification | Done in the **same** LLM call: add a `doc_class` field to the JSON. This is cheaper and the spec allows it. |
| D4 | Page coordinates | Render every page at **200 DPI**. All bounding boxes are in those pixel coordinates. PDF text-layer words come in points, so convert with `× 200/72`. |
| D5 | Text layer vs OCR | Use the PDF text layer if the page has ≥ 20 words from `page.get_text("words")`. Otherwise run Tesseract on the preprocessed image. |
| D6 | Image quality check | Use the variance of the Laplacian as a blur score. Below a threshold (tune it on dev data, starting at 100) → `needs_review`, reason `low_image_quality`. Processing **still continues**, so the reviewer gets pre-filled values. |
| D7 | Grounding typed values | Match amounts and dates on their **normalized** values: normalize candidate OCR spans and compare. Exact normalized match = 1.0; otherwise use `rapidfuzz.ratio/100` on text. Try spans of 1–6 consecutive words on the same line. |
| D8 | Background jobs | The orchestrator opens its **own** DB session; it never reuses the request's session. Retry creates a new `extractions` row; old rows are kept for history. |
| D9 | "Only approval.py writes invoices" test | (a) A static test that scans `app/` for `Invoice(`, `InvoiceLineItem(` and `insert(Invoice` and fails if any appear outside `app/services/approval.py` or `app/models.py`. (b) A unit test showing `approve()` refuses an extraction with a failed rule unless a user approves it. |
| D10 | Cost tracking | `cost_usd = input_tokens × in_price + output_tokens × out_price`. Prices go in a dict in `app/config.py`, keyed by model. **Look up current prices when building M2**; don't type them from memory. |
| D16 | LLM provider (confirmed with user 2026-10-26) | Gemini is the default provider; Claude is kept as an alternative. `LLM_PROVIDER=gemini\|anthropic` in `.env` picks one via `pipeline/llm/factory.py`. Build both in M2 behind the same `LLMProvider` interface. **Look up current Gemini and Claude model names and prices when building M2.** |
| D17 | Storing the grounding score | §7 grounding produces `source_match`, but §6 had no column for it. Added `extracted_fields.source_match` (float, nullable) so M3 can compute confidence and recompute it after edits. |
| D18 | Default models (looked up 2026-10-26) | Gemini: `gemini-3.5-flash-lite` (Google's recommended low-cost model, $0.30 / $2.50 per 1M tokens). Claude backup: `claude-opus-5-5`; set `LLM_MODEL=claude-haiku-5-5` for a cheaper Claude. `LLM_MAX_TOKENS` raised to 8000 because thinking tokens count against it. |
| D19 | Unknown vendor at approval (confirmed with user 2026-10-27) | If `require_review_for_new_vendor` is off (or a human approves), `approval.py` adds the vendor from the invoice's name and writes an audit row with the new action `vendor_created`. When the setting is off, `vendor_known` is downgraded to a warning so it doesn't lower the vendor name's confidence either. |
| D20 | Warnings | `line_items_sum` with no line items is a *warning*: shown to the reviewer, but it doesn't block auto-approval or lower confidence. Every other failed rule is an error. |
| D21 | Blank optional fields | A header field that is legitimately absent (e.g. no due date printed) gets no confidence and is left out of `overall_confidence`. A missing *required* field still scores 0. |
| D22 | Currency grounding | `INR` grounds against printed `Rs.`, `₹` or `(INR)` (`normalize_currency`), otherwise those layouts could never reach full confidence. |
| D23 | Review edits (confirmed with user 2026-10-27) | Reviewers can edit, add and delete line items; each change is a `field_corrected` audit row (deleted line → `line_items.N`, old values in `old_value`). After every save all checks re-run, so reasons update immediately. A typed value gets `source_match` 1.0. A duplicate can be overridden with a note, but never when the same vendor + invoice number is already booked (`already_recorded`). |
| D24 | M5 tuning (dev data only, 2026-10-27) | Default prompt `extract_v2` (v1 kept). Grounding compares dates/amounts with their printed forms. `normalize_currency` ignores commas. Blur threshold 100 → 40. Gemini provider retries 429/5xx up to 3 times using Google's suggested wait (free tier: 15 requests/min). Evidence in `eval/results/M5_targets.md`. |
| D11 | Accuracy definition | Report header fields (8) and line-item fields separately. Line items are matched by position (index). Headline "field-level accuracy" = header + line-item fields combined; also show header-only. |
| D12 | "Today" in tests | Date rules depend on today's date. Tests pass a fixed `today`; validation functions take `today` as a parameter. The generator makes invoice dates within the last ~12 months, relative to the run date. |
| D13 | Eval database | `eval/run_eval.py` uses a separate database (`invoice_eval`). It is wiped, migrated and seeded on each run. Files are processed in a fixed order (originals before their seeded duplicates) so duplicate detection works. |
| D14 | Test-set vendors | Every vendor in `data/test/` exists in the seed data, **except** 2–3 on purpose, to exercise the `vendor_known` rule. |
| D15 | Currency | Default `INR`, stored as given; no conversion (out of scope). |

---

## M1 — Skeleton + dataset

**Goal:** an empty but runnable app with all tables, seed data, and a fake-invoice generator.

| Step | Files | Notes |
|---|---|---|
| 1 | `app/config.py`, `app/db.py`, `app/main.py` | `pydantic-settings` reads `.env`. `main.py` has only `/health` for now |
| 2 | `app/models.py` | All §6 tables, plus D2's column if confirmed. UUID PKs, `created_at` with a server default. `Numeric(14,2)` for money. Postgres `ARRAY(Text)` for aliases, `JSONB` for JSON fields. Unique (vendor_id, invoice_number_normalized) |
| 3 | `alembic/`, `alembic.ini` | `alembic init`; `env.py` reads `DATABASE_URL` from settings and `target_metadata = Base.metadata`. Autogenerate the first migration, **then read it** before applying |
| 4 | `app/seed.py` | Clerk `clerk@meridian.test` and manager `manager@meridian.test` (demo passwords in README only), 15 vendors with aliases, and the settings row. Safe to run twice (idempotent) |
| 5 | `data/generator/` | `layouts.py` (≥ 5 reportlab layouts: classic table, modern minimal, two-column header, tax-heavy (GST-style CGST/SGST), compact/thermal-like), `generate.py` (CLI: `--count`, `--out`, `--scan`, `--seed`), `scanify.py` (render to image → rotate ±3°, noise, blur, JPEG) |
| 6 | Labels | One `<name>.json` per invoice, exactly in the §7 schema, plus a `doc_class` field (D3). Amounts as strings with 2 decimals, dates ISO. Totals must add up exactly, using Decimal |
| 7 | `data/test/` | ~25 synthetic now (mix of clean and scanned), with 5 seeded duplicates covering: exact copy, same number + different file, number variant (`INV-0042` vs `42`), rescanned copy, date ±2 days. `duplicates.json` = `[{"file","duplicate_of","kind"}]`. Real samples and photos are added later |
| 8 | `tests/` | Test the generator (labels valid, totals consistent, deterministic with `--seed`), models import, seed idempotency |

**Done when:**
- [ ] `docker compose up -d --build` runs; `/health` returns OK; the UI placeholder loads
- [ ] `alembic upgrade head` creates every table (check with `\dt` in psql)
- [ ] The seed script runs twice without errors
- [ ] `python -m data.generator.generate --count 20 --out data/dev` produces 20 PDFs + 20 labels
- [ ] `pytest` passes

**Prompt:** `/next-milestone` (or: "Start M1 following docs/BUILD_PLAYBOOK.md. Explain first, then wait.")

---

## M2 — Extraction pipeline

**Goal:** upload a file → it is processed in the background → the staging tables are filled, with source locations.

| Step | Files | Notes |
|---|---|---|
| 1 | `app/storage.py` | `Storage` protocol: `save(bytes, key)`, `load(key)`, `exists`. `LocalStorage` now; `S3Storage` stub (boto3) |
| 2 | `app/auth.py`, `api/auth` route | bcrypt + D1 tokens; `require_user`, `require_manager` dependencies |
| 3 | `pipeline/ingest.py` | Detect type from magic bytes (not the file extension). PDF → pages at 200 DPI (PyMuPDF). Image → one page, EXIF-rotated |
| 4 | `pipeline/preprocess.py` | Grayscale, deskew, denoise, CLAHE contrast, blur score (D6) |
| 5 | `pipeline/ocr.py` | Returns `list[Word(text, page, x0,y0,x1,y1, line_id, conf)]`. Uses the text layer or Tesseract (D5) |
| 6 | `pipeline/llm/base.py`, `gemini_provider.py`, `anthropic_provider.py`, `factory.py` (D16), `FakeLLMProvider` (in tests) | `extract(images, ocr_text, prompt) -> LLMResult(data, input_tokens, output_tokens, model)` |
| 7 | `pipeline/prompts/extract_v1.txt`, `pipeline/extract.py` | Prompt: JSON only, `null` instead of guessing, copy values exactly as printed. Strip code fences → `json.loads` → retry once → otherwise fail |
| 8 | `pipeline/normalize.py` | Dates, amounts, invoice numbers, vendor matching (§7) |
| 9 | `pipeline/grounding.py` | D7 |
| 10 | `pipeline/orchestrator.py` | Runs the steps, timing each one; writes `extractions` + `extracted_fields`; any exception → `failed` + `error_message` |
| 11 | `api/documents.py` | `POST /documents` (multi-file, 15 MB limit, sha256), list, get, page image, retry |

**Tests:** normalize (many date and amount formats, including `1.234,56`, `₹ 1,23,456.00`, `12-Mar-2026`); invoice number normalization; vendor matching; grounding against a hand-built word list; orchestrator with `FakeLLMProvider` (success, bad JSON → retry → fail, exception → `failed`).

**Done when:**
- [ ] Uploading a dev invoice through `/docs` produces 1 `extractions` row and N `extracted_fields` rows, with `page_number` and `source_text` filled
- [ ] A broken file ends as `failed`, and Retry works
- [ ] Model name, prompt version, tokens and cost are stored
- [ ] `pytest` passes, with no real API calls

---

## M3 — Validation, duplicates, confidence, routing + baseline eval

| Step | Files | Notes |
|---|---|---|
| 1 | `pipeline/validate.py` | One pure function per rule (§8) → `RuleResult(rule, passed, message, fields, severity)`. `line_items_sum` with no lines = warning |
| 2 | `pipeline/duplicates.py` | The 4 checks of §9. A pure function takes the candidate plus a list of existing records; the DB query lives in the orchestrator |
| 3 | `pipeline/confidence.py` | The §10 formula, exactly as written; header minimum = overall |
| 4 | `pipeline/router.py` | Returns `(decision, reasons)` |
| 5 | `services/approval.py`, `services/audit.py` | The single writer. Re-checks the rules itself (doesn't trust the caller). Writes the invoice + lines + audit row in one transaction |
| 6 | `eval/metrics.py`, `eval/run_eval.py` | D11, D13. Output to `eval/results/<timestamp>.json` with every §14 metric that can be computed |

**Tests:** pass and fail for every rule; every duplicate kind, plus a near-miss that must **not** match; confidence edge cases; router; D9.

**Done when:**
- [ ] All the tests above pass
- [ ] A **baseline eval** run is saved in `eval/results/` and committed. **Don't change anything because of test-set results.**

---

## M4 — Review UI + audit

| Step | Files | Notes |
|---|---|---|
| 1 | `api/review.py` | Queue (oldest first), PATCH fields (audit each change), approve (re-validate; duplicate override needs a note), reject (reason required) |
| 2 | `ui/api_client.py` | Small wrapper around `requests`, adds the token |
| 3 | `ui/Home.py` | Login; redirect by role |
| 4 | `ui/pages/1_Upload.py` | Multi-file uploader; recent-uploads table with coloured status; Retry; auto-refresh every few seconds while anything is `processing` |
| 5 | `ui/pages/2_Review_Queue.py` | Vendor, invoice number, total, reasons (in plain words, not rule ids), age |
| 6 | `ui/pages/3_Review_Invoice.py` | Left: page image with PIL-drawn boxes; selected field in a stronger colour. Right: form with confidence badges (green ≥ threshold, amber, red), rule messages, editable line-items table (`st.data_editor`), Approve / Reject. Duplicate case: both invoices side by side |

Plain-language reason labels, e.g. `totals_math` → "Subtotal + tax doesn't equal total".

**Done when:**
- [ ] A clerk can open a flagged invoice, fix it and approve it in under 2 minutes (time it)
- [ ] Every edit, approval and rejection appears in `audit_log`
- [ ] A clerk cannot open the manager pages or routes

---

## M5 — Iteration, dashboard, settings

1. Run the pipeline on `data/dev/` and list the errors by field and cause. Fix the biggest causes: `extract_v2.txt` prompt, normalization edge cases, grounding, confidence weights. **Use dev data only.**
2. `api/dashboard.py` + `ui/pages/4_Dashboard.py`: every metric in §12.
3. `api/settings.py` + `ui/pages/5_Settings.py`: threshold slider, tolerances, toggles, vendor editor. Every change is audited.
4. Threshold sweep in `run_eval.py` (0.60 → 0.95, step 0.05): auto-approval rate and error rate for each threshold.

**Done when:**
- [ ] A second eval run is saved
- [ ] A §14 targets table is filled in honestly, met or not, with the reason for any miss

---

## M6 — Deploy + docs

1. Deploy: a Postgres instance (check current free-tier limits; Neon and Supabase are alternatives to the host's own), plus 2 services from the same Dockerfile (API, UI), with S3-compatible storage (e.g. Cloudflare R2 / Backblaze B2) via `S3Storage`.
2. Run migrations and the seed in prod; demo logins in README.
3. Docs: `architecture.md` (Mermaid diagram), `clerk_guide.md` (1 page, screenshots), `admin_runbook.md` (deploy, rotate keys, change threshold, retry failed docs, back up the DB), `evaluation_report.md` (before/after table, threshold chart, cost per invoice + projection for 2,000/month, manual-entry baseline, design trade-offs, next steps).
4. README: run locally in < 10 minutes.

**Done when:**
- [ ] A fresh invoice uploaded to the deployed URL goes all the way to approved
- [ ] Someone else can follow the README and run it locally

---

## Before you start: things to gather
- Gemini API key in `.env` as `GEMINI_API_KEY` (needed from M2) — ✅ done. Anthropic key optional, only to try Claude
- ~15 public sample invoices: search Kaggle or Hugging Face for invoice datasets and **check the licence**. Label them by hand in the §7 JSON format
- ~10 phone photos of printed synthetic invoices (different angles and lighting)
- Timings for 10 manual entries (the baseline for the report)
