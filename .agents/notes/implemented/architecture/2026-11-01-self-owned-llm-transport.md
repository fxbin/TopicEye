# Agent Note: 自建 LLM 传输层的可行性与边界

Status: implemented — 自有传输层是唯一实现，litellm 已退出运行时依赖（issue #204）

## Problem

本仓库用 LiteLLM 调 LLM。历史缺陷几乎全部集中在 litellm 的**模型名路由约定**上，
而不是它的网络传输能力：

- #83 `Provider NOT provided`——模型名含斜杠被当成 provider 路由
- 3ed5e1f / fc49ed0 / 2b3c773 反复补 `openai/` 前缀
- ffc654f 斜杠模型名兜底路由
- ba7250b `custom` 路由 + 容器回环地址重写

另有三项与路由无关、但同样由 litellm 引入的固有成本（本次实测）：

- **导入即联网**：litellm 导入时抓取远端模型价格表，失败重试 3 次。本机实测冷
  导入 6.9–13.8 秒，其中 `import app.services.llm` 单独就要 8.19 秒。
- **进程环境污染**：litellm 导入执行 `load_dotenv()`，把 `backend/.env` 写进
  `os.environ`。`backend/tests/test_config.py` 为此专门 `monkeypatch.delenv`。
- **依赖体量**：litellm 装 100MB，带 77 个传递依赖。

反过来看，本仓库真正需要的编排能力**已经是自己的代码**：`services/llm/` 下约
2500 行（failover、冷却、熔断、限流、预算、响应缓存、上下文预检、用量与计价、
调用轨迹）。litellm 在这里只承担三件事：发 HTTP 请求、把响应归一化、把 HTTP
错误映射成异常类。

## Decision

**做，但不是「重写 litellm」，而是把「传输」这一层从 litellm 里剥出来。**

litellm 在本仓库的调用面极窄，实测共 3 处 `acompletion`/`completion`、1 处
`provider_list`、7 个异常类。所以自研的成本不在于功能多，而在于**保住行为一致**。

本次落地的形状（issue #181，`LLM_TRANSPORT` 开关；**自 issue #200 起默认 `native`**）：

- 新增 `services/llm/adapters/`：自有错误分类、响应归一化、OpenAI 兼容协议实现
  （httpx 直连 `/chat/completions`）。
- 自有错误在边界处**映射回 litellm 的异常类型**，编排层（重试判定、failover、
  熔断、内容降级）一行都不用改，判定结论逐条一致——这是本次的核心约束。
- **按协议分流，不按 litellm provider 名单分流**。provider 列存的是 litellm
  provider 名，而那份名单随版本变动：实测 litellm 1.103.1 已无 `zhipu`（改名
  `zai`），而本仓库 `model_catalog_service` 仍把智谱 GLM 映射到 `zhipu`。
  自有路径只依赖「协议 + 端点」，不依赖那份名单。
- 不满足条件的 provider（缺 api_base，或配了 litellm 专属路由串与参数）
  **显式回落 litellm 并记 warning**，不静默换路径。
- 自 #185 起，anthropic 与 gemini 也有了自有协议实现，不再落在回落名单里；详见
  [补 anthropic / gemini 原生协议](2026-11-01-native-anthropic-gemini-protocols.md)。

## 生产切换（issue #200）

自研传输层在三个 PR 合并后（#181 OpenAI 兼容族、#185 anthropic / gemini、#194
去掉远端价格表拉取），把 compose 的默认值切到 `LLM_TRANSPORT=native`。

切换前的核实：

- **覆盖**：主链路的全部异步 LLM 调用都经过 `_call_engine` 的传输分派；**未覆盖**
  的是 A/B 评测与模型 ping 的**同步** `litellm.completion`
  （`api/v1/llm_evaluations.py` / `api/v1/llm_models.py`）——切换后两条路径混用。
- **线上模型不会回落**：`llm_models` 只有 1 行，provider=`custom`（在已实现协议内）、
  配了 `api_base`、`extra_params` 里既无 `litellm_params` 也无 `litellm_model`。
- **能力够用**：编排层只传 model / messages / temperature / max_tokens /
  num_retries=0，不用流式、不用 tools、不用 function calling。
- **真实端到端跑通**：同一模型、同一 OpenAI 兼容端点，两条路径各跑一次并落库
  比对——input_tokens、billable_input、input_cost 完全一致；output 差异来自模型
  两次采样的生成长度不同，不是计量差异。

**回滚**：设 `LLM_TRANSPORT=litellm` 后重启后端容器（改 compose 默认值或用环境
变量覆盖都行）。未经 compose 的部署（直接跑 uvicorn）读到代码里的保守默认
`litellm`，不受这次切换影响。

