# Agent Note: 不用 npm audit fix --force 清 eslint 工具链的 6 个 high

Status: rejected — 该修复会降级 Next.js eslint 插件栈，破坏性变更，收益不抵代价

## Problem

CI 的 `security-scan` 作业长期为红：6 个 high 漏洞，链路是
`eslint-config-next@16.2.6` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces`
（GHSA-vfj7-8cjw-p6xm，stack-exhaustion DoS）。

`npm audit fix --force` 报告能修，但它的方案是把 `eslint-config-next` **降到 14.2.35**——
从 16 退回 14，跨两个大版本。

## Proposal

执行 `npm audit fix --force`，接受降级。

## Alternatives considered

- **执行 `npm audit fix --force`。** 否决。这是**降级**不是升级：Next.js 主版本是 16，eslint 配置退回 14 会与 `next lint` / 插件规则集错配，且丢掉 15/16 新增的规则。工具链的「安全」不值得用「规则失效」换。
- **用 `overrides` 强压 `brace-expansion`。** 未验证。`braces` 的 glob 模式是 `*` 无上界，理论上无法静态证明修复有效；在没跑通之前不能写进 CI 门禁。
- **维持现状 + 显式声明预存红。** 采纳。`package.json` 与 main 逐字节一致，6 个 high 全在 dev-only 的 lint 工具链，**不进生产镜像、不接触运行时数据**。

## Consequences

- `security-scan` 保持红，成为已知预存红。合并 PR 时须在 Verifier verdict 段落显式声明，**不要把它误记成本次改动引入的失败**。
- 真正的修法是等上游 `fast-glob` / `micromatch` 发版，而不是从自己这端强行压版本。
- 若将来 `braces` 上游修复落地，`eslint-config-next` 随 minor 升级即可自然清零。

## Consequences（再次强调，勿重复踩）

看到 `npm audit` 报 high 就跑 `--force`，在依赖树较深的工具链里几乎总是错的：
**`--force` 给出的方案经常是降级而非修复。** 动手前先看它到底要改哪个包、往哪个方向改。

## Verification

- 复现：`cd frontend && npm audit --audit-level=high`
- 现状基线：`package.json` / `package-lock.json` 在 main 与功能分支逐字节一致
