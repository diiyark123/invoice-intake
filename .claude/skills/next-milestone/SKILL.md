---
name: next-milestone
description: Build the next milestone of the invoice-intake project. Reads PROGRESS.md, explains the milestone in plain language, waits for approval, builds it, runs its acceptance checks and tests, then updates PROGRESS.md. Use when the user says "next milestone", "continue the build", "start M1/M2/..." or similar.
---

# Next milestone

Follow these steps in order. Don't skip the explanation step.

## 1. Find where we are
- Read `PROGRESS.md`, then `PROJECT_SPEC.md` (the milestone in §13 plus the sections it refers to), then that milestone's section in `docs/BUILD_PLAYBOOK.md`.
- If the user named a specific milestone, use that one. Otherwise take the first one not marked ✅.
- Check that the previous milestone really works: run `pytest -q`. If it fails, tell the user and fix that first.

## 2. Explain before building
Give a short, plain-language plan:
- One sentence on what this milestone achieves.
- A table: step | file(s) | what it does in simple words.
- What "done" means: the acceptance checks, in simple words.
- Anything the user must provide (API key, sample invoices, a decision).

Then **stop and wait for the user to say go.** If something is ambiguous and the playbook's "Decisions" section doesn't settle it, ask now.

## 3. Build
- Follow the playbook's step order. Keep `app/pipeline/` functions pure and small.
- Write the tests listed for this milestone alongside the code.
- Respect the five rules in CLAUDE.md (approval.py is the only writer, traceability, never lose uploads, no secrets, Decimal money).

## 4. Verify
- Run `pytest -q` and every acceptance check for the milestone (spec §13). Show the real output.
- If a check can't run (for example, no API key yet), say exactly which one and why.

## 5. Wrap up
- Update `PROGRESS.md`: status, today's date, what was verified, what is still pending.
- Give the user a short summary (what was built, what passed, what's next), then stop. Don't start the next milestone without being asked.
