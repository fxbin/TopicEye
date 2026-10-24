# Agent Note: 依赖审计口径与例外复核合同

Status: implemented — #151 按所有者明确要求迁移既有入口；不改变运行或生产授权

## Problem

依赖扫描的批准例外需要独立、可检索的维护入口；不能因旧文档退役而扩大豁免。

## Decision

本篇维护下列合同；修改对应行为时同步核对，参数与安全边界沿用迁移前原文。

当前可执行门禁以 [CI workflow](../../../../.github/workflows/ci.yml) 的 security-scan 为准。
修改依赖或审计策略时核对本页；具体版本以锁文件为准，漏洞是否仍存在必须重新审计，不由历史笔记推断。

## 执行与批准的例外

- 后端使用 frozen 同步后的 `pip-audit`，失败不得忽略。
- 前端当前执行 `npm audit --audit-level=high --omit=dev`，生产依赖的 high 级门禁维持严格阻断。
- dev 依赖豁免来自 eslint 工具链中 braces 的 DoS 告警，不适用于生产依赖，也不能推广为“dev 漏洞都不用处理”。
- 原批准例外的复审条件是 braces 上游提供补丁（原记录为高于 3.0.3）：须核对上游与实际依赖树，优先正常升级，并在验证后恢复全量审计口径。不能只凭旧版本数字或旧扫描报告判断满足条件。
- 不为通过 CI 静默扩大豁免或降低门槛。新红先核对当前 advisory 和真实依赖路径，再按权限处理。

禁止以 `npm audit fix --force` 的“可修复”提示代替依赖变更审查。
历史否决原因见 [eslint 栈降级方案](../../rejected/risk/2026-09-28-npm-audit-force-downgrades-eslint-stack.md)；该文保留当时判断，不是当前扫描状态真源。

## 已处理告警的历史线索

以下仅迁移原 AGENTS 中的追溯信息，不宣称当下所有漏洞均已修复：

| 记录 | 追溯入口 |
|---|---|
| multidict 6.9.0 告警 | [issue #99](https://github.com/fxbin/TopicEye/issues/99) |
| Next.js 16.3.8 的 RCE/DoS 告警，处理版本 16.4.1 | [issue #142](https://github.com/fxbin/TopicEye/issues/142) |
| filelock 4.0.1 的三条告警，处理版本 4.2.1 | [issue #144](https://github.com/fxbin/TopicEye/issues/144) |

具体依赖事实源是 [backend/uv.lock](../../../../backend/uv.lock) 与
[frontend/package-lock.json](../../../../frontend/package-lock.json)。历史修复不构成当前安全证明；当前状态看最新 audit 与 CI。

## Alternatives considered

只删除文档而保留断链或省略合同：不采用，入口收敛不能丢失使用边界。

## Consequences

CI workflow 和锁文件仍是当前执行事实；历史漏洞版本不是当前安全证明。本次未执行升级、审计策略变更或外部扫描。
