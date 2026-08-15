# Bug Reproduction Matrix

Parent: #2 · Owner: #5

> Rule: only reproduced defects become implementation bugs. Suspicions remain investigation rows until evidence exists.

| ID | Severity | Symptom / user impact | Environment | Reproduction | Expected | Actual | Boundaries | Evidence / correlation ID | Repro rate | Regression test | Owner issue | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE-001 | P0 | Main CI cannot reach a trusted green baseline | GitHub Actions, main `597fb293...` | Run workflow 31603354158 | lint gate passes and downstream jobs complete | Ruff formatting gate fails on `backend/tests/test_today_picks.py`; backend test step cancelled by fail-fast | CI / backend tests | run 31603354158 | 100% for verified run | Ruff format check + fresh CI | #3 | confirmed |
| SECURITY-001 | P0 | Security gate blocks baseline | GitHub Actions | Run pip-audit in security job | no actionable known-vulnerability findings | 69 findings across 7 resolved packages in verified run | dependencies / auth / parsers / ASGI | run 31603354158 | 100% for verified run | security audit + compatibility smoke | #4 | confirmed |

## Row rules

- **confirmed**: exact reproduction/evidence exists.
- **intermittent**: reproduced more than once but not deterministically; capture request/job/source IDs and timestamps.
- **investigating**: user report or code smell without adequate reproduction; do not implement speculative behavior changes.
- **fixed-awaiting-verification**: Worker evidence exists but independent Verifier has not passed it.
- **verified**: acceptance criteria and regression evidence passed independent verification.

## Critical journey checklist

- [ ] Auth/session/OAuth
- [ ] Source create/configure → manual/scheduled sync → persistence
- [ ] Extraction → enrichment → classification
- [ ] Analysis enqueue → recovery/dispatch → terminal state
- [ ] Today Picks read → mark/feedback
- [ ] Trending sync → snapshot/read
- [ ] DuckDB unavailable → OLTP fallback
- [ ] Startup migration → scheduler/degraded modes → graceful shutdown
- [ ] Primary frontend loading/error/empty/success states
