# Contributing to TopicEye

Thanks for your interest in contributing! TopicEye is built for content creators, and the fastest way to help is to **add a source connector** — each one lets the radar cover more ground.

## Quick start (5 minutes)

```bash
git clone https://github.com/fxbin/TopicEye.git
cd TopicEye/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# SQLite is the default database — no extra setup needed.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8102 --reload
```

In another terminal:

```bash
cd TopicEye/frontend
npm install
npm run dev
```

Open http://localhost:3000. The first run will seed default categories and (if you enable it) an admin account.

## Project layout

```
backend/app/
├── api/v1/            # FastAPI routers (one file per domain)
├── models/            # SQLAlchemy ORM models
├── schemas/           # Pydantic request/response schemas
├── services/          # Business logic
│   ├── scrapers/      # RSS / RSSHub / YouTube / Podcast / Newsletter
│   └── trending_scrapers/  # Trending boards (Reddit, Zhihu, ...)
├── repositories/      # DB access layer
└── core/              # config, database, auth primitives
frontend/src/
├── app/               # Next.js App Router pages
├── components/        # Shared UI (Button, Panel, Badge in ui.tsx)
└── lib/               # API client, navigation, helpers
```

## Commit discipline

This repo uses **Conventional Commits** with Chinese summaries. The convention is enforced in [AGENTS.md](AGENTS.md) — read it before your first PR.

Shape: `<type>(<scope>): <中文说明>`

- **types:** `feat`, `fix`, `chore`, `test`, `docs`, `refactor`
- **scopes:** `auth`, `cache`, `trending`, `backend`, `frontend`, `config`, `db`, `docs`, `test`

Examples:

```
feat(auth): 后端新增 OAuth 登录(Google/GitHub)
fix(cache): 重试统计工作台启动预热
docs: 补充 agent 提交规范
```

Stage explicit paths (`git add backend/app/...`), avoid `git add -A`. Keep each commit focused on one behavior or risk boundary — don't mix backend and frontend in the same commit unless they're the same feature.

## Before submitting a PR

Run the smallest relevant verification:

```bash
# Backend — syntax + tests
cd backend
python -m py_compile $(git diff --name-only --cached | grep '\.py$')
python -m pytest tests/path/to/your_test.py -q

# Frontend — type check (don't run `npm run lint`, it's broken under current Next.js)
cd frontend && npx tsc --noEmit

# Shell scripts
bash -n path/to/script.sh
```

Inspect your staged diff:

```bash
git diff --cached --stat
git diff --cached --summary
```

Keep local-only files out of commits — especially `backend/.env`, `*.db`, `venv/`, `node_modules/`, and screenshots.

## How to add a source connector

This is the most valuable contribution and the most beginner-friendly. A connector lives in `backend/app/services/scrapers/` (for content sources) or `backend/app/services/trending_scrapers/` (for ranking boards).

A minimal source connector:

```python
# backend/app/services/scrapers/my_source.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class MySourceItem:
    title: str
    url: str
    summary: str = ""
    published_at: str | None = None

def fetch(url: str) -> list[MySourceItem]:
    """Fetch and parse items from the given source URL."""
    # 1. fetch the page / feed (use httpx, reuse RSS parser if applicable)
    # 2. parse into MySourceItem list
    # 3. return — the framework handles normalization & storage
    ...
```

Then register it in the URL auto-recognizer (`backend/app/services/scrapers/__init__.py`) so the frontend "paste URL" flow can detect it. See existing connectors like `rss.py`, `youtube.py`, or `podcast.py` for the full pattern.

**Suggested flow:**
1. Open an issue with `good first issue` + the source you want to add.
2. Copy an existing connector as a template.
3. Add a test under `backend/tests/` (see `test_rss_scraper.py` / `test_youtube_scraper.py`).
4. Submit a PR — include a sample URL you tested against.

## Adding an OAuth provider

If you want to add a provider beyond Google / GitHub (e.g. Microsoft, Apple), the OAuth layer is in `backend/app/core/oauth.py` and `backend/app/api/v1/oauth.py`. Follow the existing Google/GitHub registration pattern, add config vars, and document the redirect URI in `backend/.env.example`.

## Code style

- **Backend:** Follow the existing async SQLAlchemy 2.0 style (`Mapped` / `mapped_column`). Reuse `retry_sqlite_locked` for DB writes. Keep routers thin — business logic goes in `services/`.
- **Frontend:** Self-built UI components (`components/ui.tsx` exports `Button`, `Panel`, `Badge`, `cx`). No third-party UI library. Tailwind v4. `lucide-react` for icons.
- **No new heavy dependencies without discussion.** The project is deliberately lean.

## Reporting bugs

Use the bug report template (`.github/ISSUE_TEMPLATE/bug_report.yml`). Include:
- What you expected vs. what happened
- Backend logs (the relevant `ERROR` / `WARNI` lines)
- `backend/.env` with secrets redacted
- Browser console errors if frontend

## Questions

Open a discussion or an issue with the `question` label. We're friendly.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
