# Setting up the new machine

Do these once. Allow about 30 minutes.

## 1. Install the tools

| Tool | Why | How to check it works |
|---|---|---|
| **Docker Desktop** | Runs Postgres, the API and the UI. Tesseract is installed inside the container, so you don't need it on the machine itself | `docker --version` and `docker compose version` |
| **Git** | Version control | `git --version` |
| **VS Code** + **Claude Code** extension (or the Claude Code CLI) | To build with Claude | Open the Claude panel in VS Code |
| Python 3.11+ (optional) | Only needed if you run things outside Docker | `python --version` |

On Windows, Docker Desktop needs **WSL 2** turned on; the installer offers to do this. Restart after installing.

## 2. Copy the project folder
Copy the whole `invoice-intake` folder, **including the hidden `.claude` folder**. The `.claude` folder holds the `/next-milestone` skill.

Then, inside the folder:
```bash
git init
git add .
git commit -m "Handoff pack: spec, CLAUDE.md, playbook, config"
```

## 3. Create your `.env`
```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```
Fill in:
- `SESSION_SECRET`: run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the result.
- `GEMINI_API_KEY`: needed from M2 onward. Get one at aistudio.google.com/apikey. (`ANTHROPIC_API_KEY` only if you set `LLM_PROVIDER=anthropic`.)

## 4. Check that Docker works
```bash
docker run --rm hello-world
docker compose up -d db       # starts only Postgres
docker compose ps             # "db" should show as healthy
```
Don't run `docker compose up` for the whole stack yet. The `app/` code doesn't exist until M1, so the `api` and `ui` services will fail to start. That's expected.

## 5. Start building
Open the folder in VS Code, open Claude Code, and type:
```
/next-milestone
```
Claude reads `PROGRESS.md`, explains M1 in simple steps, and waits for your "go".

## If something goes wrong
| Problem | Fix |
|---|---|
| Port 5432 already in use | Another Postgres is running. Stop it, or change `"5432:5432"` to `"5433:5432"` in `docker-compose.yml` |
| `api` keeps restarting | Run `docker compose logs api`. Before M1 this is normal, because the code doesn't exist yet |
| Corporate proxy blocks `docker pull` / `pip` | Ask IT for Docker Hub access, or use a personal machine |
| Changed `pyproject.toml` | `docker compose up -d --build` to rebuild the image |
