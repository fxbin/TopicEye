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

### `POST /api/v1/scoring/lfv` — Low-follower-viral detection

Same request/response shape, but uses a formula that rewards low source authority:

```
lfv = (viral*0.45 + creator*0.30 + quality*0.25) * obscure_factor * freshness_boost
```

where `obscure_factor = max(0.05, 1 - source_weight/100)`. Use this to find content heating up **before** the source becomes popular.

## curl examples

```bash
# Score a single item
curl -X POST http://localhost:8102/api/v1/scoring/score \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"content_id":1,"title":"AI agents reshape content","info_density":78,"actionability":65,"source_weight":70,"creator_score":72,"viral_score":45,"freshness_score":90,"quality_score":75,"risk_score":10,"source_weight_db":3}]}'

# Low-follower viral detection on a batch
curl -X POST http://localhost:8102/api/v1/scoring/lfv \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"content_id":1,"title":"...","viral_score":80,"creator_score":60,"quality_score":70,"source_weight":30,"risk_score":5,"source_weight_db":1}]}'
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
