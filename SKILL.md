---
name: topiceye-reader
description: 读取 TopicEye 选题数据（今日精选 / 日报 / 趋势），用于内容发现与选题辅助。当用户询问"今天有什么值得写的""最近有什么热点""帮我看看选题"时调用。
---

# TopicEye Reader

通过 HTTP API 读取 TopicEye 已抓取、已分析、已精选的选题数据。TopicEye 是一个内容选题雷达，持续抓取多个信源（RSS / 社交平台）并用 6 维评分模型筛选高价值选题。

## 鉴权

所有端点需要 Bearer token。在 TopicEye 应用「个人中心 → Agent 接入」创建一个个人 API token（明文仅显示一次），或通过 API 创建：

```bash
curl -X POST https://<your-topiceye>/api/v1/me/api-tokens \
  -H "Authorization: Bearer <session-token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-agent"}'
# 响应里的 "token" 字段即为可长期使用的 API token
```

之后所有调用带上：

```
Authorization: Bearer <your-api-token>
```

> 下文示例中 `$TOKEN` 代指该 API token，`$BASE` 代指 TopicEye 地址（如 `http://localhost:8102`）。

## 端点

### 1. `GET /api/v1/skill/today-picks` — 今日精选选题

返回最近 N 小时内 TopicEye 的精选选题。**这是回答"今天有什么值得写的"的首选端点。**

**参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `hours` | int | 48 | 回看时间窗（1–168 小时） |
| `limit` | int | 20 | 返回条数上限（1–100） |
| `category` | string | 无 | 按分类过滤（如 `AI`、`产品`） |

**关键字段：**

- `items[*].title` / `url` / `summary` — 选题标题、链接、摘要
- `items[*].analysis.adjusted_curation_score` — 最终排名分（越高越值得写）
- `items[*].analysis.recommended_reason` — AI 推荐理由
- `items[*].analysis.score_breakdown` — 完整评分明细（6 维 + 风险 + 时效）

```bash
curl "$BASE/api/v1/skill/today-picks?hours=48&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

### 2. `GET /api/v1/skill/daily-report` — 日报

返回 TopicEye 生成的日报（已编辑的选题综述）。缺省 `date` 返回今天的最新日报。

**参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `date` | string | 今天 | `YYYY-MM-DD` |

**关键字段：**

- `overview` — 选题综述（自然语言段落）
- `takeaway` — 核心要点
- `top_picks` — 精选条目数组（标题 + 来源 + 角度）
- `keywords` / `trends` — 关键词与趋势

```bash
curl "$BASE/api/v1/skill/daily-report?date=2026-07-15" \
  -H "Authorization: Bearer $TOKEN"
```

### 3. `GET /api/v1/skill/trends` — 话题趋势 + 关键词

合并返回话题趋势和关键词词频，一次请求拿全。数据来自每日快照。

**参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `days` | int | 7 | 回看天数（1–30） |
| `limit` | int | 50 | 关键词返回上限（10–200） |

```bash
curl "$BASE/api/v1/skill/trends?days=7&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

## 典型用法

| 用户问题 | 调用 |
|---|---|
| "今天有什么值得写的选题？" | `GET /skill/today-picks?hours=48&limit=10` → 按 `adjusted_curation_score` 解读 |
| "给我看一下今天的选题日报" | `GET /skill/daily-report` |
| "最近一周有什么热点趋势？" | `GET /skill/trends?days=7` |
| "AI 领域最近有什么好选题？" | `GET /skill/today-picks?category=AI` |

## 补充：评分（可选）

如果需要对**自己的内容**跑 TopicEye 的评分模型，用 `POST /api/v1/scoring/score`（详见 `AGENT_API.md`）。skill 端点读 TopicEye 数据，scoring 端点评外部数据，两者互补。
