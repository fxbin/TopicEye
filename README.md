# TopicEye

**AI-powered content discovery and topic radar for creators.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/fxbin/TopicEye/actions/workflows/ci.yml/badge.svg)](https://github.com/fxbin/TopicEye/actions/workflows/ci.yml)
[![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Frontend: Next.js](https://img.shields.io/badge/Frontend-Next.js_16-black.svg)](https://nextjs.org/)

[English](README.md) | [简体中文](README.zh-CN.md)

---

TopicEye continuously crawls 25+ sources (RSS, Reddit, YouTube, podcasts, newsletters, trending boards), scores every item through a transparent 6-dimension engine, and surfaces the topics worth writing about today. It is built for content creators who are overwhelmed by noise and need curation with taste — not another feed reader.

![Today's Picks](docs/screenshots/screenshot-today.png)

## Why TopicEye

- **Transparent scoring engine, not a black box.** Every selected item ships with a full breakdown: base score (information density / actionability / creator value / viral potential / source authority / freshness), quality gates, time decay, diversity penalty, and feedback signal. See the [`algorithm` page](docs/screenshots/screenshot-algorithm.png) in the app.
- **Feedback closes the loop.** Your 👍 / 👎 doesn't just get saved — it is weighted at 15% and feeds back into ranking. The engine gets sharper the more you use it.
- **Self-host friendly.** Full Docker setup, SQLite or PostgreSQL, OAuth login (Google / GitHub). Your data stays yours.
- **Agent-native (planned).** The scoring engine is being exposed as a stable API so other agents and tools can call it as their ranking layer.

## Screenshots

| Today's Picks | Trending Radar | Low-Follower Viral |
|---|---|---|
| ![today](docs/screenshots/screenshot-today.png) | ![trending](docs/screenshots/screenshot-trending.png) | ![lfv](docs/screenshots/screenshot-low-follower-viral.png) |

| Daily Report | Algorithm Flow | Stats Dashboard |
|---|---|---|
| ![daily](docs/screenshots/screenshot-daily.png) | ![algorithm](docs/screenshots/screenshot-algorithm.png) | ![stats](docs/screenshots/screenshot-stats.png) |

## Features

| Module | Description |
|---|---|
| **Source management** | RSS / RSSHub / Reddit / YouTube / Podcasts / Newsletters / custom sites. Public sources + private sources per user. |
| **Curation scoring** | 6-dimension weighted engine + P70 percentile cutoff + risk control + user feedback calibration. |
| **AI analysis** | Per-item summary, key points, topic suggestions (differentiated prompts for CN/EN content). |
| **Daily & weekly reports** | Auto-generated from the content pool, delivered to the notification center. |
| **Trend radar** | Topic trending + low-follower viral detection (find breakout posts before they peak). |
| **Favorites** | Save items across sessions (per-user). |
| **OAuth login** | Google / GitHub (email + password also supported). |

## Tech stack

- **Backend:** FastAPI (async) · SQLAlchemy 2.0 · Alembic · DuckDB (analytics) · httpx
- **Frontend:** Next.js 16 · React 19 · TypeScript · Tailwind CSS v4
- **Database:** SQLite (default) or PostgreSQL · DuckDB as a read-only analytics layer over OLTP
- **Auth:** Opaque bearer tokens (DB-hashed) + OAuth via Authlib
- **Infra:** Docker / docker-compose (dev + prod) · APScheduler

## Quick start

### Prerequisites

- Python 3.12+ · Node.js 20+ · Git
- **or** Docker + Docker Compose (easiest path)

### Option A — Docker Compose (recommended for running the service)

```bash
git clone https://github.com/fxbin/TopicEye.git
cd TopicEye
docker compose -f docker-compose.prod.yml up -d --build
```

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs

> The default `docker-compose.yml` is deliberately a hot-reload development
> setup. Use `docker compose up -d --build` there only while developing; it
> runs `next dev` and is not the local deployment configuration.

### Option B — Local development

**1. Backend** (port 8102)

```bash
cd TopicEye/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # edit as needed
uvicorn app.main:app --host 127.0.0.1 --port 8102 --reload
```

**2. Frontend** (port 3000, in a new terminal)

```bash
cd TopicEye/frontend
npm install
npm run dev
```

Open http://localhost:3000.

> **Proxy note:** if you run a local HTTP proxy (ClashX / Surge on :7890), make sure `localhost` and `127.0.0.1` bypass it, or set `BACKEND_API_URL=http://127.0.0.1:8102` before `npm run dev`.

## Configuration

All configuration is environment-driven. See [`backend/.env.example`](backend/.env.example) for the full list with comments. Highlights:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./topiceye.db` | OLTP database. Swap to `postgresql+asyncpg://...` for Postgres. |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed frontend origins. |
| `OAUTH_GOOGLE_CLIENT_ID` / `_SECRET` | empty | Enable Google login. [Guide](backend/.env.example). |
| `OAUTH_GITHUB_CLIENT_ID` / `_SECRET` | empty | Enable GitHub login. |

> **Webnovel-CN module** (Fanqie / Qimao / Zhihu Yanxuan) is gated behind a runtime feature flag — disabled by default. Admins can enable it from **Source management → Feature flags** in the UI, or via `PUT /api/v1/settings/feature-flags`. No restart needed.

## Development

```bash
# Backend tests (uses an isolated test database)
cd backend && python -m pytest tests/ -q

# Frontend type check
cd frontend && npx tsc --noEmit

# Run a single scraper manually
curl -X POST http://127.0.0.1:8102/api/v1/sources/1/sync
```

The project uses Conventional Commits (`feat(auth): ...`, `fix(cache): ...`). See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow, and [AGENTS.md](AGENTS.md) for the commit discipline enforced in this repo.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, code style, and workflow. Feel free to open an issue with the `good first issue` label to find a starter task.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Copyright © 2026 fxbin.
