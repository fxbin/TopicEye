# TopicEye 2026-08 Stabilization PRD

Parent issue: #2
Status: planning / repository truth

## 1. Problem statement

TopicEye has evolved into a production-shaped system spanning frontend UX, FastAPI APIs, PostgreSQL/SQLite support, Alembic migrations, scheduled source synchronization, DB-backed analysis jobs, DuckDB analytics fallback, LLM processing and external-content ingestion. The current delivery baseline is not trustworthy enough for continued high-frequency AI-assisted development: the latest verified `main` workflow is red, the dependency audit fails, and broad bug fixing lacks a single reproducibility matrix.

The product problem for this iteration is therefore not “add more features”. It is: **make TopicEye safe to iterate quickly**.

## 2. Goals

1. Restore a green, reproducible `main` baseline.
2. Reduce known dependency-security exposure without introducing untested compatibility regressions.
3. Convert reported/observed bugs into reproducible contracts instead of ad-hoc fixes.
4. Establish regression coverage for the most business-critical paths.
5. Harden lifecycle-heavy areas: scheduler, background jobs, recovery, degraded mode and shutdown.
6. Adopt the virtual-intelligent-dev-team GitHub delivery loop as the default workflow.

## 3. Success metrics

- Main branch CI: 100% required jobs green for the stabilization release candidate.
- P0 defects: 0 open at release.
- P1 defects: either closed or explicitly deferred with owner/rationale.
- Security audit: no unowned actionable finding.
- Critical-flow matrix: every flow has owner + smoke/regression evidence.
- Delivery traceability: meaningful changes have Issue → branch → PR → verification evidence.
- No stabilization PR merges with an unresolved Verifier `FAIL` verdict.

## 4. User-critical journeys

1. Authenticate and retain a valid session.
2. Add/configure a source and trigger sync.
3. Fetch/extract/enrich/classify content and persist it correctly.
4. Queue analysis work and survive process/job interruption.
5. Browse Today Picks and perform mark/feedback actions.
6. Sync and view trends/snapshots.
7. Continue core reads when DuckDB is unavailable through the intended OLTP fallback.
8. Start a deployment, migrate safely, become healthy, run scheduler work, and shut down cleanly.
9. See usable loading, empty, error and success states in the primary frontend flows.

## 5. Scope

### In scope
- CI baseline recovery.
- Dependency remediation.
- Bug inventory and reproduction contracts.
- Regression/smoke test additions.
- Runtime reliability fixes that are backed by reproduced evidence.
- Workflow/governance documentation and PR verification loop.

### Out of scope
- Feature expansion unrelated to stabilization.
- Broad UI redesign.
- Replacing APScheduler, the ORM, or the current overall architecture without defect evidence.
- Performance rewrites without measurements.

## 6. Severity model

- **P0**: blocks CI/release, data corruption/loss, critical security exposure, system unavailable, or critical journey unusable.
- **P1**: major user journey broken/intermittent, repeated background-job failure, serious correctness/reliability issue with workaround at best.
- **P2**: degraded UX/correctness with reasonable workaround; not release blocking by default.
- **P3**: polish, low-frequency edge cases, observability/documentation improvements.

## 7. Delivery contract

Every meaningful change follows:

`Issue / WorkOrder → issue branch → Worker implementation → tests/evidence → PR → independent Verifier → remediation loop if needed → merge → DeliveryCycleReport`

The same implementation pass must not self-declare independent verification.

## 8. Release gate

The stabilization release is eligible only when:

- current CI failures are resolved;
- security findings are remediated or explicitly dispositioned;
- P0 backlog is empty;
- critical smoke matrix passes;
- migration forward/rollback evidence is recorded where migrations changed;
- Verifier verdict is PASS for release-scoped implementation PRs;
- residual risks and deferred P1/P2 items are written into the release report.
