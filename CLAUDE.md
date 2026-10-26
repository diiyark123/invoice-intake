# CLAUDE.md — instructions for Claude Code in this repo

## What this project is
AI Invoice Intake for Accounts Payable (fictional client: Meridian Supplies).
Invoices (PDF / scan / photo) → OCR + LLM extraction (Gemini by default, Claude optional) → normalize → ground to source → validate → duplicate check → confidence → auto-approve or human review.

**`PROJECT_SPEC.md` is the single source of truth.** Read it fully before writing code.
`docs/BUILD_PLAYBOOK.md` breaks each milestone into concrete steps and lists decisions already made.
`PROGRESS.md` records which milestone we are on — read it at the start of every session and update it at the end of each milestone.

## How to work with this user
- The user is learning. **Before coding a milestone, explain the plan in plain, simple language (short steps, a table, no jargon) and wait for a "go".**
- Build **one milestone at a time** (spec §13). Finish its acceptance checks and tests, then stop and give a short summary: what was built, what was verified, what is still pending.
- If the spec is ambiguous and the playbook's "Decisions" section doesn't settle it, **ask** — don't guess.
- Report results honestly. If an acceptance check couldn't be run, say so; don't mark it done.

## Non-negotiable rules (spec §2)
1. Only `app/services/approval.py` writes to `invoices` / `invoice_line_items`, and only after all checks pass or a logged-in user approves.
2. Every stored field value keeps: document id, page, source OCR text, bbox, model name, prompt version. Every human edit goes to `audit_log`.
3. Never lose an upload: errors set status `failed` + `error_message`; the file stays and Retry works.
4. Secrets only in env vars (`.env` is git-ignored). Never hardcode keys.
5. Money is `Decimal` in Python, `NUMERIC(14,2)` in Postgres. Never `float`.

## Conventions
- Python 3.11, type hints everywhere, Pydantic at API boundaries.
- `app/pipeline/` = small pure functions, testable without the database or the LLM.
- Tests never call a real LLM API (Gemini or Claude) — use a `FakeLLMProvider`.
- `data/test/` is the held-out test set: only `eval/run_eval.py` reads it. Tune using `data/dev/` only.
- Log each pipeline step with document id and duration.
- Format with `black`, lint with `ruff`.

## Commands
```bash
docker compose up -d --build                         # start db + api + ui
docker compose exec api alembic upgrade head          # apply migrations
docker compose exec api python -m app.seed            # seed users + vendors
docker compose exec api pytest -q                     # run tests
docker compose exec api python -m data.generator.generate --count 20 --out data/dev   # make fake invoices
docker compose exec api python -m eval.run_eval       # evaluation (M3+)
docker compose logs -f api                            # watch API logs
```
- API: http://localhost:8000/docs   UI: http://localhost:8501
- Without Docker (fallback): `python -m venv .venv`, `pip install -e ".[dev]"`, then set `DATABASE_URL` to a hosted Postgres and `TESSERACT_CMD` to the local tesseract path.

## Skill
`/next-milestone` — reads PROGRESS.md, explains the next milestone simply, builds it after approval, verifies, and updates PROGRESS.md.
