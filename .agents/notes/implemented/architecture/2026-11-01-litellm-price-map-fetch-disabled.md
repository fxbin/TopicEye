# Agent Note: 关掉 litellm 启动时对远端模型价格表的拉取

Status: implemented — 已随 #204 退役 litellm 而失效：变量与 compose 条目移除，运行时不再导入 litellm

## Problem

litellm 在**模块导入时**就会拉取远端模型价格表
（`raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`），
失败重试 3 次（退避 2s / 4.8s）。本机与容器内实测（容器用 `--network none`
模拟最坏情况）：

| 场景 | `import litellm` | 编排层 import | 外部请求 |
|---|---|---|---|
| 远端可达，未设开关 | 4.75 s | — | 1 次（成功） |
| 远端不可达，未设开关 | 9.97 s | 10.80 s | 3 次失败 + 回落 |
| 开关打开 | 3.17 s | 3.10 s | **0 次** |

「远端不可达」不是假想：本机实测 `raw.githubusercontent.com` 多次 SSL 失败。
而它把**启动成败挂在一个外部端点上**——GitHub 抖动时，每次启动都多花近 8 秒
并刷 3 条 WARNING。

## Decision

**部署层设 `LITELLM_LOCAL_MODEL_COST_MAP=True`，不再联网拉远端那份，改用 litellm
随包的本地备份。**

### 为什么放部署层，不放代码

litellm 读的是环境变量，且读时机在 import 时。两种放法的差别不在「要不要设」，
而在**谁还能改它**：

- **代码里 `os.environ.setdefault(...)`**：它跑在 `app.core.config` 之前，但
  **早于 litellm 自己的 `load_dotenv()`**——`.env` 里显式写的值那时还没进
  `os.environ`，于是 setdefault 先占位、而 litellm 的 `load_dotenv()` 默认
  `override=False` 不覆盖 → **`.env` 里写 `False` 失效**。
- **compose 的 `environment:` 段**：进程启动前就注入，`os.environ` 里已有该键，
  compose 的 `${VAR:-True}` 还能让用户在根 `.env` 或 shell 里显式覆盖 →
  **可恢复**。

所以放 compose：`docker-compose.yml` 与 `docker-compose.prod.yml` 的 backend
`environment:` 段各加一行，`backend/.env.example` 写明它是什么、怎么恢复。
本地开发也是 `docker compose up`（Makefile 的 `dev` 目标），开发与生产一次覆盖。

### 为什么这份表对我们没用

1. **我们的计价早就不依赖它**：全仓库没有任何地方读 `litellm.model_cost` /
   `get_model_info` / `response_cost`。计价走 `pricing_from_model` →
   `normalized_model_pricing` → `llm_models` 表 + models.dev 目录表
   （见 [LLM 调用与计费口径](../feature/2026-10-24-content-event-contract.md)）。
2. **线上唯一的模型不在表里**：`minicpm5-2b` 调 `get_model_info` 直接抛
   `This model isn't mapped yet`——那份表对我们唯一的生产模型没有任何上下文
   窗口或价格信息可用。
3. **它不是我们的价格来源**：我们自己的模型目录表来自 models.dev（见
   [自建 LLM 传输层的可行性与边界](2026-11-01-self-owned-llm-transport.md)）。

## Alternatives considered

- **在代码里硬设 `os.environ[...] = "True"`**：彻底不可覆盖，连 compose 的
  `environment:` 都压不住——用户失去恢复能力，不接受。
- **把价格表换成我们自己的一份**：我们的计价已经不读它，换了也没有收益。
- **彻底删掉价格表**：做不到——litellm 随包一定带
  `model_prices_and_context_window_backup.json`（容器内 3817 条，本机 4319 条）。
  「彻底删掉 litellm 依赖」是另一件事（见传输层那条路线）。

## Consequences

- 启动省 ~3.4 s（远端可达时）/ ~7.7 s（远端不可达时），并且启动不再依赖
  `raw.githubusercontent.com`。
- 少 233 条模型条目（约 5%）。这些条目对我们无用；实测随包备份里
  `gpt-4.1-mini`、`gpt-4o`、`claude-sonnet-4-5`、`gpt-5` 都在。
- **残余风险**：若将来接了**在 litellm 表里**的模型，本地备份的上下文窗口与价格
  数字会比远端旧一些，而 litellm 的上下文窗口检查会用这些数字。要恢复远端表，
  把 `LITELLM_LOCAL_MODEL_COST_MAP` 设为 `False` 即可（compose 的
  `${VAR:-True}` 认这个覆盖）。
- 验证方式：两个开关状态下各跑一遍 parity 测试
  （`test_llm_native_transport.py` 52 项 + `test_llm_native_anthropic_gemini.py`
  36 项）——都全绿；同一组请求在两种状态下的异常类型与内容完全一致。

相关：[自建 LLM 传输层的可行性与边界](2026-11-01-self-owned-llm-transport.md)、
[补 anthropic / gemini 原生协议](2026-11-01-native-anthropic-gemini-protocols.md)
