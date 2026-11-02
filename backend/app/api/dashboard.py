"""
内置监控大盘 — 自包含 HTML 页面（零外部依赖）。

路由：
  GET /api/v1/metrics/dashboard  →  后台内嵌监控画布

设计（#209）：
- 皮肤回到产品本色：浅底 #F7F7F8 + 品牌橙 #FF6B35 + 与主站同款字体栈；
  状态语义三档（灰=正常 / 橙=注意 / 红=严重），不再一个指标一种颜色。
- 首屏只有一个主角：状态判定条（"现在能不能发稿" + 依据 + 采样时间）。
- 其下是体检表（指标 / 值 / 阈值 / 迷你趋势 / 状态），点任一行就地展开该指标的
  趋势与相关日志——值班真正要的主动作。
- 顶部 4 个页签移进左侧墨色栏（与主站后台壳一致）；删掉"速率/累计"开关，
  刷新间隔并入时间窗。

数据来源：
- 当前值：/api/v1/metrics/snapshot（实时）
- 趋势：/api/v1/metrics/history（PG 每 60 秒落一次的快照，含 P50/P95/P99 序列）

图表引擎特性（纯 Canvas API，无 Chart.js / D3 / CDN 依赖）：
- 交互式 tooltip（hover 十字光标 + 数值面板）
- 双 Y 轴支持（不同量级数据同图展示）
- 速率计算（累计值 → req/s）
- 渐变面积填充
- 迷你趋势线（体检表行内）
- 响应式（ResizeObserver 自动重绘）
- Page Visibility API：标签页隐藏时自动暂停轮询
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.api.v1.auth import get_current_admin_user

router = APIRouter(prefix="", tags=["dashboard"])

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TopicEye 监控大盘</title>
<style>
:root{
  --bg:#F7F7F8; --surface:#FFFFFF; --surface-2:#FAFAFA;
  --border:#E5E7EB; --border-soft:#F0F0F1;
  --text:#1A1A2E; --text-2:#4B5563; --text-3:#5F6773;
  --accent:#FF6B35; --accent-soft:#FFF4EE; --accent-border:#FFD0B5;
  --ok:#9CA3AF; --warn:#FF6B35; --crit:#EF4444;
  /* 小字用的深色变体：品牌色本身在白底上只有 2.8:1，当文字读不清 */
  --accent-text:#C2410C; --warn-text:#B45309; --crit-text:#B91C1C;
  --ink:#1D1D20; --ink-2:#2A2A2E; --ink-line:#3F3F46;
  --ink-text:#E4E4E7; --ink-muted:#A1A1AA;
  --r-lg:12px; --r-md:10px; --r-sm:8px; --r-xs:6px;
  --sans:-apple-system,BlinkMacSystemFont,"DM Sans","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,"SF Mono","DM Mono",Menlo,Consolas,monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--sans);background:var(--bg);color:var(--text);font-size:13px;line-height:1.55;-webkit-font-smoothing:antialiased}
.num,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:var(--accent-text);text-decoration:none}
a:hover{text-decoration:underline}

/* ── 壳：左墨色栏 + 右工作区 ── */
.shell{display:flex;height:100vh;overflow:hidden}
.rail{width:196px;flex:0 0 196px;background:var(--ink);color:var(--ink-text);display:flex;flex-direction:column}
.rail-brand{display:flex;align-items:center;gap:8px;padding:16px 16px 12px;font-size:14px;font-weight:700;letter-spacing:.01em}
.rail-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex:0 0 8px}
.rail-caption{padding:10px 16px 4px;font-size:10px;letter-spacing:.08em;color:var(--ink-muted);text-transform:uppercase}
.rail-nav{display:flex;flex-direction:column;padding:4px 8px;gap:1px}
.rail-item{appearance:none;background:none;border:0;color:var(--ink-muted);text-align:left;font:inherit;font-size:13px;padding:8px 10px;border-radius:var(--r-sm);cursor:pointer;position:relative}
.rail-item:hover{background:var(--ink-2);color:var(--ink-text)}
.rail-item.is-active{background:var(--ink-2);color:#fff;font-weight:600}
.rail-item.is-active::before{content:"";position:absolute;left:-8px;top:6px;bottom:6px;width:3px;border-radius:0 2px 2px 0;background:var(--accent)}
.rail-foot{margin-top:auto;padding:12px 16px;border-top:1px solid var(--ink-line);display:flex;flex-direction:column;gap:6px;font-size:12px}
.rail-foot a{color:var(--ink-muted)}
.rail-foot a:hover{color:var(--ink-text);text-decoration:none}
.main{flex:1;min-width:0;display:flex;flex-direction:column;overflow-y:auto}

/* ── 顶栏 ── */
.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 24px;background:rgba(247,247,248,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--border)}
.topbar-head{display:flex;align-items:baseline;gap:12px;min-width:0}
.topbar-head h1{font-size:16px;font-weight:700;letter-spacing:.01em}
.topbar-sub{font-size:12px;color:var(--text-2)}
.topbar-tools{display:flex;align-items:center;gap:10px;flex-shrink:0}
.field{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-2)}
select,input[type=text]{appearance:none;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-sm);padding:5px 26px 5px 9px;font:inherit;font-size:12px;color:var(--text);cursor:pointer;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%236B7280' stroke-width='3'><path d='M6 9l6 6 6-6'/></svg>");background-repeat:no-repeat;background-position:right 8px center}
select:hover,input[type=text]:hover{border-color:#D1D5DB}
.btn{appearance:none;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-sm);padding:6px 12px;font:inherit;font-size:12px;color:var(--text);cursor:pointer}
.btn:hover{border-color:#D1D5DB;background:var(--surface-2)}
.btn:active{transform:translateY(1px)}
.updated{font-size:12px;color:var(--text-2);font-family:var(--mono)}

/* ── 主体 ── */
.content{padding:20px 24px 56px;display:flex;flex-direction:column;gap:20px;max-width:1180px}

/* ── 状态判定条（首屏唯一主角）── */
.verdict{display:flex;align-items:flex-start;gap:14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:18px 20px}
.verdict-bar{width:4px;align-self:stretch;border-radius:2px;background:var(--ok);flex:0 0 4px}
.verdict[data-state="ok"] .verdict-bar{background:var(--ok)}
.verdict[data-state="warn"] .verdict-bar{background:var(--warn)}
.verdict[data-state="crit"] .verdict-bar{background:var(--crit)}
.verdict[data-state="pending"] .verdict-bar{background:var(--border)}
.verdict-text{flex:1;min-width:0}
.verdict-title{font-size:19px;font-weight:700;letter-spacing:.01em;line-height:1.35}
.verdict[data-state="warn"] .verdict-title{color:var(--warn-text)}
.verdict[data-state="crit"] .verdict-title{color:var(--crit-text)}
.verdict-meta{font-size:12px;color:var(--text-2);margin-top:4px}
.verdict-acts{display:flex;gap:8px;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end}
.verdict-act{appearance:none;font:inherit;font-size:12px;font-weight:600;border:1px solid var(--accent-border);background:var(--accent-soft);color:#B23A0F;border-radius:var(--r-sm);padding:4px 10px;cursor:pointer}
.verdict-act:hover{background:#FFE9DE}

/* ── 面板 ── */
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden}
.panel-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:14px 18px 0}
.panel-head h2{font-size:13px;font-weight:700;letter-spacing:.01em}
.panel-sub{font-size:12px;color:var(--text-3)}
.panel-body{padding:12px 18px 16px}

/* ── 体检表 ── */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--text-2);border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:0 10px;border-bottom:1px solid var(--border-soft);vertical-align:middle}
th.num,td.num{text-align:right}
.check-row{cursor:pointer}
.check-row:hover td{background:var(--surface-2)}
.check-row.is-open td{background:var(--accent-soft)}
.check-name{font-weight:600;font-size:13px}
.check-sub{color:var(--text-3);font-size:11px}
.check-value{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:14px;font-weight:600;text-align:right;white-space:nowrap}
.check-thr{color:var(--text-2);font-size:11.5px;white-space:nowrap}
.check-spark{width:132px}
.check-spark canvas{display:block;width:132px;height:22px}
.check-state{width:78px;text-align:right}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;line-height:18px;white-space:nowrap}
.pill.ok{background:#F3F4F6;color:var(--text-2)}
.pill.warn{background:var(--accent-soft);color:var(--accent-text)}
.pill.crit{background:#FEE2E2;color:var(--crit-text)}
.pill.info{background:#F9FAFB;color:var(--text-3)}
.check-detail td{background:#FCFCFD;padding:14px 18px}
.detail-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:20px}
.detail-title{font-size:11px;font-weight:600;color:var(--text-2);margin-bottom:8px}
.detail-canvas{width:100%;height:120px;display:block}
.detail-logs{max-height:190px;overflow-y:auto;font-family:var(--mono);font-size:11px;line-height:1.7;color:var(--text-2)}
.detail-logs div{padding:1px 0;border-bottom:1px solid var(--border-soft);white-space:pre-wrap;word-break:break-all}
.detail-logs div:last-child{border-bottom:0}
.detail-empty{color:var(--text-3);font-size:11.5px;font-family:var(--sans)}

/* ── 图表 ── */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:0}
/* 图表格子不自带边框：外层面板已经是容器，格子再套一层卡片就成了卡片套卡片 */
.chart-cell{background:transparent;border:0;padding:4px 0 0;position:relative;min-width:0}
.chart-title{font-size:11.5px;font-weight:600;color:var(--text-2);margin-bottom:6px}
.chart-cell canvas{display:block;width:100%;height:160px}
.chart-tip{display:none;position:absolute;z-index:10;background:rgba(26,26,46,.96);color:#fff;border-radius:var(--r-sm);padding:7px 10px;font-size:11px;pointer-events:none;white-space:nowrap;box-shadow:0 4px 14px rgba(0,0,0,.16)}
.chart-tip .tt-time{color:#C7CBD6;margin-bottom:3px}
.chart-tip .tt-row{display:flex;align-items:center;gap:6px}
.chart-tip .tt-dot{width:7px;height:7px;border-radius:50%;flex:0 0 7px}
.chart-tip .tt-label{color:#C7CBD6}
.chart-tip .tt-val{margin-left:auto;font-family:var(--mono);font-variant-numeric:tabular-nums}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--text-2);padding:6px 2px 0}
.legend i{display:inline-block;width:12px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}

/* ── 运行时状态卡 ── */
.stat{padding:10px 14px;border-left:1px solid var(--border)}
.stat:first-child{border-left:0;padding-left:0}
.stat-label{font-size:11px;color:var(--text-2);margin-bottom:6px}
.stat-value{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:17px;font-weight:700}
.stat-meta{font-size:11px;color:var(--text-3);margin-top:4px;font-family:var(--sans)}

/* ── 日志面板 ── */
.log-filter{display:flex;gap:8px;align-items:center;margin-bottom:10px}
.log-panel{max-height:420px;overflow-y:auto;font-family:var(--mono);font-size:11.5px}
.log-entry{padding:5px 8px;border-bottom:1px solid var(--border-soft);display:flex;gap:10px;align-items:flex-start}
.log-entry:hover{background:var(--surface-2)}
.log-ts{color:var(--text-3);white-space:nowrap;font-variant-numeric:tabular-nums}
.log-level{font-weight:600;white-space:nowrap}
.log-level.ERROR,.log-level.CRITICAL{color:var(--crit-text)}
.log-level.WARNING{color:var(--warn-text)}
.log-level.INFO{color:var(--accent-text)}
.log-level.DEBUG{color:var(--text-3)}
.log-msg{flex:1;min-width:0;word-break:break-all}
.log-source{color:var(--text-3);font-size:10.5px;white-space:nowrap}
.loading{padding:24px;text-align:center;color:var(--text-3);font-size:12px}
.empty{padding:28px;text-align:center;color:var(--text-3);font-size:12.5px}

@media(max-width:900px){
  .grid2,.grid3,.detail-grid{grid-template-columns:1fr}
  .rail{width:56px;flex:0 0 56px}
  .rail-brand span:not(.rail-dot),.rail-caption,.rail-item{font-size:0}
  .rail-item::after{content:attr(data-short);font-size:12px}
  .rail-foot a{font-size:0}
  .rail-foot a::after{content:"↗";font-size:13px}
  .check-spark,.check-thr{display:none}
}
</style>
</head>
<body>
<div class="shell">
  <aside class="rail">
    <div class="rail-brand"><span class="rail-dot"></span><span>TopicEye</span></div>
    <div class="rail-caption">监控</div>
    <nav class="rail-nav">
      <button class="rail-item is-active" data-tab="overview" data-short="概览">概览</button>
      <button class="rail-item" data-tab="llm-logs" data-short="LLM">LLM 日志</button>
      <button class="rail-item" data-tab="app-logs" data-short="日志">应用日志</button>
      <button class="rail-item" data-tab="web-vitals" data-short="体验">前端体验</button>
    </nav>
    <div class="rail-foot">
      <a href="/metrics" target="_blank">Prometheus</a>
      <a href="/health/ready" target="_blank">健康检查</a>
    </div>
  </aside>

  <main class="main">
    <header class="topbar">
      <div class="topbar-head">
        <h1>监控大盘</h1>
        <span class="topbar-sub" id="uptime">--</span>
      </div>
      <div class="topbar-tools">
        <label class="field">时间窗
          <select id="timeWindow">
            <option value="1">最近 1 小时</option>
            <option value="6">最近 6 小时</option>
            <option value="24" selected>最近 24 小时</option>
            <option value="168">最近 7 天</option>
          </select>
        </label>
        <button class="btn" id="refreshBtn">刷新</button>
        <span class="updated" id="lastUpdate">--</span>
      </div>
    </header>

    <!-- 概览 -->
    <section class="content" id="tab-overview">
      <section class="verdict" id="verdict" data-state="pending">
        <span class="verdict-bar"></span>
        <div class="verdict-text">
          <div class="verdict-title" id="verdictTitle">正在读取…</div>
          <div class="verdict-meta" id="verdictMeta">--</div>
        </div>
        <div class="verdict-acts" id="verdictActs"></div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>系统体检</h2>
          <span class="panel-sub" id="checkSummary">--</span>
        </div>
        <div class="panel-body" style="padding:6px 10px 8px">
          <table>
            <thead>
              <tr>
                <th style="width:32%">检查项</th>
                <th class="num" style="width:18%">当前值</th>
                <th style="width:20%">阈值</th>
                <th class="check-spark">趋势</th>
                <th class="check-state">状态</th>
              </tr>
            </thead>
            <tbody id="checkBody"></tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>趋势</h2>
          <span class="panel-sub" id="trendWindow">--</span>
        </div>
        <div class="panel-body">
          <div class="grid2">
            <div class="chart-cell">
              <div class="chart-title">请求速率 &amp; 错误</div>
              <canvas id="chartRequests" height="170"></canvas>
              <div class="chart-tip" id="ttRequests"></div>
            </div>
            <div class="chart-cell">
              <div class="chart-title">LLM 调用 &amp; 成本</div>
              <canvas id="chartLlm" height="170"></canvas>
              <div class="chart-tip" id="ttLlm"></div>
            </div>
            <div class="chart-cell">
              <div class="chart-title">HTTP 延迟分位数</div>
              <canvas id="chartLatency" height="150"></canvas>
              <div class="chart-tip" id="ttLatency"></div>
            </div>
            <div class="chart-cell">
              <div class="chart-title">DB 连接池</div>
              <canvas id="chartDbPool" height="150"></canvas>
              <div class="chart-tip" id="ttDbPool"></div>
            </div>
            <div class="chart-cell">
              <div class="chart-title">LLM 延迟分位数</div>
              <canvas id="chartLlmLatency" height="150"></canvas>
              <div class="chart-tip" id="ttLlmLatency"></div>
            </div>
            <div class="chart-cell">
              <div class="chart-title">Top 请求路径</div>
              <table style="margin-top:2px"><tbody id="topPathsTable"></tbody></table>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>运行时状态</h2></div>
        <div class="panel-body">
          <div class="grid3">
            <div class="stat">
              <div class="stat-label">熔断器</div>
              <div class="stat-value"><span class="pill info" id="cbBadge">--</span></div>
              <div class="stat-meta" id="cbDetail">--</div>
            </div>
            <div class="stat">
              <div class="stat-label">LLM 响应缓存</div>
              <div class="stat-value"><span class="pill info" id="cacheBadge">--</span></div>
              <div class="stat-meta" id="cacheDetail">--</div>
            </div>
            <div class="stat">
              <div class="stat-label">慢查询</div>
              <div class="stat-value"><span class="pill info" id="slowBadge">--</span></div>
              <div class="stat-meta" id="slowDetail">--</div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>LLM 各场景调用</h2></div>
        <div class="panel-body" style="padding:6px 10px 8px">
          <table>
            <thead><tr><th>场景</th><th class="num">完成</th><th class="num">失败</th><th class="num">Token</th><th class="num">成本</th></tr></thead>
            <tbody id="llmSceneTable"></tbody>
          </table>
        </div>
      </section>
    </section>

    <!-- LLM 日志 -->
    <section class="content" id="tab-llm-logs" style="display:none">
      <section class="panel">
        <div class="panel-head">
          <h2>LLM 调用日志</h2>
          <span class="panel-sub" id="llmLogCount">0 条</span>
        </div>
        <div class="panel-body">
          <div class="log-filter">
            <button class="btn" data-llm-filter="FAILED" onclick="setLlmLogFilter('FAILED')">仅失败</button>
            <button class="btn" data-llm-filter="ALL" onclick="setLlmLogFilter('ALL')">全部</button>
          </div>
          <div class="log-panel" id="llmLogPanel"><div class="loading">点击刷新加载…</div></div>
        </div>
      </section>
    </section>

    <!-- 应用日志 -->
    <section class="content" id="tab-app-logs" style="display:none">
      <section class="panel">
        <div class="panel-head">
          <h2>应用日志</h2>
          <span class="panel-sub" id="appLogCount">0 条</span>
        </div>
        <div class="panel-body">
          <div class="log-filter">
            <button class="btn" data-log-filter="ALL" onclick="setAppLogFilter('ALL')">全部</button>
            <button class="btn" data-log-filter="ERROR" onclick="setAppLogFilter('ERROR')">ERROR</button>
            <button class="btn" data-log-filter="WARNING" onclick="setAppLogFilter('WARNING')">WARNING</button>
            <button class="btn" data-log-filter="INFO" onclick="setAppLogFilter('INFO')">INFO</button>
          </div>
          <div class="log-panel" id="appLogPanel"><div class="loading">点击刷新加载…</div></div>
        </div>
      </section>
    </section>

    <!-- 前端体验 -->
    <section class="content" id="tab-web-vitals" style="display:none">
      <section class="panel">
        <div class="panel-head">
          <h2>前端体验指标</h2>
          <span class="panel-sub" id="webVitalsMeta">--</span>
        </div>
        <div class="panel-body">
          <div class="log-filter">
            <button class="btn" data-wv-nav="navigate" onclick="setWebVitalsNav('navigate')">首次加载</button>
            <button class="btn" data-wv-nav="soft-navigation" onclick="setWebVitalsNav('soft-navigation')">软导航</button>
            <button class="btn" data-wv-nav="all" onclick="setWebVitalsNav('all')">全部</button>
            <button class="btn" onclick="fetchWebVitals()">刷新</button>
          </div>
          <div class="grid3" style="margin-bottom:14px">
            <div class="stat">
              <div class="stat-label">LCP p75</div>
              <div class="stat-value" id="wvLcp">--</div>
              <div class="stat-meta" id="wvLcpSub">--</div>
            </div>
            <div class="stat">
              <div class="stat-label">INP p75</div>
              <div class="stat-value" id="wvInp">--</div>
              <div class="stat-meta" id="wvInpSub">--</div>
            </div>
            <div class="stat">
              <div class="stat-label">CLS p75</div>
              <div class="stat-value" id="wvCls">--</div>
              <div class="stat-meta" id="wvClsSub">--</div>
            </div>
          </div>
          <div class="detail-title">按路由拆解（p75）</div>
          <table>
            <thead><tr><th>路由</th><th>指标</th><th class="num">p75</th><th class="num">样本</th><th class="check-state">状态</th></tr></thead>
            <tbody id="wvRouteTable"><tr><td colspan="5" class="loading">加载中…</td></tr></tbody>
          </table>
        </div>
      </section>
    </section>
  </main>
</div>

<script>
const API_SNAPSHOT = window.location.origin + '/api/v1/metrics/snapshot';
const API_HISTORY = window.location.origin + '/api/v1/metrics/history';
const API_CHECKS = window.location.origin + '/api/v1/metrics/checks';
const API_LOGS = window.location.origin + '/api/v1/metrics/logs';
const API_LLM_LOGS = window.location.origin + '/api/v1/metrics/llm-logs';
const API_WEB_VITALS = window.location.origin + '/api/v1/metrics/web-vitals/summary';

// 图表配色：语义优先，一个系列一个颜色且与状态对应
const C = {
  accent:'#FF6B35', accentSoft:'rgba(255,107,53,0.14)',
  teal:'#00C9A7', tealSoft:'rgba(0,201,167,0.14)',
  crit:'#EF4444', critSoft:'rgba(239,68,68,0.12)',
  amber:'#D97706', amberSoft:'rgba(217,119,6,0.12)',
  purple:'#8B5CF6', purpleSoft:'rgba(139,92,246,0.12)',
  grid:'#E5E7EB', axis:'#5F6773', text:'#1A1A2E', faint:'#7B8391',
};

let activeTab = 'overview';
let refreshTimer = null;
let isTabVisible = !document.hidden;
let lastData = null;
let lastSeries = [];
let lastChecks = [];
let lastSummary = {};
let llmLogFilter = 'FAILED';
let appLogFilter = 'ALL';
let webVitalsNav = 'navigate';
let historyHours = 24;

// ── 工具 ──
function fmtNum(n){if(n==null||n===undefined)return'--';if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return String(Math.round(n*100)/100)}
// 延迟一律按毫秒入参，秒只是展示选择——别让「1.5 秒」被当成「1.5 毫秒」
function fmtMs(ms){if(ms==null||ms===undefined)return'--';if(ms<1000)return ms.toFixed(ms<10?1:0)+'ms';return(ms/1000).toFixed(2)+'s'}
function fmtCost(n){return n!=null?'$'+Number(n).toFixed(4):'--'}
// 趋势图刻度：跟着体检项自己的单位走，别丢裸数字让人猜
function fmtByUnit(unit,v){
  if(v==null)return'--';
  if(unit==='ms')return fmtMs(v);
  if(unit==='%')return Number(v).toFixed(Math.abs(v)<10?2:1)+'%';
  if(unit==='$')return fmtCost(v);
  if(unit===' 次/小时')return Number(v).toFixed(1)+' 次/小时';
  if(unit===' 次')return Math.round(v)+' 次';
  if(unit===' req/s')return Number(v).toFixed(1)+' req/s';
  return fmtNum(v);
}
function fmtMb(m){if(m==null)return'--';if(m>=1024)return(m/1024).toFixed(2)+'GB';return(m).toFixed(0)+'MB'}
function fmtTime(s){if(!s)return'--';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);if(h>0)return h+'h '+m+'m';if(m>0)return m+'m '+sec+'s';return sec+'s'}
function fmtClock(ts){if(!ts)return'--';return new Date(ts*1000).toLocaleTimeString('zh-CN',{hour12:false})}
function escHtml(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function stateLabel(s){return s==='ok'?'正常':s==='warn'?'注意':s==='crit'?'严重':s==='info'?'—':'待定'}

// 累计值 → 速率
function calcRate(series,key){
  if(!series||series.length<2)return[];
  const out=[];
  for(let i=1;i<series.length;i++){
    const dt=series[i].ts-series[i-1].ts;
    if(dt<=0){out.push({t:series[i].ts,v:0});continue}
    // 进程重启后累计值会归零，差值可能为负 → 不是真实速率，裁掉
    const v=(series[i][key]-series[i-1][key])/dt;
    out.push({t:series[i].ts,v:v>0?v:0});
  }
  return out;
}

// ── 体检项 ──
// 判定（当前值 / 阈值 / 状态）由服务端 /api/v1/metrics/checks 给，
// 前端不自己算状态——单位换算和「没有样本」的区分只有服务端知道。
// 这里只负责：把结论画出来，以及把历史快照映射成对应的趋势序列。

// ── 趋势序列（PG 历史快照 → 统一字段）──
function seriesFromHistory(records){
  return (records||[]).map(r=>({
    ts:Date.parse(r.captured_at)/1000,
    total_requests:r.http_total_requests||0,
    total_errors_5xx:r.http_total_errors_5xx||0,
    error_rate:r.http_error_rate==null?null:r.http_error_rate,
    total_llm_calls:r.llm_total_calls||0,
    total_llm_cost_usd:r.llm_total_cost_usd||0,
    db_pool_checked_out:r.db_pool_checked_out||0,
    db_pool_size:r.db_pool_size||0,
    db_utilization:r.db_pool_utilization==null?null:r.db_pool_utilization,
    p50:r.http_p50||0,p95:r.http_p95||0,p99:r.http_p99||0,
    llm_p50:r.llm_p50||0,llm_p95:r.llm_p95||0,llm_p99:r.llm_p99||0,
    llm_success_rate:r.llm_success_rate==null?null:r.llm_success_rate,
  }));
}

// 各体检项的趋势序列。trend 键由服务端下发，这里只负责取对应那一列。
// 趋势口径必须跟该项的当前值一致：错误率画比率（不是累计 5xx 个数），
// 连接池画利用率（不是已借出连接数）——否则同一行里两个数字说的不是一回事。
function trendFor(trendKey,series){
  if(!trendKey||!series.length)return[];
  const s=series;
  switch(trendKey){
    case 'errors': return s.map(p=>({t:p.ts,v:p.error_rate==null?0:p.error_rate}));
    case 'p95': return s.map(p=>({t:p.ts,v:p.p95*1000}));
    case 'llmok': return s.map(p=>({t:p.ts,v:p.llm_success_rate==null?null:p.llm_success_rate})).filter(p=>p.v!=null);
    case 'db': return s.map(p=>({t:p.ts,v:p.db_utilization!=null?p.db_utilization:(p.db_pool_size?p.db_pool_checked_out/p.db_pool_size*100:0)}));
    case 'reqrate': return calcRate(s,'total_requests');
    case 'cost': return s.map(p=>({t:p.ts,v:p.total_llm_cost_usd}));
    default: return [];
  }
}

// ── 数据获取 ──
async function fetchJSON(url){
  const r=await fetch(url);
  if(!r.ok)throw new Error(url+' -> '+r.status);
  return r.json();
}

async function loadOverview(){
  try{
    const [snap,hist,checks]=await Promise.all([
      fetchJSON(API_SNAPSHOT),
      fetchJSON(API_HISTORY+'?hours='+historyHours+'&limit=1000'),
      fetchJSON(API_CHECKS),
    ]);
    lastData=snap;
    lastSeries=seriesFromHistory(hist.records);
    lastChecks=checks.checks||[];
    lastSummary=checks.summary||{};
    renderOverview(snap);
  }catch(err){
    document.getElementById('verdictTitle').textContent='读取失败';
    document.getElementById('verdictMeta').textContent=err.message;
    document.getElementById('verdict').dataset.state='crit';
  }
  document.getElementById('lastUpdate').textContent=new Date().toLocaleTimeString('zh-CN',{hour12:false});
}

function renderOverview(data){
  const snap=data.snapshot||{};
  const up=Math.floor(snap.uptime_seconds||0);
  document.getElementById('uptime').textContent=up>0?('运行 '+fmtTime(up)):'刚启动';

  renderVerdict();
  renderChecks();
  renderCharts(data);
  renderStatusCards(data);
  renderTopPaths(data);
  renderLlmScenes(data);
}

function renderVerdict(){
  const el=document.getElementById('verdict');
  const acts=document.getElementById('verdictActs');
  acts.innerHTML='';
  const problems=lastChecks.filter(c=>c.state==='warn'||c.state==='crit');
  const pending=!lastSeries.length;
  if(pending){
    el.dataset.state='pending';
    document.getElementById('verdictTitle').textContent='尚无采样快照';
    const next=new Date(Date.now()+60000);
    document.getElementById('verdictMeta').textContent='监控快照每 60 秒落一次库；下一次约 ' + next.toLocaleTimeString('zh-CN',{hour12:false}) + '。实时值仍可看下方体检表。';
    return;
  }
  if(!problems.length){
    el.dataset.state='ok';
    const ok=lastSummary.ok||0;
    const noData=lastSummary.no_data||0;
    const title=ok?('系统正常 · '+ok+' 项检查通过'):'系统正常';
    document.getElementById('verdictTitle').textContent=noData?(title+`，${noData} 项暂无数据`):title;
    document.getElementById('verdictMeta').textContent=noData
      ?('采样自最近 '+historyHours+' 小时；标「—」的项还没有样本，不计入通过。')
      :('采样自最近 '+historyHours+' 小时；判定依据是下方每项的当前值与阈值。');
    return;
  }
  const crit=problems.filter(c=>c.state==='crit');
  const warn=problems.filter(c=>c.state==='warn');
  el.dataset.state=crit.length?'crit':'warn';
  const parts=[];
  if(crit.length)parts.push(crit.length+' 项严重');
  if(warn.length)parts.push(warn.length+' 项注意');
  document.getElementById('verdictTitle').textContent=parts.join('、');
  document.getElementById('verdictMeta').textContent='超标项：'+problems.map(c=>c.label).join('、');
  problems.slice(0,3).forEach(c=>{
    const b=document.createElement('button');
    b.className='verdict-act';
    b.textContent=c.label;
    b.onclick=()=>openDetail(c.key,true);
    acts.appendChild(b);
  });
}

function renderChecks(){
  const body=document.getElementById('checkBody');
  body.innerHTML='';
  lastChecks.forEach(c=>{
    const tr=document.createElement('tr');
    tr.className='check-row';
    tr.dataset.key=c.key;
    tr.innerHTML=
      '<td><div class="check-name">'+escHtml(c.label)+'</div><div class="check-sub">'+escHtml(c.hint)+'</div></td>'+
      '<td class="num"><div class="check-value">'+escHtml(c.display)+'</div></td>'+
      '<td class="check-thr">'+escHtml(c.threshold)+'</td>'+
      '<td class="check-spark"><canvas id="spark_'+c.key+'"></canvas></td>'+
      '<td class="check-state"><span class="pill '+c.state+'">'+stateLabel(c.state)+'</span></td>';

    const detail=document.createElement('tr');
    detail.className='check-detail';
    detail.dataset.key=c.key;
    detail.dataset.open='0';
    detail.style.display='none';
    detail.innerHTML=
      '<td colspan="5"><div class="detail-grid">'+
        '<div><div class="detail-title">'+escHtml(c.label)+' 趋势</div><canvas class="detail-canvas" id="detail_'+c.key+'"></canvas></div>'+
        '<div><div class="detail-title">相关日志</div><div class="detail-logs" id="logs_'+c.key+'"><div class="detail-empty">展开后加载…</div></div></div>'+
      '</div></td>';

    tr.onclick=()=>openDetail(c.key);
    body.appendChild(tr);
    body.appendChild(detail);

    const spark=trendFor(c.trend,lastSeries);
    if(spark.length>1)drawSparkline('spark_'+c.key,spark,c.state==='crit'?C.crit:c.state==='warn'?C.accent:C.faint);
  });

  const parts=[];
  const crit=lastSummary.crit||0,warn=lastSummary.warn||0,ok=lastSummary.ok||0,noData=lastSummary.no_data||0;
  if(crit)parts.push(crit+' 项严重');
  if(warn)parts.push(warn+' 项注意');
  if(!crit&&!warn)parts.push(ok+' 项正常');
  if(noData)parts.push(noData+' 项暂无数据');
  document.getElementById('checkSummary').textContent=parts.join(' · ')+'　共 '+lastChecks.length+' 项';
}

async function openDetail(key,scroll){
  const detail=document.querySelector('.check-detail[data-key="'+key+'"]');
  if(!detail)return;
  if(detail.dataset.open==='1'){
    detail.dataset.open='0';detail.style.display='none';
    const row=document.querySelector('.check-row[data-key="'+key+'"]');
    if(row)row.classList.remove('is-open');
    return;
  }
  document.querySelectorAll('.check-detail').forEach(r=>{r.dataset.open='0';r.style.display='none'});
  document.querySelectorAll('.check-row').forEach(r=>r.classList.remove('is-open'));
  detail.dataset.open='1';detail.style.display='table-row';
  const row=document.querySelector('.check-row[data-key="'+key+'"]');
  if(row)row.classList.add('is-open');

  const c=lastChecks.find(x=>x.key===key);
  if(!c)return;
  const spark=trendFor(c.trend,lastSeries);
  const canvas=document.getElementById('detail_'+key);
  if(canvas)drawDetail(canvas,spark,c);
  await fillLogs(key,c);
  if(scroll&&row)row.scrollIntoView({block:'nearest',behavior:'smooth'});
}

async function fillLogs(key,c){
  const box=document.getElementById('logs_'+key);
  if(!box)return;
  box.innerHTML='<div class="detail-empty">加载中…</div>';
  try{
    const url=c.logs==='llm'?API_LLM_LOGS+'?status=ALL&limit=20':API_LOGS+'?level=ALL&limit=20';
    const data=await fetchJSON(url);
    const rows=c.logs==='llm'?(data.logs||[]):(data.entries||[]);
    if(!rows.length){box.innerHTML='<div class="detail-empty">窗口内没有相关日志</div>';return}
    box.innerHTML=rows.slice(0,20).map(r=>{
      if(c.logs==='llm'){
        const t=r.created_at?new Date(r.created_at).toLocaleTimeString('zh-CN',{hour12:false}):'--';
        return '<div>'+escHtml(t)+'  '+escHtml(r.scene||'')+'  '+escHtml(r.status||'')+'  '+
          escHtml((r.error||'').slice(0,120)||'ok')+'</div>';
      }
      const t=r.ts?new Date(r.ts).toLocaleTimeString('zh-CN',{hour12:false}):'--';
      return '<div>'+escHtml(t)+'  '+escHtml(r.level||'')+'  '+escHtml(r.logger||'')+'  '+escHtml(r.message||'')+'</div>';
    }).join('');
  }catch(err){
    box.innerHTML='<div class="detail-empty">日志读取失败：'+escHtml(err.message)+'</div>';
  }
}

// ── 迷你趋势线 ──
function drawSparkline(canvasId,data,color){
  const c=document.getElementById(canvasId);
  if(!c)return;
  const ctx=c.getContext('2d');
  const dpr=window.devicePixelRatio||1;
  const W=c.offsetWidth||132,H=c.offsetHeight||22;
  c.width=W*dpr;c.height=H*dpr;
  ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,W,H);
  if(!data||data.length<2){
    ctx.fillStyle=C.faint;ctx.font='10px sans-serif';ctx.textAlign='center';
    ctx.fillText('—',W/2,H/2+3);return;
  }
  let min=Infinity,max=-Infinity;
  for(const d of data){if(d.v==null)continue;if(d.v<min)min=d.v;if(d.v>max)max=d.v}
  if(min===max){min=Math.max(0,min-1);max+=1}
  const pad=2;
  ctx.beginPath();
  for(let i=0;i<data.length;i++){
    const x=pad+(i/(data.length-1))*(W-2*pad);
    const y=pad+(1-(data[i].v-min)/(max-min))*(H-2*pad);
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  }
  ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.stroke();
}

// ── 详情大图（单线，无交互）──
function drawDetail(canvas,data,c){
  if(!canvas)return;
  const ctx=canvas.getContext('2d');
  const dpr=window.devicePixelRatio||1;
  const W=canvas.offsetWidth||360,H=canvas.offsetHeight||120;
  canvas.width=W*dpr;canvas.height=H*dpr;
  ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,W,H);
  const pad={top:10,right:10,bottom:18,left:54};
  const cw=W-pad.left-pad.right,ch=H-pad.top-pad.bottom;
  if(!data||data.length<2){
    ctx.fillStyle=C.faint;ctx.font='12px sans-serif';ctx.textAlign='center';
    ctx.fillText('该窗口内没有可画的数据',W/2,H/2);return;
  }
  let min=Infinity,max=-Infinity;
  for(const p of data){if(p.v==null)continue;if(p.v<min)min=p.v;if(p.v>max)max=p.v}
  if(min===max){min=Math.max(0,min-1);max+=1}
  const range=(max-min)||1;
  // 延迟、速率这类不可能为负的量，坐标轴不要因为留白而伸到 0 以下
  min=min>=0?Math.max(0,min-range*0.1):min-range*0.1;
  max+=range*0.1;
  ctx.strokeStyle=C.grid;ctx.lineWidth=1;ctx.setLineDash([3,4]);
  ctx.font='10px monospace';ctx.fillStyle=C.axis;ctx.textAlign='right';
  for(let i=0;i<=3;i++){
    const y=pad.top+(ch/3)*i;
    ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(pad.left+cw,y);ctx.stroke();
    ctx.fillText(fmtByUnit(c.unit,max-((max-min)/3)*i),pad.left-6,y+3);
  }
  ctx.setLineDash([]);
  const color=c.key==='errrate'||c.key==='p95'||c.key==='req'||c.key==='cost'?C.accent:(c.key==='db'?C.purple:C.teal);
  ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();
  for(let i=0;i<data.length;i++){
    const p=data[i];if(p.v==null)continue;
    const x=pad.left+(i/(data.length-1))*cw;
    const y=pad.top+(1-(p.v-min)/(max-min))*ch;
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  }
  ctx.stroke();
  ctx.fillStyle=C.axis;ctx.font='10px monospace';ctx.textAlign='center';
  ctx.fillText(fmtClock(data[0].ts),pad.left+10,H-4);
  ctx.fillText(fmtClock(data[data.length-1].ts),pad.left+cw-10,H-4);
}

// ── 交互式图表引擎 ──
class InteractiveChart{
  constructor(canvasId,tooltipId,options){
    this.canvas=document.getElementById(canvasId);
    this.tooltip=document.getElementById(tooltipId);
    this.ctx=this.canvas.getContext('2d');
    this.opts=Object.assign({leftAxis:true,rightAxis:false,pad:{top:14,right:26,bottom:22,left:52}},options);
    this.series=[];
    this.hoverIdx=-1;
    this.hoverX=null;
    this.bindEvents();
    if(window.ResizeObserver){new ResizeObserver(()=>this.render()).observe(this.canvas.parentElement)}
  }
  bindEvents(){
    this.canvas.addEventListener('mousemove',(e)=>{
      const rect=this.canvas.getBoundingClientRect();
      this.hoverX=e.clientX-rect.left;
      this.updateHover();
      this.render();
    });
    this.canvas.addEventListener('mouseleave',()=>{
      this.hoverX=null;this.hoverIdx=-1;
      if(this.tooltip)this.tooltip.style.display='none';
      this.render();
    });
  }
  updateHover(){
    if(!this.series.length||!this.series[0].data.length){this.hoverIdx=-1;return}
    const pad=this.opts.pad;
    const W=this.canvas.offsetWidth;
    const cw=W-pad.left-pad.right;
    const data=this.series[0].data;
    const minTs=data[0].t,maxTs=data[data.length-1].t;
    const tsRange=maxTs-minTs||1;
    const ratio=(this.hoverX-pad.left)/cw;
    const targetTs=minTs+ratio*tsRange;
    let best=0,bestDist=Infinity;
    for(let i=0;i<data.length;i++){
      const d=Math.abs(data[i].t-targetTs);
      if(d<bestDist){bestDist=d;best=i}
    }
    this.hoverIdx=best;
  }
  setData(series){this.series=series||[];this.render()}
  render(){
    const ctx=this.ctx,dpr=window.devicePixelRatio||1;
    const W=this.canvas.offsetWidth,H=this.canvas.offsetHeight||160;
    this.canvas.width=W*dpr;this.canvas.height=H*dpr;
    ctx.scale(dpr,dpr);
    ctx.clearRect(0,0,W,H);
    const pad=this.opts.pad;
    const cw=W-pad.left-pad.right,ch=H-pad.top-pad.bottom;
    if(!this.series.length||this.series[0].data.length===0){
      ctx.fillStyle=C.faint;ctx.font='12px sans-serif';ctx.textAlign='center';
      ctx.fillText('该窗口内没有采样数据',W/2,H/2);return;
    }
    const hasRight=this.opts.rightAxis&&this.series.some(s=>s.axis==='right');
    let lMin=Infinity,lMax=-Infinity,rMin=Infinity,rMax=-Infinity;
    for(const s of this.series){
      for(const p of s.data){
        if(s.axis==='right'){if(p.v<rMin)rMin=p.v;if(p.v>rMax)rMax=p.v}
        else{if(p.v<lMin)lMin=p.v;if(p.v>lMax)lMax=p.v}
      }
    }
    // 整条线都在 0 上时别把坐标轴拉到 -1..1：那会让「没有量」看起来像「有正有负」
    if(lMin===lMax){lMin=Math.max(0,lMin-1);lMax+=1}
    if(rMin===rMax){rMin=Math.max(0,rMin-1);rMax+=1}
    const lRange=lMax-lMin,rRange=rMax-rMin;
    // 速率、计数这类不可能为负的量，坐标轴不要因为留白而伸到 0 以下
    lMin=lMin>=0?Math.max(0,lMin-lRange*0.1):lMin-lRange*0.1;
    lMax+=lRange*0.1;
    rMin=rMin>=0?Math.max(0,rMin-rRange*0.1):rMin-rRange*0.1;
    rMax+=rRange*0.1;
    const data=this.series[0].data;
    const minTs=data[0].t,maxTs=data[data.length-1].t;
    const tsRange=(maxTs-minTs)||1;
    ctx.strokeStyle=C.grid;ctx.lineWidth=1;ctx.setLineDash([3,4]);
    ctx.font='10px monospace';ctx.fillStyle=C.axis;ctx.textAlign='right';
    const lFmt=this.opts.axisFmt||fmtNum;
    const rFmt=this.opts.rightAxisFmt||this.opts.axisFmt||fmtNum;
    for(let i=0;i<=4;i++){
      const y=pad.top+(ch/4)*i;
      ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(pad.left+cw,y);ctx.stroke();
      ctx.fillText(lFmt(lMax-((lMax-lMin)/4)*i),pad.left-6,y+3);
    }
    ctx.setLineDash([]);
    if(hasRight){
      ctx.textAlign='left';
      for(let i=0;i<=4;i++){
        const y=pad.top+(ch/4)*i;
        ctx.fillText(rFmt(rMax-((rMax-rMin)/4)*i),pad.left+cw+6,y+3);
      }
    }
    ctx.textAlign='center';
    for(let i=0;i<=4;i++){
      const x=pad.left+(cw/4)*i;
      const ts=minTs+(tsRange/4)*i;
      ctx.fillText(fmtClock(ts),x,H-6);
    }
    for(const s of this.series){
      const isRight=s.axis==='right';
      const dMin=isRight?rMin:lMin,dMax=isRight?rMax:lMax,dRange=(dMax-dMin)||1;
      if(s.fill){
        const grad=ctx.createLinearGradient(0,pad.top,0,pad.top+ch);
        grad.addColorStop(0,s.fill);
        grad.addColorStop(1,'rgba(255,255,255,0)');
        ctx.beginPath();
        for(let i=0;i<s.data.length;i++){
          const p=s.data[i];
          const x=pad.left+((p.t-minTs)/tsRange)*cw;
          const y=pad.top+(1-(p.v-dMin)/dRange)*ch;
          if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
        }
        ctx.lineTo(pad.left+cw,pad.top+ch);
        ctx.lineTo(pad.left,pad.top+ch);
        ctx.closePath();
        ctx.fillStyle=grad;ctx.fill();
      }
      ctx.strokeStyle=s.color;ctx.lineWidth=2;ctx.beginPath();
      for(let i=0;i<s.data.length;i++){
        const p=s.data[i];
        const x=pad.left+((p.t-minTs)/tsRange)*cw;
        const y=pad.top+(1-(p.v-dMin)/dRange)*ch;
        if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
    if(this.hoverIdx>=0&&this.hoverIdx<data.length){
      const p=data[this.hoverIdx];
      const hx=pad.left+((p.t-minTs)/tsRange)*cw;
      ctx.strokeStyle='rgba(156,163,175,0.55)';ctx.lineWidth=1;ctx.setLineDash([4,3]);
      ctx.beginPath();ctx.moveTo(hx,pad.top);ctx.lineTo(hx,pad.top+ch);ctx.stroke();
      ctx.setLineDash([]);
      for(const s of this.series){
        const sp=s.data[this.hoverIdx];
        if(!sp)continue;
        const isRight=s.axis==='right';
        const dMin=isRight?rMin:lMin,dMax=isRight?rMax:lMax,dRange=(dMax-dMin)||1;
        const y=pad.top+(1-(sp.v-dMin)/dRange)*ch;
        ctx.fillStyle=s.color;
        ctx.beginPath();ctx.arc(hx,y,4,0,Math.PI*2);ctx.fill();
        ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();
      }
      if(this.tooltip){
        let html='<div class="tt-time">'+fmtClock(p.t)+'</div>';
        for(const s of this.series){
          const sp=s.data[this.hoverIdx];
          if(sp==null)continue;
          const val=s.fmt?s.fmt(sp.v):fmtNum(sp.v);
          html+='<div class="tt-row"><span class="tt-dot" style="background:'+s.color+'"></span><span class="tt-label">'+s.label+'</span><span class="tt-val">'+val+'</span></div>';
        }
        this.tooltip.innerHTML=html;
        this.tooltip.style.display='block';
        const tw=this.tooltip.offsetWidth||120;
        let tx=hx+10;
        if(tx+tw>W)tx=hx-tw-10;
        this.tooltip.style.left=tx+'px';
        this.tooltip.style.top=(pad.top+4)+'px';
      }
    }
    ctx.font='10.5px sans-serif';ctx.textAlign='left';
    let lx=pad.left+6;
    for(const s of this.series){
      ctx.fillStyle=s.color;
      ctx.fillRect(lx,pad.top+2,12,3);
      ctx.fillStyle=C.axis;
      ctx.fillText(s.label,lx+16,pad.top+7);
      lx+=ctx.measureText(s.label).width+38;
    }
  }
}

const chartReq=new InteractiveChart('chartRequests','ttRequests',{leftAxis:true});
// 双轴图的右侧刻度要放得下，否则 "-0.12" 这种标签会被画布边缘截断
const chartLlm=new InteractiveChart('chartLlm','ttLlm',{leftAxis:true,rightAxis:true,pad:{top:14,right:52,bottom:22,left:52}});
const chartLat=new InteractiveChart('chartLatency','ttLatency',{leftAxis:true,axisFmt:v=>fmtMs(v*1000)});
const chartDb=new InteractiveChart('chartDbPool','ttDbPool',{leftAxis:true});
const chartLlmLat=new InteractiveChart('chartLlmLatency','ttLlmLatency',{leftAxis:true,axisFmt:v=>fmtMs(v*1000)});

function renderCharts(data){
  const s=lastSeries;
  document.getElementById('trendWindow').textContent='最近 '+historyHours+' 小时 · 每 60 秒一个采样点';

  const reqRates=calcRate(s,'total_requests');
  const errRates=calcRate(s,'total_errors_5xx');
  chartReq.setData([
    {label:'请求/s',color:C.accent,fill:C.accentSoft,data:reqRates,fmt:v=>v.toFixed(2)},
    {label:'错误/s',color:C.crit,data:errRates,fmt:v=>v.toFixed(2)},
  ]);

  const llmRates=calcRate(s,'total_llm_calls');
  const costRates=calcRate(s,'total_llm_cost_usd');
  chartLlm.setData([
    {label:'LLM 调用/s',color:C.teal,fill:C.tealSoft,data:llmRates,fmt:v=>v.toFixed(2)},
    {label:'成本/s (USD)',color:C.amber,axis:'right',data:costRates,fmt:v=>'$'+v.toFixed(4)},
  ]);

  chartLat.setData([
    {label:'P50',color:C.teal,data:s.map(p=>({t:p.ts,v:p.p50})),fmt:v=>fmtMs(v*1000)},
    {label:'P95',color:C.accent,data:s.map(p=>({t:p.ts,v:p.p95})),fmt:v=>fmtMs(v*1000)},
    {label:'P99',color:C.crit,data:s.map(p=>({t:p.ts,v:p.p99})),fmt:v=>fmtMs(v*1000)},
  ]);

  chartDb.setData([
    {label:'已借出',color:C.purple,fill:C.purpleSoft,data:s.map(p=>({t:p.ts,v:p.db_pool_checked_out}))},
    {label:'池大小',color:C.faint,data:s.map(p=>({t:p.ts,v:p.db_pool_size}))},
  ]);

  chartLlmLat.setData([
    {label:'P50',color:C.teal,data:s.map(p=>({t:p.ts,v:p.llm_p50})),fmt:v=>fmtMs(v*1000)},
    {label:'P95',color:C.accent,data:s.map(p=>({t:p.ts,v:p.llm_p95})),fmt:v=>fmtMs(v*1000)},
    {label:'P99',color:C.crit,data:s.map(p=>({t:p.ts,v:p.llm_p99})),fmt:v=>fmtMs(v*1000)},
  ]);
}

function findCheck(key){
  return lastChecks.find(c=>c.key===key);
}

// 运行时状态卡直接用服务端的判定结论，不在前端再抄一份阈值与状态映射。
function renderStatusCards(data){
  const cb=findCheck('cb');
  const cbBadge=document.getElementById('cbBadge');
  cbBadge.textContent=cb?cb.display:'—';
  cbBadge.className='pill '+(cb?cb.state:'info');
  const breaker=data.circuit_breaker||{};
  document.getElementById('cbDetail').textContent='失败 '+(breaker.failure_count||0)+'/'+(breaker.failure_threshold||5);

  const cache=data.llm_cache||{};
  const cacheTotal=(cache.hits||0)+(cache.misses||0);
  const cbadge=document.getElementById('cacheBadge');
  // 缓存命中率只是参考数字，没有行动阈值，不判档位
  cbadge.textContent=cacheTotal?((cache.hit_rate*100).toFixed(1)+'%'):'无记录';
  cbadge.className='pill info';
  document.getElementById('cacheDetail').textContent='命中 '+(cache.hits||0)+'/'+cacheTotal;

  const slow=findCheck('slow');
  const sbadge=document.getElementById('slowBadge');
  sbadge.textContent=slow?slow.display:'—';
  sbadge.className='pill '+(slow?slow.state:'info');
  document.getElementById('slowDetail').textContent='进程运行至今累计 '+(data.slow_queries==null?'—':data.slow_queries)+' 次';
}

function renderTopPaths(data){
  const paths=(data.snapshot&&data.snapshot.http&&data.snapshot.http.top_paths)||[];
  document.getElementById('topPathsTable').innerHTML=paths.length
    ? paths.slice(0,8).map(p=>'<tr><td style="word-break:break-all">'+escHtml(p.path)+'</td><td class="num">'+fmtNum(p.count)+'</td></tr>').join('')
    : '<tr><td class="empty" colspan="2">暂无数据</td></tr>';
}

function renderLlmScenes(data){
  const scenes=(data.snapshot&&data.snapshot.llm&&data.snapshot.llm.by_scene)||{};
  const html=Object.entries(scenes).map(([scene,d])=>
    '<tr><td>'+escHtml(scene)+'</td><td class="num">'+(d.done||0)+'</td><td class="num">'+(d.failed||0)+'</td>'+
    '<td class="num">'+fmtNum(d.tokens||0)+'</td><td class="num">'+fmtCost(d.cost||0)+'</td></tr>').join('');
  document.getElementById('llmSceneTable').innerHTML=html||'<tr><td class="empty" colspan="5">暂无数据</td></tr>';
}

// ── 页签切换 ──
document.querySelectorAll('.rail-item').forEach(item=>{
  item.addEventListener('click',()=>{
    document.querySelectorAll('.rail-item').forEach(i=>i.classList.remove('is-active'));
    item.classList.add('is-active');
    activeTab=item.dataset.tab;
    document.querySelectorAll('.content').forEach(c=>c.style.display='none');
    document.getElementById('tab-'+activeTab).style.display='flex';
    if(activeTab==='llm-logs')fetchLlmLogs();
    if(activeTab==='app-logs')fetchAppLogs();
    if(activeTab==='web-vitals')fetchWebVitals();
    if(activeTab==='overview')loadOverview();
  });
});

// ── LLM 日志 ──
function setLlmLogFilter(f){
  llmLogFilter=f;
  document.querySelectorAll('[data-llm-filter]').forEach(b=>{
    b.classList.toggle('active',b.dataset.llmFilter===f);
  });
  fetchLlmLogs();
}

async function fetchLlmLogs(){
  try{
    const data=await fetchJSON(API_LLM_LOGS+'?status='+llmLogFilter+'&limit=50');
    const logs=data.logs||[];
    document.getElementById('llmLogCount').textContent=data.count+' 条';
    const panel=document.getElementById('llmLogPanel');
    if(!logs.length){panel.innerHTML='<div class="empty">窗口内没有日志记录</div>';return}
    panel.innerHTML=logs.map(l=>{
      const time=l.created_at?new Date(l.created_at).toLocaleTimeString('zh-CN',{hour12:false}):'--';
      const level=l.status==='FAILED'?'ERROR':'INFO';
      return '<div class="log-entry"><span class="log-ts">'+escHtml(time)+'</span>'+
        '<span class="log-level '+level+'">'+escHtml(l.status||'')+'</span>'+
        '<span class="log-msg">'+escHtml(l.scene||'')+' · '+escHtml(l.model||'')+
        (l.error?' — '+escHtml(l.error):'')+'</span>'+
        '<span class="log-source">'+fmtMs(l.duration_ms||0)+' '+(l.cost_usd?fmtCost(l.cost_usd):'')+'</span></div>';
    }).join('');
  }catch(err){
    document.getElementById('llmLogPanel').innerHTML='<div class="empty">读取失败：'+escHtml(err.message)+'</div>';
  }
}

// ── 应用日志 ──
function setAppLogFilter(f){
  appLogFilter=f;
  document.querySelectorAll('[data-log-filter]').forEach(b=>{
    b.classList.toggle('active',b.dataset.logFilter===f);
  });
  fetchAppLogs();
}

async function fetchAppLogs(){
  try{
    const data=await fetchJSON(API_LOGS+'?level='+appLogFilter+'&limit=200');
    const entries=data.entries||[];
    const summary=data.summary||{};
    document.getElementById('appLogCount').textContent=(summary.total!=null?summary.total:entries.length)+' 条';
    const panel=document.getElementById('appLogPanel');
    if(!entries.length){panel.innerHTML='<div class="empty">窗口内没有日志记录</div>';return}
    panel.innerHTML=entries.map(e=>{
      const time=e.ts?new Date(e.ts).toLocaleTimeString('zh-CN',{hour12:false}):'--';
      return '<div class="log-entry"><span class="log-ts">'+escHtml(time)+'</span>'+
        '<span class="log-level '+escHtml(e.level||'INFO')+'">'+escHtml(e.level||'INFO')+'</span>'+
        '<span class="log-msg">'+escHtml(e.logger||'')+': '+escHtml(e.message||'')+'</span>'+
        (e.source?'<span class="log-source">'+escHtml(e.source)+'</span>':'')+'</div>';
    }).join('');
  }catch(err){
    document.getElementById('appLogPanel').innerHTML='<div class="empty">读取失败：'+escHtml(err.message)+'</div>';
  }
}

// ── 前端体验指标 ──
function setWebVitalsNav(nav){
  webVitalsNav=nav;
  document.querySelectorAll('[data-wv-nav]').forEach(b=>{
    b.classList.toggle('active',b.dataset.wvNav===nav);
  });
  fetchWebVitals();
}

function wvFormatValue(metric,value){
  if(value==null)return'--';
  if(metric==='CLS')return Number(value).toFixed(3);
  return Math.round(value)+'ms';
}

function wvRatingClass(rating){
  if(rating==='good')return'ok';
  if(rating==='poor')return'crit';
  if(rating==='needs-improvement')return'warn';
  return'info';
}

function wvRatingLabel(rating){
  if(rating==='good')return'良好';
  if(rating==='poor')return'差';
  if(rating==='needs-improvement')return'待改进';
  return'--';
}

async function fetchWebVitals(){
  try{
    const data=await fetchJSON(API_WEB_VITALS+'?hours=24&navigation_type='+webVitalsNav);
    const metrics=data.metrics||[];
    const byMetric={};
    metrics.forEach(m=>{byMetric[m.metric]=m});
    [['LCP','wvLcp','wvLcpSub'],['INP','wvInp','wvInpSub'],['CLS','wvCls','wvClsSub']].forEach(([metric,valId,subId])=>{
      const m=byMetric[metric];
      const valEl=document.getElementById(valId);
      const subEl=document.getElementById(subId);
      if(!m||m.p75==null){
        valEl.textContent='--';valEl.style.color='';
        subEl.textContent='暂无样本';return;
      }
      valEl.textContent=wvFormatValue(metric,m.p75);
      valEl.style.color=m.rating==='good'?'':(m.rating==='poor'?'var(--crit-text)':m.rating==='needs-improvement'?'var(--warn-text)':'');
      subEl.textContent='P50 '+wvFormatValue(metric,m.p50)+' / P95 '+wvFormatValue(metric,m.p95)+' / '+m.sample_count+' 样本';
    });
    const navLabel={navigate:'首次加载','soft-navigation':'软导航',all:'全部'}[data.navigation_type]||data.navigation_type;
    document.getElementById('webVitalsMeta').textContent=navLabel+' · 共 '+(data.sample_count||0)+' 个样本';
    const routes=data.routes||[];
    document.getElementById('wvRouteTable').innerHTML=routes.length
      ? routes.map(r=>'<tr><td style="word-break:break-all">'+escHtml(r.path)+'</td><td>'+escHtml(r.metric)+'</td>'+
        '<td class="num">'+wvFormatValue(r.metric,r.p75)+'</td><td class="num">'+fmtNum(r.sample_count)+'</td>'+
        '<td class="check-state"><span class="pill '+wvRatingClass(r.rating)+'">'+wvRatingLabel(r.rating)+'</span></td></tr>').join('')
      : '<tr><td class="empty" colspan="5">该窗口内没有样本。上线后由浏览器端上报产生。</td></tr>';
  }catch(err){
    document.getElementById('wvRouteTable').innerHTML='<tr><td class="empty" colspan="5">读取失败：'+escHtml(err.message)+'</td></tr>';
  }
}

// ── 刷新与轮询 ──
function startAutoRefresh(){
  if(refreshTimer)clearInterval(refreshTimer);
  refreshTimer=setInterval(()=>{
    if(document.hidden||!isTabVisible)return;
    if(activeTab==='overview')loadOverview();
  },15000);
}

document.getElementById('refreshBtn').addEventListener('click',()=>{
  if(activeTab==='overview')loadOverview();
  else if(activeTab==='llm-logs')fetchLlmLogs();
  else if(activeTab==='app-logs')fetchAppLogs();
  else if(activeTab==='web-vitals')fetchWebVitals();
});

document.getElementById('timeWindow').addEventListener('change',(e)=>{
  historyHours=parseInt(e.target.value);
  if(activeTab==='overview')loadOverview();
});

document.addEventListener('visibilitychange',()=>{
  isTabVisible=!document.hidden;
  if(isTabVisible&&activeTab==='overview')loadOverview();
});

window.addEventListener('resize',()=>{
  if(lastData)renderOverview(lastData);
});

loadOverview();
startAutoRefresh();
</script>
</body>
</html>
"""


