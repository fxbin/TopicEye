# Agent Note: PR 合并不等于 issue 关闭

Status: implemented — PR 模板已改默认写 `Fixes #NN`，AGENTS.md 补入关闭步骤

## Problem

2026-09-29 PR #89 合并后，Issue #88 仍是 OPEN。当时的判断依据是「PR 合并了所以事情做完了」——但 PR 模板第 5 行写的是 `Refs #<issue>`，GitHub 对 `Refs` **不触发自动关闭**，对 `Fixes` / `Closes` 才触发。

一个 slug 字母之差，让登记册与 GitHub 状态静默分叉。而 AGENTS.md 当时的 Delivery Workflow 只写到「合并」就没了，**从没说要确认 issue 关闭**。

## Decision

1. PR 描述默认写 `Fixes #NN`（需要 issue 继续跟踪时才用 `Refs`，且必须在正文写明后续批次）。
2. Delivery Workflow 补一步：合并后核对 `gh issue view N --json state`，不凭「PR merged」推断。
3. **合并成功不等于 issue 已关闭。** 这条要单独说，因为它是反直觉的——符合直觉的推断恰好是错的。

## Alternatives considered

- **加 CI 检查：PR 关联的 issue 必须 closed。** 否决：合并时 issue 本来就该是 open 的（PR 还没合），检查时机不对；真要查应该是「PR 合并后 issue 是否自动关闭」，这依赖模板文本，CI 查不了。
- **用 GitHub Actions 自动 close。** 否决：把流程正确性外包给一个可能失效的 workflow，不如把规则写进模板 + 交付流程。模板是人读的，CI 拦的是代码错误，两者分工不同。
- **在回归矩阵里记一条「#88 已修复」就够了。** 否决：矩阵记状态、issue 记生命周期，两个真源分叉就是这次事故的根因。

## Consequences

- 写 issue 成了真正的动作，而不只是记录动作。
- 代价：每条 PR 描述要多想一步用 `Fixes` 还是 `Refs`。
- 关联：`.agents/notes/implemented/process/2026-09-28-three-gate-approval.md`（三道闸门是同一类「流程靠自觉就会失守」的加固）

## Verification

- 模板默认文本：`.github/PULL_REQUEST_TEMPLATE.md` 第 5 行为 `Fixes #<issue>`
- 实际效果：PR #89 合并后 `gh issue view 88 --json state` 返回 `CLOSED`（`closedAt: 2026-09-29T23:01:16Z`）
