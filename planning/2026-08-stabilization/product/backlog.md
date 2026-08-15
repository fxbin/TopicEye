# Stabilization Backlog

Parent: #2

## Priority order

| Priority | Issue | Outcome | Dependency |
|---|---|---|---|
| P0 | #3 Restore green main | Remove current Ruff gate; re-establish complete CI evidence | none |
| P0 | #4 Dependency vulnerabilities | Upgrade/disposition vulnerable packages with compatibility coverage | #3 preferred first so CI signal is readable |
| P1 | #5 Bug inventory & regression matrix | One reproducible contract per confirmed defect | can start in parallel |
| P1 | #6 Runtime reliability | Harden scheduler/jobs/lifecycle from reproduced evidence | #5 informs bug splits |
| P1 | #7 GitHub delivery workflow | Make Issue→branch→PR→Verifier the default path | start immediately |

## Execution waves

### Wave 0 — Trusted baseline
- #3 formatting-only Worker PR.
- Fresh full CI run.
- Split any newly exposed failure into its own issue.

### Wave 1 — Security baseline
- #4 capture full advisory matrix.
- Upgrade smallest compatible dependency groups.
- Verify auth/OAuth, uploads/PDF, ASGI request handling, migrations.

### Wave 2 — Reproduction and regression
- #5 inventory user-reported and discovered bugs.
- Convert P0/P1 rows into dedicated implementation issues.
- Add tests at the lowest useful layer: unit for logic, integration for DB/job boundaries, E2E/smoke for user-critical journeys.

### Wave 3 — Runtime reliability
- #6 startup/shutdown, scheduler ownership, source lease, analysis recovery, background task lifecycle, external-I/O isolation.
- Behavioral changes require a reproduced defect issue; do not hide multiple fixes in one hardening PR.

### Wave 4 — Product bug burn-down
- Work P0 first, then P1 by user impact × reproducibility × blast radius.
- FE and BE may run in parallel only when API/data contracts are explicit.

## Issue template for newly reproduced bugs

Every new bug issue should contain:
1. Symptom / user impact.
2. Environment and preconditions.
3. Exact reproduction steps.
4. Expected vs actual.
5. Evidence: request ID/job ID/log/API payload/screenshots as relevant.
6. Suspected boundaries, not speculative root cause.
7. Acceptance criteria.
8. Regression test plan.
9. Risks/rollback.
10. Verifier requirements.

## WIP policy

- Keep P0 Worker WIP intentionally low: finish/verify before opening another risky P0 implementation.
- Parallelize independent discovery/testing work, not conflicting edits to shared lifecycle/core files.
- One PR should have one primary reason to exist.
