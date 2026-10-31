# Local setup: from `git clone` to a working app

One straight path from an empty computer to logging in and processing your first invoice. Do the steps in order; each one ends with a **✅ Check** so you know it worked before moving on.

Time: about 20 minutes the first time (most of it is downloads).
For day-to-day use after setup (starting, stopping, updating, commands, troubleshooting), see [setup_guide.md](setup_guide.md).

| Part | What you do |
|---|---|
| [1](#part-1--install-docker-desktop) | Install Docker Desktop |
| [2](#part-2--get-the-code-from-github) | Get the code from GitHub |
| [3](#part-3--get-your-secrets-ready) | Get your secrets ready (Gemini key, session secret) |
| [4](#part-4--create-the-env-file) | Create the `.env` file |
| [5](#part-5--build-and-start-with-docker) | Build and start with Docker |
| [6](#part-6--create-the-database-and-the-login-users) | Create the database and the login users |
| [7](#part-7--log-in-to-the-app) | Log in to the app |
| [8](#part-8--process-your-first-invoice) | Process your first invoice |
| [9](#part-9--look-inside-the-database-optional) | Look inside the database (optional) |
| [10](#part-10--final-checklist) | Final checklist |

---

## Part 1 — Install Docker Desktop

Docker runs the three parts of the app (database, API, UI) in isolated "containers", so you don't have to install Python, PostgreSQL or Tesseract yourself.

1. Find out your Mac's chip:  → *About This Mac*. It says **Apple M1/M2/M3/M4…** or **Intel**.
2. Go to **docker.com/products/docker-desktop** → *Download for Mac*. Pick **Apple Silicon** or **Intel** to match.
   *Windows:* download *Docker Desktop for Windows* and accept the **WSL 2** option during install; restart when asked.
3. Open the downloaded file, drag **Docker** into *Applications*, then open Docker from *Applications*.
4. Accept the terms. You can skip signing in to a Docker account; it isn't needed.
5. Wait until Docker Desktop says **Engine running** (bottom-left) and the whale icon appears in the menu bar.

Leave Docker Desktop running whenever you use the project.

**✅ Check:** open **Terminal** (Cmd+Space → type *Terminal*) and run:
```bash
docker --version
docker compose version
```
Both print a version number (e.g. `Docker version 29.x`, `Docker Compose version v5.x`).
If you see `command not found` or `Cannot connect to the Docker daemon`, Docker Desktop isn't open yet.

## Part 2 — Get the code from GitHub

1. Check that git is installed:
   ```bash
   git --version
   ```
   On a Mac, if it isn't installed, a window offers to install the *Command Line Tools*. Click **Install**, wait, then run the command again.

2. The repo is **private**, so git needs a login. Create a **personal access token** once:
   github.com → your photo (top right) → **Settings** → **Developer settings** (bottom of the left menu) → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)** → Note: `invoice-intake`, Expiration: your choice, tick **`repo`** → **Generate token**. Copy it now, because GitHub shows it only once.

3. Download the code (here into your Desktop):
   ```bash
   cd ~/Desktop
   git clone https://github.com/diiyark123/invoice-intake.git
   cd invoice-intake
   ```
   When asked: **Username** = your GitHub username, **Password** = the **token** from step 2 (not your GitHub password). macOS remembers it.

**✅ Check:**
```bash
ls
```
shows `app`, `ui`, `docker-compose.yml`, `.env.example`… (run `ls -a` to see `.env.example`, since files starting with a dot are hidden).

From now on, **run every command from inside this `invoice-intake` folder.**

## Part 3 — Get your secrets ready

The app needs two secret values. Neither is ever stored on GitHub.

| Secret | What it's for | Required? |
|---|---|---|
| `GEMINI_API_KEY` | Lets the app call Google's Gemini AI to read invoices | Yes, to process invoices (login and screens work without it) |
| `SESSION_SECRET` | Signs login tokens so nobody can fake a login ([explained here](how_it_fits_together.md#part-1--login-tokens-and-session_secret)) | **Yes**, login fails without it |

**Get a Gemini key:**
1. Go to **aistudio.google.com/apikey** and sign in with a Google account.
2. Click **Create API key** (choose or create any Google Cloud project when asked).
3. Copy the key. It starts with `AIza…`.

The free tier is enough (15 requests per minute). Treat the key like a password: don't paste it into chats, emails or code. If it leaks, delete it on the same page and create a new one.

**Make a session secret:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```
Copy the long random string it prints. (*Windows:* use `python` instead of `python3`.) Any long random string works; this command just makes a good one.

Other values you may have heard of are **not** needed locally:

| Value | Why you don't need it locally |
|---|---|
| Database password | Fixed to `invoice` / `invoice` in `docker-compose.yml`. The database only runs on your computer |
| `ANTHROPIC_API_KEY` | Only if you switch the AI to Claude |
| `S3_*` (Cloudflare R2) | Only for cloud file storage; locally files go in the `storage/` folder |
| `SEED_CLERK_PASSWORD`, `SEED_MANAGER_PASSWORD` | Only if you want your own login passwords instead of the demo ones (see Part 6) |

## Part 4 — Create the `.env` file

`.env` holds your settings and secrets. It is listed in `.gitignore`, so git never uploads it.

1. Copy the template:
   ```bash
   cp .env.example .env
   ```
   (*Windows PowerShell:* `Copy-Item .env.example .env`)
2. Open it in a text editor:
   ```bash
   open -e .env
   ```
   (or open the folder in VS Code and click `.env`)
3. Fill in exactly **two lines** (no spaces around `=`, no quotes):
   ```
   GEMINI_API_KEY=AIza...your key...
   SESSION_SECRET=...the long random string from Part 3...
   ```
4. Save and close. Leave every other line as it is. [setup_guide.md §5](setup_guide.md#5-the-env-file-explained) explains each one.

**✅ Check** (shows only whether each value is filled, not the value itself):
```bash
grep -E "^(GEMINI_API_KEY|SESSION_SECRET)=." .env | cut -d= -f1
```
It must print both names. If one is missing, that line is still empty.

## Part 5 — Build and start with Docker

```bash
docker compose up -d --build
```

What this does (the file `docker-compose.yml` describes it):

| Container | What it is | Port on your computer |
|---|---|---|
| `db` | PostgreSQL 16, the database | 5432 |
| `api` | FastAPI backend: login, uploads, AI processing, rules | 8000 |
| `ui` | Streamlit web app you use in the browser | 8501 |

The first run downloads and builds everything: **about 4–5 minutes**. Later runs take seconds.

**✅ Check:**
```bash
docker compose ps
```
All three show **Up** (and `db` shows **healthy**):
```
invoice-intake-api-1   ...   Up   0.0.0.0:8000->8000/tcp
invoice-intake-db-1    ...   Up (healthy)   0.0.0.0:5432->5432/tcp
invoice-intake-ui-1    ...   Up   0.0.0.0:8501->8501/tcp
```
If `api` isn't up, run `docker compose logs api` and see [Troubleshooting](#if-something-goes-wrong).

## Part 6 — Create the database and the login users

The database is created in three layers. The first two happen by themselves; the third is one command.

| Layer | What gets created | How |
|---|---|---|
| 1. Empty database | A PostgreSQL database named `invoice`, user `invoice`, password `invoice` | **Automatic.** The `db` container creates it on its very first start, from the `POSTGRES_*` lines in `docker-compose.yml` |
| 2. Tables | 9 tables: `users`, `vendors`, `settings`, `documents`, `extractions`, `extracted_fields`, `invoices`, `invoice_line_items`, `audit_log` | **Automatic.** The `api` container runs `alembic upgrade head` every time it starts (the files in `alembic/versions/` describe the tables) |
| 3. Starting data | The 2 login users, 15 known vendors, default settings | **You run the seed once** (below) |

**Run the seed:**
```bash
docker compose exec api python -m app.seed
```
**✅ Check:** the last line says
```
Seed complete, rows added: {'users': 2, 'vendors': 15, 'settings': 1}
```
Running it again is safe. It then says `rows added: {'users': 0, ...}` because nothing is missing.

This creates the two logins:

| Role | Email | Password | Can do |
|---|---|---|---|
| AP clerk | `clerk@meridian.test` | `clerk-demo-123` | Upload, review queue, review and approve invoices |
| AP manager | `manager@meridian.test` | `manager-demo-123` | Everything the clerk can, plus Dashboard and Settings |

Passwords are stored only as secure hashes (bcrypt), never as plain text.

**Want your own passwords instead?** Add these two lines to `.env` (at least 10 characters each), then restart and seed again:
```
SEED_CLERK_PASSWORD=your-clerk-password
SEED_MANAGER_PASSWORD=your-manager-password
```
```bash
docker compose up -d
docker compose exec api python -m app.seed
```
The seed sees the new values and resets those users' passwords. Do this again any time you want to change a password.

**✅ Check the tables exist:**
```bash
docker compose exec db psql -U invoice -d invoice -c "\dt"
```
lists the 9 tables above plus `alembic_version` (10 rows).

## Part 7 — Log in to the app

1. **Check the API:** open **http://localhost:8000/health**. It shows
   ```
   {"status":"ok","database":"ok"}
   ```
   `"database":"ok"` means the API reached the database.
2. **Open the app:** **http://localhost:8501**.
3. Log in as the clerk: `clerk@meridian.test` / `clerk-demo-123`.

**✅ Check:** the left sidebar says *Logged in as …* and shows **Upload**, **Review queue** and **Review invoice**. Log out and log in as the manager: you also see **Dashboard** and **Settings**.

(API documentation for developers: **http://localhost:8000/docs**.)

## Part 8 — Process your first invoice

The repo includes sample invoices in the `data/dev/` folder (made-up, safe to use).

1. Log in as the clerk → **Upload**.
2. Click *Browse files* → open the `invoice-intake/data/dev/` folder → choose e.g. `invoice_0010.pdf` → **Upload**.
3. The *Recent uploads* table updates by itself every few seconds: *uploaded* → *processing* → **auto-approved** or **needs review** (usually 5–10 seconds).
4. If it says *needs review*, click **Open**. You see the invoice page with boxes around each value the AI read, and the reasons it needs a person. Fix anything wrong, then click **Save and approve**.

**✅ Check:** the invoice ends as *auto-approved* or *approved*. Log in as the manager → **Dashboard**: it is counted.

If it ends as **failed**, the error is shown on the row. The usual causes are a missing or wrong `GEMINI_API_KEY`, or `429` (too many requests; wait a minute). Fix it and click **Retry**. The file is never lost.

Need more sample invoices?
```bash
docker compose exec api python -m data.generator.generate --count 20 --out data/dev --scan 0.5
```

## Part 9 — Look inside the database (optional)

**From the terminal:**
```bash
docker compose exec db psql -U invoice -d invoice
```
Then try:
```sql
select email, role from users;
select filename, status from documents order by created_at desc limit 5;
select invoice_number, total, approval_type from invoices;
\q
```
(`\q` quits.)

**With a database app** (TablePlus, DBeaver, pgAdmin, or the VS Code *PostgreSQL* extension), create a new PostgreSQL connection:

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| User | `invoice` |
| Password | `invoice` |
| Database | `invoice` |

Look, but don't change rows by hand. The app keeps an audit trail, and manual edits bypass it.

## Part 10 — Final checklist

- [ ] `docker compose ps` shows `db`, `api` and `ui` running
- [ ] http://localhost:8000/health shows `"database":"ok"`
- [ ] The seed printed `Seed complete`
- [ ] You can log in at http://localhost:8501 as the clerk and as the manager
- [ ] One sample invoice was processed and approved
- [ ] `git status` does **not** list `.env`

You're set up. Next time you only need:
```bash
cd ~/Desktop/invoice-intake
git pull
docker compose up -d --build
```
Stop with `docker compose stop`. **Never** run `docker compose down -v` unless you want to delete all data. See [setup_guide.md §4](setup_guide.md#4-stopping-and-where-your-data-lives).

## If something goes wrong

| Problem | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Open Docker Desktop and wait for *Engine running* |
| `port is already allocated` | Another program uses 5432, 8000 or 8501. Quit it, or change the **left** number in `docker-compose.yml` (e.g. `"8001:8000"`) and use that port in the browser |
| `git clone` says *Authentication failed* | Use the **token** as the password, not your GitHub password; check it has the `repo` scope |
| Login shows a server error (not "wrong password") | `SESSION_SECRET` is empty: fill it in (Part 4), then `docker compose up -d` |
| *"Wrong email or password"* with the demo passwords | Run the seed (Part 6). If you set `SEED_*_PASSWORD`, use those instead |
| UI says *"Cannot reach the server"* | `docker compose ps`; if `api` isn't running, `docker compose logs api` shows why |
| Every upload `failed` | Check `GEMINI_API_KEY` in `.env`, `docker compose up -d`, then **Retry** |
| Want to start completely fresh | `docker compose down -v` (**deletes all data**), then Parts 5 and 6 again |

More: [setup_guide.md §8](setup_guide.md#8-troubleshooting) · how the pieces connect: [how_it_fits_together.md](how_it_fits_together.md)
