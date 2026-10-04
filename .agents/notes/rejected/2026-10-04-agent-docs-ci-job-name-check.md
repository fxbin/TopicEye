# Agent Note: AGENTS.md 引用校验只查路径与 make 目标，不查 CI 作业名

Status: rejected — 作业名与分支名、npm 包名同形，三次修补后仍同时误报与漏报

## Problem

`AGENTS.md` 是喂给 agent 的指令文件，命令与路径过期等于静默的错误。加
`backend/scripts/check_agent_docs.py` 机器化校验时，原本规划三类：

1. 仓库内文件路径
2. `make` 目标
3. CI 作业名

第 1、2 类靠变异测试确认有效（注入坏路径与坏 make 目标都被杀掉）。第 3 类不行。

## Proposal

用 `check_ci_jobs` 校验 AGENTS.md 里提到的 CI 作业名在 `.github/workflows/ci.yml` 里存在。

## Alternatives considered

- **按措辞判定**（要求候选名同行出现「作业」二字）。否决：`security-scan` 在本文里
  恰恰出现在「五项检查（types / tests / lint / layering / security-scan）」这种纯列举的
  上下文里，没有「作业」二字，直接漏报。
- **按依赖链上下文判定**（该名字出现在 `->` 箭头或 npm 链路行则放过）。否决：修好了
  `eslint-config-next` / `fast-glob` 的误报，但随即把分支名示例 `issue-4-cryptography-50`
  判成作业名，误报。
- **排除 `issue-` 前缀。** 否决：压住了上面那个误报，但注入的 `security-scanx` 变异
  存活——漏报没修，只是把误报挪了个位置。
- **保留路径 + make 两类，作业名改人工核对。** 采纳。

## Consequences

- `check_ci_jobs` 与配套的 `is_dependency_chain_context` 已从脚本删除，`CI_WORKFLOW`
  常量一并摘掉。脚本 docstring 记录了这段失败史，避免以后有人重新加回来。
- AGENTS.md「4.4 Verifier 契约」里的作业清单由五项变六项（新增 `agent-docs`），
  这一处是**手改**的——它正是自动校验覆盖不到的那一类。
- 一个会误报的门禁比没有更糟：它训练 agent 忽略检查结果，而忽略检查结果这件事，
  代价要等到真的漏掉一次才显现。

## Verification

- 变异测试脚本：`/tmp/topiceye-rewrite/mutation_check_agent_docs.py`（临时目录，不入库）
- 基线 + 5 个注入用例：应杀的 3 个全部杀掉，2 个已知盲区确认杀不掉且符合预期
- `cd backend && uv run python scripts/check_agent_docs.py ../AGENTS.md` 通过