**长期存在的差异**（连接复用一项已由 #206 补上，见下文）：运行期出错（连接
失败、超时）**不会自动回落**，而是走编排层的重试 / failover——运行期偷偷换实现
会让语义漂移。（本段其余描述对应 #200 时刻的 litellm 依赖状态，随后由 #204 收掉。）

## 退役 litellm（issue #204）

生产切到 native 后，litellm 只剩三处用途：评测 / ping 的同步直连、不满足条件时的
回落、以及编排层判定所依赖的异常类型。这三处一次性收掉，litellm 退出运行时依赖。

四段切片（同一 PR、独立 commit、可逐个 revert）：

1. **同步路径**：新增 `provider.complete_once()`——单次、不重试、不 failover、不过
   熔断与限流，但经 `_call_engine` 同一传输分派。评测与 ping 改调它，评测测的就是
   生产跑的那条路径。
2. **传输唯一化**：删掉 `LLM_TRANSPORT` 开关与四处 `acompletion` 回落。配置不满足
   条件（provider 无协议实现 / 缺 api_base / 带 litellm 专属路由串或参数）抛
   `LlmConfigurationError`：候选级问题——冷却该候选、换下一个，不做 tenacity 重试，
   也不算「换路无解」的确定性请求错。默认网关补齐 deepseek / zhipu / minimax /
   moonshot / openrouter（取自精选目录，有镜像测试守卫）与 xai / mistral（官方端点；
   xai 用文档的 `/v1` 而非 litellm 的裸域名）。
3. **异常族翻转**：编排层判定改认 `adapters.errors` 自有类型，删 `to_litellm_exception`。
   自有族里 ContextWindow / ContentPolicy / UnsupportedParams 本就是 `LlmBadRequestError`
   子类，400/422 同归，判定语义不变。
4. **词汇表固化**：`model_resolver` 的斜杠模型名启发式改用 litellm 1.103.1 的 158 项
   provider 名单快照，不再 import litellm。

**parity 对照组怎么保住**：litellm 仍装在 dev 依赖组（不进生产镜像，`uv sync --no-dev`
排除）。`tests/llm_parity_oracle.py` 逐字保留 litellm 时代的三个判定函数；两套 parity
测试让真实 litellm 走完整异常映射链路，断言「新谓词(自有异常) is legacy 谓词(真实
litellm 异常)」——结论级对照，不是手写期望表。

**生产依赖集**：115 个包 → 83 个。

**回滚**：`LLM_TRANSPORT=litellm` 这条路径不存在了，回滚手段是 revert 合并提交。
存量部署若环境里还留着 `LLM_TRANSPORT` / `LITELLM_LOCAL_MODEL_COST_MAP`，
Settings 的 `extra="ignore"` 会忽略，不影响启动。

**不变的东西**：`extra_params.litellm_params` / `litellm_model` / `litellm_provider`
这些已落库的配置键名与语义全部保留（`num_retries` 变成无害的存量键，不再拒绝）；
目录接口的 `litellm_provider` 字段名保留；`request_model` 列继续记路由串。