# 后台壳承载系统导航；画布保留监控页签、体检判定、图表和数据请求。
_EMBEDDED_CSS = """
body.embedded .shell{flex-direction:column}
body.embedded .rail{width:100%;flex:0 0 auto;background:var(--surface);color:var(--text-2);border-bottom:1px solid var(--border)}
body.embedded .rail-brand,body.embedded .rail-caption,body.embedded .rail-foot{display:none}
body.embedded .rail-nav{flex-direction:row;flex-wrap:wrap;padding:12px 16px;gap:6px}
body.embedded .rail-item{font-size:13px;color:var(--text-2);padding:7px 12px}
body.embedded .rail-item:hover{background:var(--surface-2);color:var(--text)}
body.embedded .rail-item.is-active{background:var(--accent-soft);color:var(--accent-text)}
body.embedded .rail-item::after,body.embedded .rail-item.is-active::before{display:none}
body.embedded .main{min-height:0}
body.embedded .topbar{position:static;flex-wrap:wrap;padding:12px 16px;background:var(--surface)}
body.embedded .topbar-head h1{display:none}
body.embedded .topbar-tools{flex-wrap:wrap;min-width:0}
body.embedded .content{max-width:none;padding:16px 16px 32px}
"""


@router.get(
    "/api/v1/metrics/dashboard",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def embedded_dashboard():
    """后台壳内的监控画布，沿用管理员鉴权与原大盘数据口径。"""
    html = _DASHBOARD_HTML.replace("</style>", _EMBEDDED_CSS + "</style>", 1)
    return HTMLResponse(html.replace("<body>", '<body class="embedded" data-dashboard="embedded">', 1))
