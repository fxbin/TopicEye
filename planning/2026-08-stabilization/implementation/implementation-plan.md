# Stabilization Implementation Plan

Parent: #2

## Delivery loop
For every meaningful fix:
`Issue/WorkOrder → issue branch → Worker → focused tests → full relevant CI → PR → independent Verifier → remediation/re-verify → merge`.

## Phase 0 — Restore signal
1. Complete #3 as formatting-only change.
2. Re-run full CI and capture every resulting job conclusion.
3. Any newly exposed unrelated failure becomes a linked issue.

## Phase 1 — Dependency security
1. Complete #4 from a clean dependency resolution.
2. Build package/advisory/fixed-version matrix.
3. Upgrade smallest compatible groups.
4. Regression-test auth/OAuth, multipart/file/PDF handling and FastAPI/Starlette request behavior.

## Phase 2 — Defect discovery contract
1. Complete #5 bug matrix.
2. Reproduce user-reported defects on a defined environment.
3. Create dedicated P0/P1 issues with exact acceptance criteria.
4. Prefer regression-first implementation when a deterministic reproduction is possible.

## Phase 3 — Runtime reliability
Run #6 audit in slices: startup/shutdown; scheduler ownership; source lease; analysis recovery; background tasks; health semantics; external-I/O isolation. Behavioral fixes are split to dedicated bug issues.

## Phase 4 — Product burn-down
Prioritize: severity → user impact → reproducibility → blast radius. Parallel FE/BE work only when the API/data contract is stable.

## Branch/PR convention
- Branch: `issue-<number>-<short-slug>`.
- One primary issue per implementation PR.
- No direct-to-main normal delivery.
- PR includes: WorkOrder, diff summary, test evidence, risks/rollback, verifier section.

## Worker handoff
Worker receives: issue link, allowed paths/boundaries, non-goals, acceptance criteria and required commands/checks. Worker must report deviations rather than silently widening scope.

## Verifier handoff
Verifier receives the original WorkOrder plus Worker evidence. Verifier validates behavior and scope independently; a failed verdict returns a concrete remediation list/patch to Worker and requires re-verification.

## Parallelization policy
Safe parallel streams: security analysis, bug reproduction, frontend UX reproduction and documentation. Avoid simultaneous conflicting edits to `main.py`, scheduler/job lifecycle code, migration heads or shared dependency pins.
