# Invoice Intake — AI for Accounts Payable

Reads vendor invoices (PDF, scans, photos) with OCR + an LLM (Gemini by default, Claude optional), checks them against business rules, auto-approves the confident ones and sends the rest to a human review screen.

> **Status:** M1 done (skeleton, database, seed data, invoice generator). See `PROGRESS.md`.

## Demo logins (created by `python -m app.seed`)
| Role | Email | Password |
|---|---|---|
| AP clerk | `clerk@meridian.test` | `clerk-demo-123` |
| AP manager | `manager@meridian.test` | `manager-demo-123` |

Demo only. Override with `SEED_CLERK_PASSWORD` / `SEED_MANAGER_PASSWORD` before seeding anywhere public.

## Start here
1. `docs/SETUP_NEW_MACHINE.md`: install Docker etc. and create `.env`
2. `PROJECT_SPEC.md`: the full specification
3. `docs/BUILD_PLAYBOOK.md`: milestone steps and design decisions
4. In Claude Code, run `/next-milestone`

## What's in this folder
| File | Purpose |
|---|---|
| `PROJECT_SPEC.md` | Single source of truth: what to build |
| `CLAUDE.md` | Instructions Claude Code loads automatically |
| `PROGRESS.md` | Which milestone we're on |
| `docs/BUILD_PLAYBOOK.md` | Step-by-step per milestone, with decisions |
| `docs/SETUP_NEW_MACHINE.md` | One-time machine setup |
| `.claude/skills/next-milestone/` | `/next-milestone` skill |
| `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example` | Ready-made config |

This README will be rewritten in M6 with run instructions and demo logins.
