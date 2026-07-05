# Roadmap

This is the public roadmap for TopicEye. It tracks the direction of the next few releases and the reasoning behind them. Dates are targets, not promises — this is a community project and we ship when it's ready.

For the full history of what's shipped, see the **Product Updates** page inside the app (or the `product_updates` records seeded by Alembic).

## Guiding principles

1. **Open source first, commercialization later.** We earn the right to charge only after the free, self-hostable product is genuinely useful and a community has formed around it.
2. **The scoring engine is the moat.** TopicEye's differentiation is the transparent 6-dimension scoring + low-follower-viral detection — not the breadth of sources. We invest where the moat is.
3. **Agent-native.** In 2026+, an open project's biggest leverage is becoming the capability that other agents and tools call. We expose the engine, not lock it away.
4. **No premature infrastructure.** Multi-user quotas, Redis-backed state, payment gateways — these come only when real adoption signals demand them.

## v0.4.0 — Open-source readiness *(target: 2026-07-25)*

**Theme: make the project legally and practically participable.**

- [ ] **Open-source infrastructure pack** — Apache-2.0 license, English README, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR templates, screenshots in README, CI badge, `frontend/.env.example`.
- [ ] **Webnovel-CN feature flag** — China-specific scrapers (Fanqie / Qimao / Zhihu Yanxuan / Heiyan / Ishugui, ~2500 lines) gated behind `WEBNOVEL_CN_ENABLED` (default off). Keeps the international experience clean; code stays, just not loaded by default.
- [ ] **Source quota counting** — count private sources per user + numerify `plan_catalog.limits.custom_sources`. This is the *prerequisite* for any future paywall — charging without a quota enforced is a product incident.
- [ ] **Source contributor interface** — formalize the `scrapers/` plugin protocol, "paste URL auto-detect" flow, and a `good first issue` template. Turn feature development into a contribution pipeline.
- [ ] **Guest today-picks** — let logged-out visitors see `today-picks` with a lightweight score explanation and a non-blocking login prompt. The north-star page's first impression.

**Explicitly deferred from v0.4.0:** algorithm regression dashboard UI, payment, Agent API.

## v0.5.0 — Agent-native scoring API *(target: 2026-10-31)*

**Theme: turn TopicEye from a product into the ranking framework that other agents call.**

- [ ] **`POST /api/v1/score`** — send a batch of content items, get back ranked items + full `ScoreBreakdown` (base / quality / risk / time-decay / diversity / feedback / per-dimension). API-key auth (reuses `user_api_tokens`).
- [ ] **`POST /api/v1/lfv`** — low-follower-viral detection. Send candidate items from low-follower sources, get breakout candidates with confidence.
- [ ] **OpenAPI + examples** — versioned spec, `curl` examples, a minimal MCP/CLI call sample so Claude Code / Codex / n8n can integrate in minutes.
- [ ] **Scoring snapshot dashboard** — based on snapshot data accumulated since v0.4, build trend curves / config A-B comparison / accuracy metrics. Turns the algorithm from an internal tool into a *transparency asset* that proves the engine is trustworthy.

**The bet:** in the agent era, a stable, well-documented scoring API becomes the default ranking layer for content-class agents. That's more durable than any paywall.

## v0.6.0 — Commercialization prep *(target: 2027-01-31, gated)*

**Theme: build the quota and subscription infrastructure — but don't rush to charge.**

**Trigger conditions (must be met before this version starts):**
- The north-star metric (today-picks DAU) shows a sustained upward trend.
- Real cloud-hosting demand appears (people actively asking "can you host this?").

If the conditions aren't met, we keep polishing v0.4/v0.5 instead. We do **not** over-monetize.

- [ ] **Multi-user quotas + state externalization** — LLM quota bucketed per `user_id` (Redis token bucket), in-process state moved to Redis/PG, auth rate-limiting per user. This is the *prerequisite for scale*, not a feature in itself.
- [ ] **Stripe subscriptions (single gateway)** — strict minimal slices in order: catalog numerify (done in v0.4) → single-point quota enforcement → subscription data model (`subscriptions` / `payment_events` + User columns) → single-gateway checkout → webhook idempotency + signature verification → Stripe Customer Portal. **No WeChat/Alipay, no multi-gateway abstraction** until the single path is proven.
- [ ] **Charge for scale/convenience, never for core features.** A free user gets a fully working topic-discovery tool; Pro gets more sources, faster reports, higher API quota, team workspaces. The free tier must remain genuinely useful.

## What we're NOT doing (and why)

- **Not building a multi-gateway payment abstraction now.** Premature abstraction before the market is chosen.
- **Not doing the algorithm regression dashboard as a standalone internal tool.** It only makes sense once snapshot data exists *and* the scoring config has actually been tuned — a dashboard comparing "config vs itself" has zero information value.
- **Not physically splitting the webnovel-CN code into a separate package yet.** A feature flag captures 80% of the benefit (clean international experience) at 5% of the cost. Physical extraction can wait for a real need.
- **Not adopting GPL/AGPL.** Apache-2.0 keeps the project enterprise-friendly and integration-friendly, which matters for the Agent-native direction.

## How to influence this roadmap

- Open an issue with the `roadmap` or `enhancement` label.
- Source connectors and scrapers don't need roadmap approval — see [CONTRIBUTING.md → How to add a source connector](CONTRIBUTING.md). Just open a PR.
- For bigger direction questions, start a GitHub Discussion.
