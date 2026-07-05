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

### The scraper contract

Every scraper subclasses `BaseScraper` and registers itself with `@register_scraper("<SourceType>")`. The framework instantiates it with `(source_url, source_config)` and calls `async fetch(client)` to get items.

```python
# backend/app/services/scrapers/my_source.py
from __future__ import annotations
from typing import Any
import httpx
from . import BaseScraper, register_scraper

@register_scraper("MySource")  # must match a SourceType enum value (backend/app/models/source.py)
class MySourceScraper(BaseScraper):
    def __init__(self, source_url: str, source_config: dict[str, Any] | None = None):
        super().__init__(source_url, source_config)
        # pre-parse anything you need from source_config (e.g. channel id)

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Fetch items. Each dict MUST have these keys:
            title, url, author, summary, raw_content, tags,
            published_at, cover_url
        Missing keys should be "" / None / [] — the framework normalizes.
        """
        resp = await client.get(self.url)
        resp.raise_for_status()
        # parse resp.text / resp.json() into entries...
        return [{"title": ..., "url": ..., "summary": ..., "published_at": ...}]
```

### Four places to touch (currently — we're consolidating this)

1. **Write the scraper** in `backend/app/services/scrapers/my_source.py` (use `rss.py` / `youtube.py` / `podcast.py` as templates — start with the simplest one matching your source type).
2. **Register the import** in `backend/app/services/scrapers/__init__.py` (the `from . import xxx` block near the bottom). Without this, the decorator never runs.
3. **Add the type** to `SourceType` enum in `backend/app/models/source.py` if it's genuinely new.
4. **Add host patterns** to `backend/app/services/scrapers/recognizer.py` so the "paste URL" auto-detect recognizes your source.

> **Note:** we're working on collapsing steps 2 + 4 into the registry so contributors only write the scraper. For now, copy an existing scraper end-to-end.

### Test template

The best template is `backend/tests/test_youtube_scraper.py` — it shows the three things to verify:
1. Registration: `get_scraper_cls("YouTube") is YouTubeScraper`
2. URL parsing helpers (pure functions, no network)
3. Full `fetch()` with a `FakeClient` that returns canned responses (no real HTTP)

**Suggested flow:**
1. Open an issue with `good first issue` + the source you want to add.
2. Copy the closest existing connector as a template.
3. Add a test under `backend/tests/` (copy `test_youtube_scraper.py` structure).
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
