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

- **Transparent scoring engine, not a black box.** Every selected item ships with a full breakdown: base score (information density / actionability / creator value / viral potential / source authority / freshness), quality gates, time decay, diversity penalty, and feedback signal. See [`algorithm` page](docs/screenshots/screenshot-timeline.png) in the app.
- **Feedback closes the loop.** Your 👍 / 👎 doesn't just get saved — it is weighted at 15% and feeds back into ranking. The engine gets sharper the more you use it.
- **Self-host friendly.** Full Docker setup, SQLite or PostgreSQL, OAuth login (Google / GitHub). Your data stays yours.
- **Agent-native (planned).** The scoring engine is being exposed as a stable API so other agents and tools can call it as their ranking layer. See the [roadmap](ROADMAP.md).

## Screenshots

| Today's Picks | Timeline | Daily Report |
|---|---|---|
| ![today](docs/screenshots/screenshot-today.png) | ![timeline](docs/screenshots/screenshot-timeline.png) | ![daily](docs/screenshots/screenshot-daily.png) |

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

### Option A — Docker Compose (recommended)

```bash
git clone https://github.com/fxbin/TopicEye.git
cd TopicEye
docker compose up -d
```

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs

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
| `WEBNOVEL_CN_ENABLED` | `false` | Enable China-specific webnovel scrapers (Fanqie / Qimao / Zhihu Yanxuan). Disabled by default to keep the international experience clean. |

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

## Roadmap

We just shipped **v0.3.0** (public/private sources, user-owned daily reports). Up next:

- **v0.4.0 — Open-source readiness:** Apache-2.0 license, English README, contributor docs, source-contributor plugin protocol, webnovel-CN feature flag. [Full roadmap →](ROADMAP.md)
- **v0.5.0 — Agent-native scoring API:** expose the 6-dimension engine + low-follower-viral detection as a stable, key-authenticated API so other agents can call it.
- **v0.6.0 — Commercialization prep:** multi-user quotas + Stripe subscriptions (gated behind real adoption signals).

## Contributing

Contributions are welcome — especially **new source connectors** (RSS feeds, podcast indexes, newsletter scrapers, trending boards). Each connector is a self-contained, well-scoped PR that's perfect for a first contribution.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, code style, and how to add a source. Feel free to open an issue with the `good first issue` label to find a starter task.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Copyright © 2026 fxbin.
