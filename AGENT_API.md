# Agent API

TopicEye exposes its scoring engine as a stable HTTP API so other agents, CLIs, and automation tools (Claude Code, Codex, n8n, custom scripts) can use it as their content-ranking layer.

## Authentication

All endpoints require a Bearer token. You can use either:

1. **Personal API token** (recommended for agents/scripts) — create one in the app at **Profile → API tokens**, or via `POST /api/v1/me/api-tokens`. The token is shown once.
2. **Browser session token** — useful for testing in the docs UI.

```
Authorization: Bearer <your-token>
```

## Endpoints

### `POST /api/v1/scoring/score` — Full curation scoring

Run items through the complete 6-dimension pipeline and get the full breakdown.

**Request body:**

```json
{
  "items": [
    {
      "content_id": 1,
      "title": "Why AI agents will reshape content discovery",
      "category": "AI",
      "source_name": "example.com",
      "published_at": "2026-07-07T10:00:00Z",
      "info_density": 78,
      "actionability": 65,
      "source_weight": 70,
      "creator_score": 72,
      "viral_score": 45,
      "freshness_score": 90,
      "quality_score": 75,
      "risk_score": 10,
      "source_weight_db": 3,
      "feedback_score": 5
    }
  ]
}
```

Only `content_id` is required — every other field defaults to a neutral value. Send 1–50 items per call.

**Response:**

```json
{
  "results": [
    {
      "content_id": 1,
      "score": {
        "base_score": 68.4,
        "source_bonus": 0.0,
        "quality_factor": 1.0,
        "risk_factor": 0.98,
        "time_decay": 0.85,
        "diversity_factor": 1.0,
        "final_score": 57.2,
        "dimension_scores": {
          "info_density": 19.5,
          "actionability": 13.0,
          "creator_value": 12.96,
          "viral_potential": 6.75,
          "source_authority": 8.4,
          "freshness": 9.0
        },
        "selected": true,
        "threshold_used": 55.0
      }
    }
  ],
  "count": 1
}
```

Items with `risk_score > 82` are hard-excluded (won't appear in results).

## Reading TopicEye data (skill endpoints)

The scoring endpoint above ranks **caller-supplied** items. The skill endpoints below let agents **read TopicEye's own curated output** — today's picks, daily report, and trends. All require the same Bearer token.

### `GET /api/v1/skill/today-picks`

Today's curated picks with full score breakdowns. This is the primary endpoint for "what's worth writing today?"

| Param | Type | Default | Notes |
|---|---|---|---|
| `hours` | int | 48 | Look-back window (1–168) |
| `limit` | int | 20 | Max items (1–100) |
| `category` | string | — | Optional category filter (e.g. `AI`) |

Returns the same shape as `GET /contents/today-picks`: `{items, total, event_members_hidden, topics, page, page_size}`. Each `items[*].analysis` carries `adjusted_curation_score` (final ranking score) and `score_breakdown`.

```bash
curl "$BASE/api/v1/skill/today-picks?hours=48&limit=10" -H "Authorization: Bearer $TOKEN"
```

### `GET /api/v1/skill/daily-report`

The daily report (edited curation summary). Omit `date` for today's latest snapshot.

| Param | Type | Default | Notes |
|---|---|---|---|
| `date` | string | today | `YYYY-MM-DD` |

Returns `overview` (summary paragraph), `takeaway`, `top_picks`, `keywords`, `trends`. 404 if no report exists for the given date.

```bash
curl "$BASE/api/v1/skill/daily-report?date=2026-07-15" -H "Authorization: Bearer $TOKEN"
```

### `GET /api/v1/skill/trends`

Merged topic trends + keyword cloud in one response.

| Param | Type | Default | Notes |
|---|---|---|---|
| `days` | int | 7 | Look-back days (1–30) |
| `limit` | int | 50 | Max keywords (10–200) |

Returns `{days, topics, keywords}`. Backed by the DuckDB analytical layer — returns 503 if unavailable.

```bash
curl "$BASE/api/v1/skill/trends?days=7" -H "Authorization: Bearer $TOKEN"
```

## curl examples

```bash
# Score a single item
curl -X POST http://localhost:8102/api/v1/scoring/score \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"content_id":1,"title":"AI agents reshape content","info_density":78,"actionability":65,"source_weight":70,"creator_score":72,"viral_score":45,"freshness_score":90,"quality_score":75,"risk_score":10,"source_weight_db":3}]}'

```

## Dimension reference

| Field | Weight in `/score` | Range | What it means |
|---|---|---|---|
| `info_density` | 0.25 | 0-100 | Signal-to-noise ratio of the content |
| `actionability` | 0.20 | 0-100 | How actionable for creators |
| `creator_score` | 0.18 | 0-100 | Value to content creators |
| `viral_score` | 0.15 | 0-100 | Viral potential |
| `source_weight` | 0.12 | 0-100 | Analysis-layer source authority |
| `freshness_score` | 0.10 | 0-100 | Freshness signal |
| `quality_score` | gate | 0-100 | Quality gate (not weighted, but gates ranking) |
| `risk_score` | filter | 0-100 | >82 = hard-excluded |
| `source_weight_db` | bonus | 1-5 | DB source tier, drives source_bonus |
| `feedback_score` | 0.15 adj | any | User feedback signal, clamped to [-20, 20] |

## OpenAPI spec

The full machine-readable spec is available at `/openapi.json` (or browse interactively at `/docs`). The scoring schemas (`ScoringRequestItem`, `ScoreBreakdownResponse`) are included so code generators and MCP servers can consume them directly.

## MCP Server

TopicEye also speaks the **Model Context Protocol** natively: a streamable-http MCP server is mounted at **`/mcp`** (2026-07-28 stateless protocol; the same server auto-negotiates older protocol revisions for legacy clients).

**Auth is the same Bearer token as the REST API** (see Authentication above) — create a personal API token, then configure your MCP client to send it as an `Authorization: Bearer <token>` header.

### Tools (no destructive writes)

All tools mirror the REST agent endpoints. Note `get_daily_report` without `date` auto-generates today's snapshot when absent (a write + potential LLM cost), same as the REST endpoint.

| Tool | What it does | Mirrors |
|---|---|---|
| `get_today_picks(hours, limit, category)` | 精选选题（含评分明细） | `GET /api/v1/skill/today-picks` |
| `get_daily_report(date?)` | 选题日报（按 token 所属用户） | `GET /api/v1/skill/daily-report` |
| `get_trends(days, limit)` | 话题趋势 + 关键词词频 | `GET /api/v1/skill/trends` |
| `score_items(items)` | 候选内容跑六维打分（`content_id` 为整数，1-50 条） | `POST /api/v1/scoring/score` |

### Client config examples

ZCode / Claude Code style (header-authenticated streamable-http):

```json
{
  "mcpServers": {
    "topiceye": {
      "url": "https://<your-host>/mcp",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

Operational notes:

- `MCP_ENABLED=false` disables the server (no route mounted; startup logs state it explicitly).
- Rate limit: 60 req/min per IP on `/mcp`.
- Production requires `SITE_BASE_URL` to be set (enables Host/Origin validation against DNS-rebinding; otherwise a startup warning is logged and the check stays off).
- Status of dynamic OAuth authorization (browser pop-up login): not yet implemented — the advertised issuer points back at the site, and clients should use pre-provisioned API tokens. Static Bearer tokens work with every MCP client; adding a real authorization server is a follow-up option (the verifier is swappable behind the SDK's `TokenVerifier`).
