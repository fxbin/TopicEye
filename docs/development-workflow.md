# TopicEye Development Workflow

This repository uses the delivery model from `virtual-intelligent-dev-team` for meaningful changes.

## Default loop

`Issue / WorkOrder → issue branch → Worker → tests/evidence → PR → independent Verifier → remediation/re-verify → merge → DeliveryCycleReport`

## 1. Issue / WorkOrder

Before implementation, define:
- context and reproduced evidence;
- scope and non-goals;
- acceptance criteria;
- verification plan;
- risks and rollback considerations.

Do not convert an unverified suspicion into a behavioral fix. Investigation may precede the bug issue when reproduction is uncertain.

## 2. Branch

Use a branch linked to the primary issue, preferably:

`issue-<number>-<short-slug>`

Avoid direct-to-`main` delivery as the normal workflow.

## 3. Worker

The Worker implements the smallest change that satisfies the WorkOrder. It must:
- preserve repository layering and `AGENTS.md` constraints;
- avoid unrelated refactors;
- add or update regression coverage when practical;
- report exact tests/checks and deviations from the original scope;
- document migration/security/lifecycle impact when applicable.

## 4. Pull request

Every meaningful PR links its primary issue and fills `.github/pull_request_template.md`.

One PR should have one primary reason to exist. Split dependency upgrades, schema changes and lifecycle rewrites unless they are inseparable from the same reproduced root cause.

## 5. Independent Verifier

The Verifier is a separate verification pass and must judge the original WorkOrder, acceptance criteria and actual diff/evidence.

Possible verdicts:
- `PASS`: acceptance criteria satisfied; residual risks documented.
- `FAIL`: concrete remediation is required; the PR returns to the Worker and is re-verified after changes.

The implementation pass must not self-declare independent verification.

## 6. Merge gate

Before merge:
- relevant CI/checks are green;
- verifier verdict is PASS;
- unresolved review threads are handled;
- schema migrations have required forward/rollback evidence;
- security findings introduced/affected by the change are dispositioned;
- rollback path is understood.

Repository admins should configure branch protection/rulesets to enforce required checks/reviews where available. The GitHub integration used to create this document cannot inspect the current branch-protection state, so the repository admin remains responsible for confirming those settings.

## 7. DeliveryCycleReport

At completion record:
- shipped outcome;
- tests/CI evidence;
- verifier verdict and residual risk;
- deferred/follow-up issues;
- rollback notes;
- reusable lessons that should feed back into the team Skill.

## Emergency fixes

If an emergency requires bypassing part of the normal sequence, minimize scope and create/attach the issue and verification evidence immediately afterward. Emergency delivery is an exception, not a parallel default workflow.
