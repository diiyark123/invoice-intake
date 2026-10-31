# Setup guide: run the project on your computer

Everything you need to run Invoice Intake from the GitHub repo, step by step. No other help is needed.
Tested on 2026-10-31 by cloning the repo into an empty folder on a Mac and following this guide. The first build took about 4 minutes.

**Contents**
1. [What you need](#1-what-you-need)
2. [First time on a computer](#2-first-time-on-a-computer)
3. [Every time after that](#3-every-time-after-that)
4. [Stopping, and where your data lives](#4-stopping-and-where-your-data-lives)
5. [The `.env` file, explained](#5-the-env-file-explained)
6. [Everyday commands](#6-everyday-commands)
7. [Saving your changes to GitHub](#7-saving-your-changes-to-github)
8. [Troubleshooting](#8-troubleshooting)
9. [Running without Docker (advanced)](#9-running-without-docker-advanced)

---

## 1. What you need

| Thing | Why | Where to get it |
|---|---|---|
| **Docker Desktop** | Runs the database, the API and the UI. You don't install Python or Postgres yourself | docker.com/products/docker-desktop |
| **git** | Downloads the code | On a Mac, run `git --version` in Terminal; if it isn't installed, macOS offers to install it |
| **Access to the GitHub repo** | The repo `github.com/diiyark123/invoice-intake` is private | Log in to GitHub as the owner, or ask the owner to add you under *Settings → Collaborators* |
| **A Gemini API key** | The AI that reads invoices. Without it everything works except processing uploads | aistudio.google.com/apikey → *Create API key* (the free tier is enough) |

Docker Desktop must be **open and running** (whale icon in the menu bar) before any `docker` command works.

## 2. First time on a computer

Follow **[local_setup.md](local_setup.md)**. It goes step by step from installing Docker to processing your first invoice, with a check after every step. In short:

```bash
git clone https://github.com/diiyark123/invoice-intake.git && cd invoice-intake
cp .env.example .env            # then fill in GEMINI_API_KEY and SESSION_SECRET
docker compose up -d --build    # first time ~4-5 minutes
docker compose exec api python -m app.seed
```
Open http://localhost:8501 and log in as `clerk@meridian.test` / `clerk-demo-123` (manager: `manager@meridian.test` / `manager-demo-123`).

## 3. Every time after that

```bash
cd ~/Desktop/invoice-intake       # wherever you cloned it
git pull                          # get the latest code (skip if you work alone on one computer)
docker compose up -d --build      # start; rebuilds only what changed (seconds if nothing did)
```
Then open http://localhost:8501. That's all. There's no need to seed again or touch `.env`.

Database changes in new code are applied automatically on start (`alembic upgrade head` runs inside the `api` container). Running the seed again is harmless, because it only adds what is missing.

## 4. Stopping, and where your data lives

| Command | What it does | Your data |
|---|---|---|
| `docker compose stop` | Stops the 3 containers | ✅ kept |
| `docker compose down` | Stops and removes the containers | ✅ kept |
| `docker compose down -v` | Also deletes the database volume | ❌ **all invoices, users and audit history are deleted** |

Quitting Docker Desktop or restarting the computer is also safe. Run `docker compose up -d` again afterwards.

| Data | Lives in |
|---|---|
| Database (documents, invoices, audit log, users, settings) | A Docker volume called `<folder name>_pgdata`, e.g. `invoice-intake_pgdata` |
| Uploaded files and page images | The `storage/` folder inside the project (git-ignored) |
| Settings and keys | `.env` (git-ignored) |

The database volume is named after the **folder**. If you delete the folder and clone again **into a folder with the same name**, your old data is still there. If you clone into a folder with a different name, you start with an empty database, so run the seed (Step 4) again. Uploaded files live in `storage/`, so deleting the folder deletes them. If you want to keep them, copy that folder first.

## 5. The `.env` file, explained

| Setting | Default in `.env.example` | Change it? |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://invoice:invoice@db:5432/invoice` | No. `db` is the database container's name. Only change it when running without Docker |
| `LLM_PROVIDER` | `gemini` | No. `anthropic` switches to Claude (also needs `ANTHROPIC_API_KEY` and `LLM_MODEL=claude-opus-5-5`) |
| `GEMINI_API_KEY` | empty | **Yes, required** to process invoices |
| `ANTHROPIC_API_KEY` | empty | Only if you use Claude |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | No (cheapest fast model; see the evaluation report) |
| `LLM_MAX_TOKENS` | `8000` | No |
| `STORAGE_BACKEND` | `local` | No. `s3` uses Cloudflare R2; see [admin_runbook.md](admin_runbook.md#switch-to-cloudflare-r2-permanent-file-storage) |
| `STORAGE_LOCAL_PATH` | `./storage` | No |
| `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | empty / `auto` | Only with `STORAGE_BACKEND=s3` |
| `SESSION_SECRET` | empty | **Yes, required.** A long random string used to sign login tokens ([how_it_fits_together.md](how_it_fits_together.md)). Changing it logs everyone out |
| `API_BASE_URL` | `http://api:8000` | No. It's how the UI container finds the API container |
| `TESSERACT_CMD` | `/usr/bin/tesseract` | No (correct inside Docker) |

Optional settings that aren't in the file (add them only if needed):

| Setting | Effect |
|---|---|
| `SEED_CLERK_PASSWORD`, `SEED_MANAGER_PASSWORD` | Use your own passwords instead of the demo ones. Add them, then run the seed again; it resets the password |
| `APP_ENV=production` | Refuses the demo passwords. Used on Render; not needed locally |

After editing `.env`, run `docker compose up -d` so the containers pick up the change.

## 6. Everyday commands

Run these from the project folder while the app is running.

| Task | Command |
|---|---|
| Watch the API's log (each processing step, errors) | `docker compose logs -f api` (Ctrl+C to stop watching) |
| Check that all 3 containers are running | `docker compose ps` |
| Run the tests (no AI calls, no cost) | `docker compose exec api pytest -q` |
| Make 20 fake invoices to try | `docker compose exec api python -m data.generator.generate --count 20 --out data/dev --scan 0.5` |
| Run the evaluation on the test set (uses Gemini, about 25 calls) | `docker compose exec api python -m eval.run_eval --note "what changed"` |
| Open the database directly | `docker compose exec db psql -U invoice -d invoice` (type `\q` to leave) |
| Restart everything | `docker compose restart` |

Tests and the evaluation use their own temporary databases, so they never touch your invoices.

Day-to-day settings such as the approval threshold, tolerances and vendor list are changed in the app: log in as the manager and open **Settings**.

## 7. Saving your changes to GitHub

```bash
git status                        # see what changed
git add -A
git commit -m "Describe what you changed"
git push
```
Check `git status` before committing: `.env` must never appear in it.
If the app is deployed on Render, pushing to `main` redeploys it automatically ([admin_runbook.md](admin_runbook.md)).

## 8. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running | Open Docker Desktop, wait for it to say *running*, try again |
| `port is already allocated` (5432, 8000 or 8501) | Another program uses that port | Stop the other program, or change the **left** number in `docker-compose.yml` (e.g. `"8001:8000"`) and use that port in the browser |
| UI says *"Cannot reach the server"* | The `api` container isn't running or crashed | `docker compose ps`, then `docker compose logs api` to see the error |
| Login fails with a server error (not "wrong password") | `SESSION_SECRET` is empty in `.env` | Fill it in (Step 2), then `docker compose up -d` |
| *"Wrong email or password"* with the demo passwords | The seed was never run on this database | `docker compose exec api python -m app.seed` |
| Every upload ends up `failed` | Missing or wrong `GEMINI_API_KEY` | Fix `.env`, `docker compose up -d`, then **Retry** on the failed rows |
| Some uploads `failed` with `429` | Gemini free tier: 15 requests per minute | Wait a minute and click **Retry** |
| *"Session expired"* | Logins last 8 hours | Log in again |
| `git pull` says *"Your local changes would be overwritten"* | You edited files that also changed on GitHub | `git stash`, `git pull`, `git stash pop` |
| Something is badly broken and you want a clean start | — | `docker compose down -v` (**deletes all data**), then Steps 3 and 4 again |

## 9. Running without Docker (advanced)

Only if Docker can't be used. This path was **not** part of the 2026-10-31 test. You need Python 3.11+, PostgreSQL 16 (local or hosted, e.g. Neon) and Tesseract (`brew install tesseract`).

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```
In `.env`, change:
```
DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/<database>
TESSERACT_CMD=/opt/homebrew/bin/tesseract     # output of: which tesseract
```
(The UI doesn't read `.env`. Without Docker it uses `http://localhost:8000` for the API by default, which is correct here.)
Then, in two terminals (both with the venv active):
```bash
alembic upgrade head && python -m app.seed && uvicorn app.main:app --port 8000   # terminal 1
streamlit run ui/Home.py                                                          # terminal 2
```
