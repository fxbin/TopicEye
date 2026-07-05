## What & why

<!-- One or two sentences: what does this change do, and why? -->

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

## Checklist

- [ ] Commits follow Conventional Commits (`feat(auth): ...`) — see [AGENTS.md](../AGENTS.md)
- [ ] No local-only files staged (`.env`, `*.db`, `venv/`, `node_modules/`, screenshots)
- [ ] New source connector? Registered in `scrapers/__init__.py` and a test added under `tests/`
- [ ] Docs updated (`.env.example`, README) if config/behavior changed

## Notes for reviewer

<!-- Anything non-obvious, risky, or worth a second look. -->
