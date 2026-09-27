## What & why

<!-- One or two sentences: what does this change do, and why? -->

Refs #<issue>

## Area

<!-- Check one or more -->
- [ ] backend
- [ ] frontend
- [ ] database / migration
- [ ] scraper / source connector
- [ ] auth
- [ ] docs
- [ ] config / infra

## Verification

<!-- The smallest check that proves this works. See CONTRIBUTING.md. -->
- [ ] `python -m pytest <relevant> -q` passes
- [ ] `npx tsc --noEmit` passes (frontend changes)
- [ ] Manual smoke test (describe below)

## Verifier verdict

<!-- CI 五项检查 = 机器 Verifier，全绿（或预存红已显式处置）后才能合并。
承载行为变更的 PR 还需独立复核结论（复核者 ≠ 实现过程），写在此处：
pass / fail / hold + 一句依据。纯依赖/文档/配置切片可写「CI 门禁即机器 Verifier」。 -->

## Checklist

- [ ] Commits follow Conventional Commits (`feat(auth): ...`) — see [AGENTS.md](../AGENTS.md)
- [ ] Branch named `issue-<number>-<short-slug>` and PR links the issue
- [ ] No local-only files staged (`.env`, `*.db`, `venv/`, `node_modules/`, screenshots)
- [ ] New source connector? Registered in `scrapers/__init__.py` and a test added under `tests/`
- [ ] Docs updated (`.env.example`, README) if config/behavior changed

## Notes for reviewer

<!-- Anything non-obvious, risky, or worth a second look. Iteration-level PRs
additionally record a DeliveryCycleReport (shipped / deferred / residual risks). -->