**仍然没做**：azure / bedrock / vertex_ai 从「回落 litellm」变成「显式报错，
见 #190」——生产零使用，出现需求时按 #190 补自有适配器。连接池已由
[#206](https://github.com/fxbin/TopicEye/issues/206) 补上（见下文「连接复用」）。

## Alternatives considered

- **继续用 litellm，只加一层薄封装**：能挡住 litellm 升级带来的行为变化，但
  挡不住导入即联网、`load_dotenv` 污染与依赖体量——而这三项恰是本次想解决的成本。
- **直接换成 OpenAI SDK**：能拿到 OpenAI 兼容语义，但只覆盖 OpenAI 一家协议，
  国产厂商与聚合网关仍要自己写适配；且本仓库的 provider 覆盖面比 OpenAI SDK 广。
- **一次性删掉 litellm**：本次范围过大。anthropic / gemini 等原生协议尚无自有
  实现，A/B 评测与模型 ping 的同步调用路径也仍在用 `litellm.completion`。先做
  可回落的试点，拿到生产证据再谈删除。

## Consequences

- 试点本身的成本很低：`adapters/` 约 1030 行（其中大头是错误分类里逐条对齐
  litellm 的特征串与说明），`_call_engine.py` 只多了一个传输
  分派函数，编排层零改动。
- **`LLM_TRANSPORT=native` 不等于「不用 litellm」**：编排层仍按 litellm 的异常
  类型判定，litellm 仍是依赖。本次只是证明「传输层可以自己写，且行为能对齐」。
- **连接复用行为与 litellm 不同**（试点期记录，已由 #206 解决）：试点时每次
  请求新建 `httpx.AsyncClient`，每次调用多一次 TLS 握手。#206 起三个适配器共用
  一个按事件循环隔离的客户端（`adapters/http_pool.py`）：连接上限
  `LLM_HTTP_POOL_CONNECTIONS`（默认 16，超出排队）、空闲保活
  `LLM_HTTP_KEEPALIVE_SECONDS`（默认 300——httpx 自带的 5 秒对间隔几十秒的
  调用等于没复用）、超时仍按请求下发、停机时在后台任务 drain 之后关闭。
- 真正的收益要等生产验证：导入耗时、连接池行为、长稳下的错误分类一致性，都需要
  线上数据支撑，不能只凭单测断言。
- **zhipu 路由存在既有隐患**：litellm 1.103.1 不认 `zhipu`，`get_llm_provider`
  会直接抛 `Provider NOT provided`。本次未改动该路径（超出本 issue 范围），
  但自有传输层按协议处理，天然不受 provider 名单变动影响。
- 同步路径迁移与删除 litellm 依赖已由 #204 完成（见上文「退役 litellm」）；
  azure / bedrock / vertex_ai 的托管端点仍按需决策（#190）。
  （anthropic / gemini 原生协议已由 #185 补上。）

## Verification

- `backend/tests/test_llm_native_transport.py`（52 项）分四组断言：
  1. **错误分类 parity**：27 组 (HTTP 状态, provider 响应体) 用例，对照组是
     **真实 litellm**——用 litellm 自己的 `aclient_session` 注入点把 httpx 换成
     MockTransport，让 litellm 走完整的「发请求 → 解析错误 → 映射异常类型」
     链路，再比异常类型、`_should_retry`、`_is_deterministic_request_error`
     三项结论。**不手写期望表**：手写的表只能证明「实现和我的理解一致」，
     证明不了「实现和 litellm 一致」。
  2. 用量提取：同一份 usage 载荷，两条路径得到相同的 `TokenUsage`（计价口径
     不因传输实现而漂移）。
  3. URL 与模型名：8 个 provider 逐条与 litellm 一致；开关分派与回落行为。
  4. 开关取值：拼错的 `LLM_TRANSPORT` 必须显式报错，不能静默回落成 litellm
     （否则「以为在跑自有传输层」的部署实际仍在跑 litellm，而外部看不出来）。
- 对齐过程中查出并修掉的两处**语义漂移**（两条路径原本会给出不同的编排结论）：
  - 判定用的错误串必须是 openai SDK 那个 `Error code: {status} - {body}`，其中
    `{body}` 是**解析后的 JSON 再按 Python repr 渲染**——按原始响应文本匹配会
    漏判 JSON 里被转义成 `\uXXXX` 的中文。
  - 异常**消息**要用 provider 那句可读文本（litellm 同源），不能用上面那个
    大串：仓库的 `_is_bad_request_error` 认 `"error code: 400"`，litellm 的
    `NotFoundError`（400 + model_not_found）消息里没有这句，混用会让同一个
    provider 响应在一条路径下「确定性错误不重试」、在另一条路径下「重试」。
- parity 用例自身踩到并修掉的一个 litellm 坑：litellm 把 openai SDK client
  缓存在 `in_memory_llm_clients_cache`，缓存键里带**事件循环 id**。循环被回收后
  id 会复用，于是后面的用例命中前一个用例留下的 client（包着已关闭的 mock 连接），
  请求变成真实网络连接、报 `Connection error.`。实测 810 次比较里出现 779 次
  不一致。修法：每次比较前清缓存 + 每次调用用唯一 api_key。修后 810 次 0 不一致，
  pytest 连跑 6 轮全绿。
- 守卫有牙齿：5 组定向变异（去掉上下文超窗的排除规则、去掉限流的状态码闸门、
  内容策略错误改判普通 BadRequestError、异常消息改回大串、去掉 model_not_found
  分支）逐一把 parity 测试打红，改回后全绿。
- litellm 对照基线用 httpx mock 抓取真实调用（URL、请求体、异常类型），
  逐条比对，不是靠读代码推断。
- `make lint`（ruff + 分层 + 评分口径 + 刊名口径 + tsc）全过；
  `check_layering.py` / `check_scoring_mirror.py` / `check_edition_naming.py` /
  `check_agent_docs.py` 全过；后端全量测试通过（`tests/test_source_url_safety.py`
  的 2 个失败是**基线即存在**的既有问题：把本次改动全部移开后在 main 基线上
  同样失败，与本次改动无关）。

相关：[LLM 调用与计费口径](../feature/2026-10-24-content-event-contract.md) 记录用量与调用轨迹的
既有合同；本次未改动该口径，只保证两条路径产出相同结果。
