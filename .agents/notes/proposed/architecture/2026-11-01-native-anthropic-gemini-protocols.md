# Agent Note: 自有传输层补 anthropic / gemini 原生协议

Status: proposed — 两个第一方协议的自有实现已落地（开关默认关闭），未在生产启用

## Problem

issue #181 把「传输」这一层从 litellm 里剥出来，做了 OpenAI 兼容族的自研实现
（PR #184）。当时 anthropic / gemini / azure / bedrock / vertex_ai 走**显式回落
litellm + warning**——功能是通的，但那意味着「删 litellm」这条路在这几家上仍然
被 litellm 的协议实现卡着。

本 note 记录补 anthropic（`/v1/messages`）与 gemini（`generateContent`）两个
第一方协议的决定与口径。

## 事实（实测，不是推断）

- **线上 anthropic / gemini 用量为 0**：`llm_call_logs` 17758 条全部是
  `provider=custom`，`llm_models` 只有 1 行（MiniCPM 5-2B）。所以本项的价值是
  「为删 litellm 铺路」，**不是**立刻降本或提效。
- litellm 1.103.1 对这两家有**各自独立**的协议实现与异常映射
  （`_map_anthropic_exception` / `_map_vertex_exception`），与 OpenAI 兼容族不同源。
- 仓库的 `extract_usage` 本就认 anthropic / gemini 的原生 usage 字段名
  （`input_tokens` / `output_tokens` / `promptTokenCount` /
  `candidatesTokenCount` / `cache_read_input_tokens` /
  `cachedContentTokenCount`），这条链路不需要改。

## Decision

**补两个第一方协议，按协议分流，其余协议继续显式回落 litellm。**

- 新增 `services/llm/adapters/anthropic_native.py` 与 `gemini_native.py`：
  请求体映射、响应归一化、错误分类各自一套。
- registry 改成 provider → 协议实现的映射表（`PROTOCOL_BY_PROVIDER`），
  `azure` / `bedrock` / `vertex_ai` 仍在回落名单里。
- 沿用 #181 的形状：自有错误在边界处映射回 litellm 异常类型，编排层（重试判定、
  failover、熔断、内容降级）零改动。
- 验证方式沿用 #181：**parity 对照组是真实 litellm**（拦 httpx 让 litellm 自己
  走一遍协议栈，再逐条比 URL / 头 / 请求体 / 异常类型 / 编排结论）。

### 三个必须记下来的口径

**1. 403 在两家的归类相反，直接改变编排结论。**

| provider | litellm 给的异常 | 是否算确定性错误 |
|---|---|---|
| anthropic | `PermissionDeniedError` | **否** → 可重试 |
| gemini | `BadRequestError` | **是** → 不重试、不降级 |

anthropic 的 403 之所以可重试，是因为 `PermissionDeniedError` 不在编排层的
确定性错误清单里（`_call_engine._is_deterministic_request_error`）。gemini 的 403
判成 `BadRequestError` 是因为 litellm 靠「响应体里出现 `403` 字样」命中——判定
形状不同，结论就相反。自家路径逐条复刻。

**2. anthropic 的 usage 给原生形状，计费按 Anthropic 的原生口径。**

litellm 把 anthropic 的 `input_tokens` + `cache_read_input_tokens` +
`cache_creation_input_tokens` 合并成 OpenAI 形状的 `prompt_tokens`（含缓存）。
在本仓库的计价函数里，anthropic 走的是「input 不含缓存、不减」分支
（`_input_tokens_include_cache`），于是 litellm 路径会把缓存部分**同时按 input
价和缓存价各算一遍**。

Anthropic API 的原生口径是：`input_tokens` 不含缓存，缓存读/写是各自独立的
字段。自家路径给 Anthropic **原生** usage，与这个口径一致，也与本仓库计价
函数的 anthropic 分支一致 → 金额正确。

litellm 路径的重复计费是**既有问题**，本次不改（会改变既有部署的金额口径，
且线上 anthropic 用量为 0，改了也没有实际影响），另开 issue 记录：
[#189](https://github.com/fxbin/TopicEye/issues/189)。

**3. gemini 的 `promptTokenCount` 含缓存，仓库的计价分支会减掉。**

Google 文档口径：`promptTokenCount` 是输入 token 总量，**含**缓存，
`cachedContentTokenCount` 是其中的缓存部分。本仓库对非 anthropic provider
走「input 含缓存、要减」分支 → 减掉后即为不含缓存的输入，金额与 gemini 侧的
原生语义一致，两条路径的数字也一致。

### 一处刻意保留 litellm 的怪癖

litellm 对 anthropic **静默丢弃** `response_format`（实测请求体里没有）。自家
路径照做——不静默丢弃 litellm 丢弃的东西，否则两条路径的行为就不一样了。gemini
侧则把 `{"type": "json_object"}` 映射成 `generationConfig.response_mime_type`，
其它形状（json_schema 等）由 registry **显式回落** litellm。

## Alternatives considered

- **一次性把 azure / bedrock / vertex_ai 也补了**：范围过大，且它们的认证与端点
  与第一方不同（vertex 要处理 project/location 与 token 交换，bedrock 要 AWS
  SigV4 签名），另开 issue：[#190](https://github.com/fxbin/TopicEye/issues/190)。
- **直接删 litellm**：本 issue 之前就排除过——同步路径（A/B 评测、模型 ping）
  仍在 `litellm.completion` 侧，且 anthropic / gemini 的协议实现刚补完，先拿到
  生产证据。
- **复用 litellm 的 transformation 做映射**：那样自研层就仍然依赖 litellm 的
  协议实现，「删 litellm」的前提不成立。

## Consequences

- 自研层覆盖到线上最主流的一类协议之外，又多了两家第一方 provider；剩余的
  azure / bedrock / vertex_ai 仍回落 litellm。
- **计费口径出现一处有意的不一致**：anthropic 在两条路径下的 `TokenUsage` 数字
  不同（自研 100 / litellm 150），但**金额**一致且自研侧正确。若将来把
  litellm 路径的重复计费修掉，两边就完全一致了。
- gemini 侧只复刻 `json_object` 这一种 `response_format`，其余显式回落——
  不静默改变请求语义。
- 自有实现仍然每次请求新建 `httpx.AsyncClient`（不复用连接），与 #181 相同，
  长期启用前需要接上连接池。

## Verification

- `backend/tests/test_llm_native_anthropic_gemini.py`（31 项）：
  - **请求 parity**：URL、鉴权头、请求体逐字段与 litellm 真实请求一致
    （anthropic 10 个用例、gemini 10 个用例逐条比对）。
  - **错误分类 parity**：18 组 (状态码, 响应体) 用例，比异常类型 + `_should_retry`
    + `_is_deterministic_request_error` 三项结论。
  - **响应归一化**：文本块拼接、thinking 进 reasoning_content、usage 提取。
  - **计费口径**：anthropic 的缓存读写单独计价、gemini 的含缓存输入减掉。
  - **registry 分流**：三家已实现协议走自有，未实现的显式回落。
- 7 组定向变异逐一把守卫打红（改 403 归类、去掉 gemini 的 403/配额规则、system
  不抽到顶层、缓存写入不合并、assistant 角色名不映射、json_object 不映射）。
- litellm 的对照基线用 httpx mock 抓真实调用取得，不是读代码推断。

相关：[自建 LLM 传输层的可行性与边界](2026-11-01-self-owned-llm-transport.md)
记录 #181 的整体形状；本次是在其上的协议扩展。
