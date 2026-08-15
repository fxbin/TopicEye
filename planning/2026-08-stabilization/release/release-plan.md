# Stabilization Release Plan

Parent: #2

## Release objective
Ship a trustworthy baseline before resuming feature-heavy iteration.

## Entry criteria
- Planning PR reviewed.
- #3 CI signal restored or actively blocking with reproduced evidence.
- P0/P1 bug severity model adopted.

## Release gates
1. Main/RC CI green on fresh run.
2. P0 backlog empty.
3. Security audit passes or every residual finding has reviewed owner/rationale/expiry.
4. Critical-flow smoke matrix passes.
5. Migration evidence recorded for any schema change.
6. Runtime reliability changes include restart/recovery/degraded-mode evidence as applicable.
7. Independent Verifier verdict PASS for release-scoped implementation PRs.

## Rollout order
`CI baseline → dependency security → regression matrix → runtime fixes → product bug burn-down`.

Prefer small revertible PRs. Do not bundle dependency upgrades, schema changes and lifecycle refactors into one release slice.

## Rollback
- Code: revert the smallest offending PR/commit.
- Dependencies: retain previous compatible lock/pin set and document downgrade constraints.
- Database: use Alembic downgrade only when the migration has been explicitly validated as reversible; otherwise follow a forward-fix/data-safe recovery plan.
- Runtime: scheduler/background changes must document whether rollback can duplicate/replay durable jobs.

## DeliveryCycleReport template
At the end of the cycle record:
- shipped issues/PRs;
- CI and smoke evidence;
- Verifier verdicts;
- security disposition;
- residual P1/P2 risks;
- rollback notes;
- deferred work and next-cycle proposals;
- workflow lessons to feed back into `virtual-intelligent-dev-team` if generally reusable.

## Exit criteria
Feature work can resume at normal velocity only after the baseline is demonstrably green and the issue/PR/verifier loop is operating in practice, not only documented.