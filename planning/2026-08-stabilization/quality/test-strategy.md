# Stabilization Test Strategy

Parent: #2 · QA inventory: #5

## Test pyramid for this cycle

### Unit
Pure parsing/classification/scoring/state-transition logic; no public network, no real external providers.

### Integration
PostgreSQL repository/transaction boundaries, Alembic forward/rollback where changed, scheduler/job persistence and recovery, API contracts using controlled dependencies.

### Smoke / critical-flow
1. auth/session/OAuth
2. source → sync → persisted content
3. extraction/enrichment/classification
4. analysis enqueue/recovery/completion
5. Today Picks read + mark/feedback
6. trends sync/snapshot read
7. DuckDB unavailable → OLTP fallback
8. startup migration → scheduler state → shutdown
9. primary frontend loading/error/empty/success states

## CI gate policy
- Ruff formatting/lint must pass before interpreting downstream failures.
- Backend PostgreSQL tests must complete, not merely be skipped/cancelled.
- Frontend tests/build must complete.
- Migration check must complete.
- Security checks must pass or have explicit reviewed dispositions.

## Bug regression rule
For deterministic P0/P1 bugs, add a failing regression test before or in the same PR as the fix whenever practical. A bug is not considered verified solely by code inspection.

## Network isolation
Default unit/integration CI must not depend on public internet availability. Mock/fake HTTP, OAuth, LLM and source endpoints. Any intentionally live external test must be separately marked and must not be a hidden prerequisite for the default suite.

## Concurrency/lifecycle cases
Test cancellation, timeout, retry/recovery, duplicate-dispatch protection, stale source-sync lease recovery, scheduler disabled mode and degraded DuckDB mode.

## Migration policy
If schema changes occur: prove upgrade from supported previous revision, current `head`, and rollback path according to repository migration policy. Do not combine unrelated schema changes with bug fixes.

## Verifier evidence
Each implementation PR records exact commands/checks, conclusions and relevant run links/IDs. Verifier independently checks the acceptance criteria and records PASS/FAIL plus residual risk.