"""
内置监控大盘 — 自包含 HTML 页面（零外部依赖）。

路由：
  GET /dashboard  →  返回自包含 HTML 页面

页面内嵌 JS 轮询 /api/v1/metrics/snapshot 获取实时指标 + 时间序列，
用纯 Canvas API 绘制交互式趋势图（无 Chart.js / D3 / CDN 依赖）。

图表引擎特性：
- 交互式 tooltip（hover 十字光标 + 数值面板）
- 双 Y 轴支持（不同量级数据同图展示）
- 速率计算（累计值 → req/s、USD/s）
- 渐变面积填充
- KPI 卡片 sparkline 迷你趋势线
- 响应式（ResizeObserver 自动重绘）
- 延迟分位数图表（P50 / P95 / P99）
- 可配置刷新间隔（5s / 10s / 30s / 1m / 5m / 15m / 关闭）
- Page Visibility API：标签页隐藏时自动暂停轮询
- LLM 失败日志面板
- 应用日志面板（内存 ring buffer）
- 进程内存/CPU 指标
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
  --bg:#0b1120;--surface:#151e30;--surface2:#1c2840;--border:#293b5c;
  --text:#e2e8f0;--text-dim:#7c8db0;--text-faint:#4a5b7e;
  --blue:#3b82f6;--cyan:#06b6d4;--green:#22c55e;--amber:#f59e0b;
  --red:#ef4444;--purple:#a855f7;--pink:#ec4899;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.header{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:8px}
.header h1{font-size:17px;font-weight:700;display:flex;align-items:center;gap:8px}
.status-dot{width:10px;height:10px;border-radius:50%;background:var(--green);animation:pulse 2s infinite;flex-shrink:0}
.status-dot.warn{background:var(--amber)}
.status-dot.err{background:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.header-right{display:flex;gap:14px;align-items:center;font-size:12px;color:var(--text-dim);flex-wrap:wrap}
.header-right a{color:var(--blue);text-decoration:none}
.header-right a:hover{text-decoration:underline}
.toggle{display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none}
.toggle input{display:none}
.toggle .track{width:34px;height:18px;background:var(--surface2);border-radius:9px;position:relative;transition:background .2s}
.toggle .track::after{content:'';position:absolute;width:14px;height:14px;border-radius:50%;background:var(--text-dim);top:2px;left:2px;transition:all .2s}
.toggle input:checked+.track{background:var(--blue)}
.toggle input:checked+.track::after{left:18px;background:#fff}
.btn{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer;transition:background .15s}
.btn:hover{background:var(--border)}
.btn.active{background:var(--blue);border-color:var(--blue)}
select.refresh-select{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:6px;font-size:12px;cursor:pointer}

/* Tab bar */
.tab-bar{display:flex;gap:0;padding:0 24px;background:var(--surface);border-bottom:1px solid var(--border)}
.tab{padding:8px 18px;font-size:13px;color:var(--text-dim);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s}
.tab:hover{color:var(--text)}
.tab.active{color:var(--blue);border-bottom-color:var(--blue)}
.tab .badge-count{display:inline-block;background:var(--red);color:#fff;font-size:10px;padding:0 5px;border-radius:8px;margin-left:4px;min-width:16px;text-align:center}

/* KPI Grid */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;padding:14px 24px}
.kpi-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:4px;position:relative;overflow:hidden}
.kpi-label{font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.06em}
.kpi-value{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.kpi-sub{font-size:11px;color:var(--text-faint)}
.kpi-value.green{color:var(--green)}.kpi-value.red{color:var(--red)}
.kpi-value.amber{color:var(--amber)}.kpi-value.blue{color:var(--blue)}
.kpi-value.cyan{color:var(--cyan)}.kpi-value.purple{color:var(--purple)}
.kpi-spark{position:absolute;bottom:0;right:0;width:80px;height:30px;opacity:0.5}

/* Sections */
.section{padding:0 24px 14px}
.section-title{font-size:12px;font-weight:600;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em;display:flex;align-items:center;gap:8px}
.section-title .pill{background:var(--surface2);padding:1px 8px;border-radius:4px;font-size:10px;color:var(--text-faint);font-weight:400}
.chart-box{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;position:relative}
canvas{display:block;width:100%}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.three-col{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:900px){.two-col,.three-col{grid-template-columns:1fr}}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:13px}
table th{text-align:left;padding:7px 10px;color:var(--text-dim);font-weight:600;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase}
table td{padding:7px 10px;border-bottom:1px solid var(--surface);color:var(--text)}
table td.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge.ok{background:#142a1a;color:var(--green)}
.badge.warn{background:#2a200a;color:var(--amber)}
.badge.err{background:#2a0e0e;color:var(--red)}
.badge.closed{background:#142a1a;color:var(--green)}
.badge.open{background:#2a0e0e;color:var(--red)}
.badge.half{background:#2a200a;color:var(--amber)}
.loading{text-align:center;padding:30px;color:var(--text-faint);font-size:13px}

/* Log panels */
.log-panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;max-height:400px;overflow-y:auto;font-family:'SF Mono','Fira Code',monospace;font-size:12px}
.log-entry{padding:4px 12px;border-bottom:1px solid var(--surface);display:flex;gap:8px;align-items:flex-start}
.log-entry:hover{background:var(--surface2)}
.log-ts{color:var(--text-faint);flex-shrink:0;width:70px}
.log-level{flex-shrink:0;width:60px;font-weight:600}
.log-level.ERROR,.log-level.CRITICAL{color:var(--red)}
.log-level.WARNING{color:var(--amber)}
.log-level.INFO{color:var(--blue)}
.log-level.DEBUG{color:var(--text-faint)}
.log-msg{flex:1;word-break:break-word;color:var(--text)}
.log-source{color:var(--text-faint);font-size:11px;margin-left:8px}
.log-filter{display:flex;gap:6px;margin-bottom:8px}
.log-filter .btn{padding:3px 10px}

/* Tooltip */
.chart-tooltip{position:absolute;background:rgba(15,23,42,0.95);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:12px;pointer-events:none;z-index:10;backdrop-filter:blur(4px);display:none;white-space:nowrap}
.chart-tooltip .tt-time{color:var(--text-dim);font-size:11px;margin-bottom:4px}
.chart-tooltip .tt-row{display:flex;align-items:center;gap:6px;margin:2px 0}
.chart-tooltip .tt-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.chart-tooltip .tt-label{color:var(--text-dim)}
.chart-tooltip .tt-val{font-weight:600;font-variant-numeric:tabular-nums;margin-left:auto}
</style>
</head>
<body>
<div class="header">
  <h1><span class="status-dot" id="statusDot"></span>TopicEye 监控大盘</h1>
  <div class="header-right">
    <span id="uptime">运行时间: --</span>
    <span id="lastUpdate">最后更新: --</span>
    <label class="toggle">
      <input type="checkbox" id="rateMode" checked>
      <span class="track"></span>
      <span>速率</span>
    </label>
    <span>刷新:</span>
    <select class="refresh-select" id="refreshInterval">
      <option value="5000">5s</option>
      <option value="10000" selected>10s</option>
      <option value="30000">30s</option>
      <option value="60000">1m</option>
      <option value="300000">5m</option>
      <option value="900000">15m</option>
      <option value="0">关闭</option>
    </select>
    <a href="/metrics" target="_blank">Prometheus</a>
    <a href="/health/ready" target="_blank">健康</a>
    <button class="btn" onclick="fetchData()">刷新</button>
  </div>
</div>

<div class="tab-bar">
  <div class="tab active" data-tab="overview">概览</div>
  <div class="tab" data-tab="llm-logs">LLM 日志 <span class="badge-count" id="llmFailCount" style="display:none">0</span></div>
  <div class="tab" data-tab="app-logs">应用日志</div>
</div>

<!-- ── Tab: Overview ── -->
<div id="tab-overview" class="tab-content">
<div class="kpi-grid" id="kpiGrid">
  <div class="kpi-card">
    <div class="kpi-label">HTTP 请求总数</div>
    <div class="kpi-value blue" id="kpiTotalReq">--</div>
    <div class="kpi-sub" id="kpiReqRate">-- req/s</div>
    <canvas class="kpi-spark" id="sparkReq" width="80" height="30"></canvas>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">错误率 (5xx)</div>
    <div class="kpi-value" id="kpiErrorRate">--</div>
    <div class="kpi-sub" id="kpiErrors">5xx: --</div>
    <canvas class="kpi-spark" id="sparkErr" width="80" height="30"></canvas>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">HTTP P95 延迟</div>
    <div class="kpi-value cyan" id="kpiP95">--</div>
    <div class="kpi-sub" id="kpiLatencySub">P50: -- / P99: --</div>
    <canvas class="kpi-spark" id="sparkLat" width="80" height="30"></canvas>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">LLM 调用</div>
    <div class="kpi-value green" id="kpiLlmCalls">--</div>
    <div class="kpi-sub" id="kpiLlmSuccess">成功率: --</div>
    <canvas class="kpi-spark" id="sparkLlm" width="80" height="30"></canvas>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">LLM 成本 (USD)</div>
    <div class="kpi-value amber" id="kpiLlmCost">--</div>
    <div class="kpi-sub" id="kpiLlmTokens">Token: --</div>
    <canvas class="kpi-spark" id="sparkCost" width="80" height="30"></canvas>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">DB 连接池</div>
    <div class="kpi-value purple" id="kpiDbPool">--</div>
    <div class="kpi-sub" id="kpiDbUtil">利用率: --</div>
    <canvas class="kpi-spark" id="sparkDb" width="80" height="30"></canvas>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">进程内存 (RSS)</div>
    <div class="kpi-value" id="kpiMem" style="color:var(--pink)">--</div>
    <div class="kpi-sub" id="kpiCpu">CPU: --</div>
    <canvas class="kpi-spark" id="sparkMem" width="80" height="30"></canvas>
  </div>
</div>

<div class="section">
  <div class="section-title">请求速率 & 错误趋势 <span class="pill" id="tsRange">最近 30 分钟</span></div>
  <div class="chart-box">
    <canvas id="chartRequests" height="200"></canvas>
    <div class="chart-tooltip" id="ttRequests"></div>
  </div>
</div>

<div class="section">
  <div class="two-col">
    <div>
      <div class="section-title">LLM 调用 & 成本趋势</div>
      <div class="chart-box">
        <canvas id="chartLlm" height="200"></canvas>
        <div class="chart-tooltip" id="ttLlm"></div>
      </div>
    </div>
    <div>
      <div class="section-title">HTTP 延迟分位数 (P50 / P95 / P99)</div>
      <div class="chart-box">
        <canvas id="chartLatency" height="200"></canvas>
        <div class="chart-tooltip" id="ttLatency"></div>
      </div>
    </div>
  </div>
</div>

<div class="section">
  <div class="two-col">
    <div>
      <div class="section-title">DB 连接池利用趋势</div>
      <div class="chart-box">
        <canvas id="chartDbPool" height="180"></canvas>
        <div class="chart-tooltip" id="ttDbPool"></div>
      </div>
    </div>
    <div>
      <div class="section-title">LLM 延迟分位数 (P50 / P95 / P99)</div>
      <div class="chart-box">
        <canvas id="chartLlmLatency" height="180"></canvas>
        <div class="chart-tooltip" id="ttLlmLatency"></div>
      </div>
    </div>
  </div>
</div>

<div class="section">
  <div class="two-col">
    <div>
      <div class="section-title">熔断器 & 缓存状态</div>
      <div class="chart-box">
        <table>
          <tr><th>组件</th><th>状态</th><th class="num">详情</th></tr>
          <tr><td>LLM 熔断器</td><td><span class="badge" id="cbBadge">--</span></td><td class="num" id="cbDetail">--</td></tr>
          <tr><td>LLM 响应缓存</td><td><span class="badge" id="cacheBadge">--</span></td><td class="num" id="cacheDetail">--</td></tr>
          <tr><td>慢查询累计</td><td><span class="badge" id="slowBadge">--</span></td><td class="num" id="slowDetail">--</td></tr>
        </table>
      </div>
    </div>
    <div>
      <div class="section-title">Top 请求路径</div>
      <div class="chart-box">
        <table>
          <thead><tr><th>路径</th><th class="num">请求数</th></tr></thead>
          <tbody id="topPathsTable"><tr><td colspan="2" class="loading">加载中...</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">LLM 各场景调用明细</div>
  <div class="chart-box">
    <table>
      <thead><tr><th>场景</th><th class="num">成功</th><th class="num">失败</th><th class="num">Token</th><th class="num">成本 (USD)</th><th class="num">P95 延迟</th></tr></thead>
      <tbody id="llmSceneTable"><tr><td colspan="6" class="loading">加载中...</td></tr></tbody>
    </table>
  </div>
</div>
</div>

<!-- ── Tab: LLM Logs ── -->
<div id="tab-llm-logs" class="tab-content" style="display:none;padding:14px 24px">
  <div class="section-title">LLM 调用日志（最近 24h） <span class="pill" id="llmLogCount">0 条</span></div>
  <div class="log-filter">
    <button class="btn active" data-llm-filter="FAILED" onclick="setLlmLogFilter('FAILED')">仅失败</button>
    <button class="btn" data-llm-filter="ALL" onclick="setLlmLogFilter('ALL')">全部</button>
    <button class="btn" onclick="fetchLlmLogs()">刷新</button>
  </div>
  <div class="log-panel" id="llmLogPanel">
    <div class="loading">点击刷新加载...</div>
  </div>
</div>

<!-- ── Tab: App Logs ── -->
<div id="tab-app-logs" class="tab-content" style="display:none;padding:14px 24px">
  <div class="section-title">应用日志（内存 Ring Buffer） <span class="pill" id="appLogCount">0 条</span></div>
  <div class="log-filter">
    <button class="btn active" data-log-filter="ALL" onclick="setAppLogFilter('ALL')">全部</button>
    <button class="btn" data-log-filter="ERROR" onclick="setAppLogFilter('ERROR')">ERROR</button>
    <button class="btn" data-log-filter="WARNING" onclick="setAppLogFilter('WARNING')">WARNING</button>
    <button class="btn" data-log-filter="INFO" onclick="setAppLogFilter('INFO')">INFO</button>
    <button class="btn" onclick="fetchAppLogs()">刷新</button>
  </div>
  <div class="log-panel" id="appLogPanel">
    <div class="loading">点击刷新加载...</div>
  </div>
</div>

<script>
const API = window.location.origin + '/api/v1/metrics/snapshot';
const API_HISTORY = window.location.origin + '/api/v1/metrics/history';
const API_LOGS = window.location.origin + '/api/v1/metrics/logs';
const API_LLM_LOGS = window.location.origin + '/api/v1/metrics/llm-logs';
let lastData = null;
let refreshTimer = null;
let currentRefreshMs = 10000;
let isTabVisible = true;
let activeTab = 'overview';
let llmLogFilter = 'FAILED';
let appLogFilter = 'ALL';
let memHistory = [];

// ── Utilities ──
function fmtNum(n){if(n==null||n===undefined)return'--';if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return String(n)}
function fmtCost(n){return n!=null?'$'+n.toFixed(4):'--'}
function fmtMs(s){if(s==null||s===0)return'--';if(s<1)return(s*1000).toFixed(0)+'ms';return s.toFixed(2)+'s'}
function fmtTime(s){if(!s)return'--';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);if(h>0)return h+'h '+m+'m';if(m>0)return m+'m '+sec+'s';return sec+'s'}
function fmtClock(ts){if(!ts)return'--';return new Date(ts*1000).toLocaleTimeString('zh-CN',{hour12:false})}
function fmtMb(mb){if(mb==null)return'--';if(mb>=1024)return(mb/1024).toFixed(1)+'GB';return mb.toFixed(0)+'MB'}
function escHtml(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// Calculate rate (delta/s) from cumulative time series
function calcRate(ts, key){
  if(!ts||ts.length<2)return[];
  const rates=[];
  for(let i=1;i<ts.length;i++){
    const dt=ts[i].ts-ts[i-1].ts;
    if(dt<=0){rates.push({t:ts[i].ts,v:0});continue}
    rates.push({t:ts[i].ts,v:(ts[i][key]-ts[i-1][key])/dt});
  }
  return rates;
}

// ── Sparkline renderer ──
function drawSparkline(canvasId, data, color){
  const c=document.getElementById(canvasId);
  if(!c)return;
  const ctx=c.getContext('2d');
  const dpr=window.devicePixelRatio||1;
  const W=c.offsetWidth||80,H=c.offsetHeight||30;
  c.width=W*dpr;c.height=H*dpr;
  ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,W,H);
  if(!data||data.length<2){
    ctx.fillStyle='#4a5b7e';ctx.font='9px monospace';ctx.textAlign='center';
    ctx.fillText('···',W/2,H/2);return;
  }
  let min=Infinity,max=-Infinity;
  for(const d of data){if(d.v<min)min=d.v;if(d.v>max)max=d.v}
  if(min===max){min-=1;max+=1}
  const pad=2;
  const grad=ctx.createLinearGradient(0,0,0,H);
  grad.addColorStop(0,color+'40');
  grad.addColorStop(1,color+'00');
  ctx.beginPath();
  for(let i=0;i<data.length;i++){
    const x=pad+(i/(data.length-1))*(W-2*pad);
    const y=pad+(1-(data[i].v-min)/(max-min))*(H-2*pad);
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  }
  ctx.lineTo(W-pad,H-pad);
  ctx.lineTo(pad,H-pad);
  ctx.closePath();
  ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();
  for(let i=0;i<data.length;i++){
    const x=pad+(i/(data.length-1))*(W-2*pad);
    const y=pad+(1-(data[i].v-min)/(max-min))*(H-2*pad);
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  }
  ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.stroke();
}

// ── Interactive Chart Engine ──
class InteractiveChart{
  constructor(canvasId,tooltipId,options){
    this.canvas=document.getElementById(canvasId);
    this.tooltip=document.getElementById(tooltipId);
    this.ctx=this.canvas.getContext('2d');
    this.opts=Object.assign({leftAxis:true,rightAxis:false,pad:{top:12,right:12,bottom:22,left:52}},options);
    this.series=[];
    this.hoverIdx=-1;
    this.hoverX=null;
    this.bindEvents();
    if(window.ResizeObserver){
      new ResizeObserver(()=>this.render()).observe(this.canvas.parentElement);
    }
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
  setData(series){
    this.series=series||[];
    this.render();
  }
  render(){
    const ctx=this.ctx,dpr=window.devicePixelRatio||1;
    const W=this.canvas.offsetWidth,H=this.canvas.offsetHeight||200;
    this.canvas.width=W*dpr;this.canvas.height=H*dpr;
    ctx.scale(dpr,dpr);
    ctx.clearRect(0,0,W,H);
    const pad=this.opts.pad;
    const cw=W-pad.left-pad.right,ch=H-pad.top-pad.bottom;
    if(!this.series.length||this.series[0].data.length===0){
      ctx.fillStyle='#4a5b7e';ctx.font='13px sans-serif';ctx.textAlign='center';
      ctx.fillText('暂无数据（等待采样中...）',W/2,H/2);return;
    }
    const hasRight=this.opts.rightAxis&&this.series.some(s=>s.axis==='right');
    let lMin=Infinity,lMax=-Infinity,rMin=Infinity,rMax=-Infinity;
    for(const s of this.series){
      for(const p of s.data){
        if(s.axis==='right'){
          if(p.v<rMin)rMin=p.v;if(p.v>rMax)rMax=p.v;
        }else{
          if(p.v<lMin)lMin=p.v;if(p.v>lMax)lMax=p.v;
        }
      }
    }
    if(lMin===lMax){lMin-=1;lMax+=1}
    if(rMin===rMax){rMin-=1;rMax+=1}
    const lRange=lMax-lMin,rRange=rMax-rMin;
    lMin-=lRange*0.1;lMax+=lRange*0.1;
    rMin-=rRange*0.1;rMax+=rRange*0.1;
    const data=this.series[0].data;
    const minTs=data[0].t,maxTs=data[data.length-1].t;
    const tsRange=(maxTs-minTs)||1;
    ctx.strokeStyle='#1c2840';ctx.lineWidth=0.5;
    ctx.font='10px monospace';ctx.fillStyle='#4a5b7e';
    ctx.textAlign='right';
    for(let i=0;i<=4;i++){
      const y=pad.top+(ch/4)*i;
      ctx.beginPath();ctx.setLineDash([3,4]);ctx.moveTo(pad.left,y);ctx.lineTo(pad.left+cw,y);ctx.stroke();
      const lVal=lMax-((lMax-lMin)/4)*i;
      ctx.fillText(fmtNum(lVal),pad.left-6,y+3);
    }
    ctx.setLineDash([]);
    if(hasRight){
      ctx.textAlign='left';
      for(let i=0;i<=4;i++){
        const y=pad.top+(ch/4)*i;
        const rVal=rMax-((rMax-rMin)/4)*i;
        ctx.fillStyle='#4a5b7e';
        ctx.fillText(fmtNum(rVal),pad.left+cw+6,y+3);
      }
    }
    ctx.textAlign='center';ctx.fillStyle='#4a5b7e';
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
        grad.addColorStop(1,'rgba(0,0,0,0)');
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
      ctx.strokeStyle='rgba(124,141,176,0.4)';ctx.lineWidth=1;ctx.setLineDash([4,3]);
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
        ctx.strokeStyle='#0b1120';ctx.lineWidth=2;ctx.stroke();
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
    ctx.font='11px sans-serif';ctx.textAlign='left';
    let lx=pad.left+8;
    for(const s of this.series){
      ctx.fillStyle=s.color;
      ctx.fillRect(lx,pad.top+2,14,3);
      ctx.fillStyle='#7c8db0';
      ctx.fillText(s.label,lx+18,pad.top+7);
      lx+=ctx.measureText(s.label).width+44;
    }
  }
}

// ── Chart instances ──
const chartReq=new InteractiveChart('chartRequests','ttRequests',{leftAxis:true});
const chartLlm=new InteractiveChart('chartLlm','ttLlm',{leftAxis:true,rightAxis:true});
const chartLat=new InteractiveChart('chartLatency','ttLatency',{leftAxis:true});
const chartDb=new InteractiveChart('chartDbPool','ttDbPool',{leftAxis:true});
const chartLlmLat=new InteractiveChart('chartLlmLatency','ttLlmLatency',{leftAxis:true});

// ── Data fetching ──
async function fetchJSON(url){
  const r=await fetch(url);
  if(!r.ok)throw new Error(url+' -> '+r.status);
  return r.json();
}

function fetchData(){
  fetchJSON(API).then(d=>{
    lastData=d;renderData(d);
  }).catch(err=>{
    document.getElementById('lastUpdate').textContent='获取失败: '+err.message;
    document.getElementById('statusDot').className='status-dot err';
  });
}

function renderData(data){
  const snap=data.snapshot||{};
  const ts=data.timeseries||[];
  const cb=data.circuit_breaker||{};
  const cache=data.llm_cache||{};
  const slow=data.slow_queries||0;
  const proc=data.process||{};
  const rateMode=document.getElementById('rateMode').checked;

  // Status dot
  const errRate=snap.http?.error_rate||0;
  const dot=document.getElementById('statusDot');
  if(errRate>5)dot.className='status-dot err';
  else if(errRate>1||cb.state==='OPEN')dot.className='status-dot warn';
  else dot.className='status-dot';

  // KPI cards
  document.getElementById('kpiTotalReq').textContent=fmtNum(snap.http?.total_requests);
  const reqRate=ts.length>=2?(ts[ts.length-1].total_requests-(ts[ts.length-2]?.total_requests||0))/Math.max(ts[ts.length-1].ts-ts[ts.length-2].ts,1):0;
  document.getElementById('kpiReqRate').textContent=reqRate.toFixed(1)+' req/s';

  const errEl=document.getElementById('kpiErrorRate');
  errEl.textContent=(snap.http?.error_rate??0).toFixed(2)+'%';
  errEl.className='kpi-value '+(errRate>5?'red':errRate>1?'amber':'green');
  document.getElementById('kpiErrors').textContent='5xx: '+(snap.http?.total_errors_5xx||0);

  const lat=snap.http?.latency||{};
  document.getElementById('kpiP95').textContent=fmtMs(lat.p95);
  document.getElementById('kpiLatencySub').textContent='P50: '+fmtMs(lat.p50)+' / P99: '+fmtMs(lat.p99);

  document.getElementById('kpiLlmCalls').textContent=fmtNum(snap.llm?.total_calls);
  document.getElementById('kpiLlmSuccess').textContent='成功率: '+(snap.llm?.success_rate??0).toFixed(1)+'%';
  document.getElementById('kpiLlmCost').textContent=fmtCost(snap.llm?.total_cost_usd);
  document.getElementById('kpiLlmTokens').textContent='Token: '+fmtNum((snap.llm?.total_input_tokens||0)+(snap.llm?.total_output_tokens||0));
  document.getElementById('kpiDbPool').textContent=(snap.db_pool?.checked_out||0)+' / '+(snap.db_pool?.size||0);
  document.getElementById('kpiDbUtil').textContent='利用率: '+(snap.db_pool?.utilization??0).toFixed(0)+'%';

  // Process metrics
  const rssMb=proc.process_rss_mb||0;
  document.getElementById('kpiMem').textContent=fmtMb(rssMb);
  document.getElementById('kpiCpu').textContent='CPU: '+(proc.process_cpu_user_s||0).toFixed(1)+'s user / '+(proc.process_cpu_sys_s||0).toFixed(1)+'s sys';
  // Track memory history for sparkline
  if(rssMb>0){
    memHistory.push({t:Date.now()/1000,v:rssMb});
    if(memHistory.length>30)memHistory.shift();
  }

  document.getElementById('uptime').textContent='运行时间: '+fmtTime(snap.uptime_seconds);
  document.getElementById('lastUpdate').textContent='最后更新: '+new Date().toLocaleTimeString('zh-CN',{hour12:false});

  // Circuit breaker
  const cbBadge=document.getElementById('cbBadge');
  cbBadge.textContent=cb.state||'UNKNOWN';
  cbBadge.className='badge '+(cb.state==='CLOSED'?'closed':cb.state==='OPEN'?'open':'half');
  document.getElementById('cbDetail').textContent='失败: '+(cb.failure_count||0)+'/'+(cb.failure_threshold||5);

  // Cache
  const cacheBadge=document.getElementById('cacheBadge');
  const hitRate=cache.hit_rate||0;
  cacheBadge.textContent=hitRate>0.3?'有效':hitRate>0?'低':'无';
  cacheBadge.className='badge '+(hitRate>0.3?'ok':hitRate>0?'warn':'err');
  document.getElementById('cacheDetail').textContent='命中: '+(cache.hits||0)+'/'+((cache.hits||0)+(cache.misses||0))+' ('+(hitRate*100).toFixed(1)+'%)';

  // Slow queries
  const slowBadge=document.getElementById('slowBadge');
  slowBadge.textContent=slow>50?'高':slow>10?'中':'正常';
  slowBadge.className='badge '+(slow>50?'err':slow>10?'warn':'ok');
  document.getElementById('slowDetail').textContent=slow+' 次';

  // Top paths
  const topPaths=snap.http?.top_paths||[];
  const tpTable=document.getElementById('topPathsTable');
  tpTable.innerHTML=topPaths.length?topPaths.map(p=>'<tr><td>'+escHtml(p.path)+'</td><td class="num">'+p.count+'</td></tr>').join(''):'<tr><td colspan="2" style="text-align:center;color:#4a5b7e">暂无数据</td></tr>';

  // LLM scene table
  const scenes=snap.llm?.by_scene||{};
  let sceneHtml='';
  for(const[scene,d]of Object.entries(scenes)){
    sceneHtml+='<tr><td>'+escHtml(scene)+'</td><td class="num">'+(d.done||0)+'</td><td class="num">'+(d.failed||0)+'</td><td class="num">'+fmtNum(d.tokens||0)+'</td><td class="num">'+fmtCost(d.cost||0)+'</td><td class="num">--</td></tr>';
  }
  document.getElementById('llmSceneTable').innerHTML=sceneHtml||'<tr><td colspan="6" style="text-align:center;color:#4a5b7e">暂无数据</td></tr>';

  // Sparklines
  const tsReq=ts.map(p=>({t:p.ts,v:p.total_requests}));
  const tsErr=ts.map(p=>({t:p.ts,v:p.total_errors_5xx}));
  const tsLlm=ts.map(p=>({t:p.ts,v:p.total_llm_calls}));
  const tsCost=ts.map(p=>({t:p.ts,v:p.total_llm_cost_usd}));
  const tsDb=ts.map(p=>({t:p.ts,v:p.db_pool_checked_out}));
  const tsReqRate=calcRate(ts,'total_requests');
  drawSparkline('sparkReq',tsReqRate,'#3b82f6');
  drawSparkline('sparkErr',tsErr,'#ef4444');
  drawSparkline('sparkLat',tsReqRate,'#06b6d4');
  drawSparkline('sparkLlm',tsLlm,'#22c55e');
  drawSparkline('sparkCost',tsCost,'#f59e0b');
  drawSparkline('sparkDb',tsDb,'#a855f7');
  drawSparkline('sparkMem',memHistory,'#ec4899');

  // ── Main charts ──
  if(rateMode){
    const reqRates=calcRate(ts,'total_requests');
    const errRates=calcRate(ts,'total_errors_5xx');
    chartReq.setData([
      {label:'请求/s',color:'#3b82f6',fill:'rgba(59,130,246,0.15)',data:reqRates,fmt:v=>v.toFixed(1)},
      {label:'错误/s',color:'#ef4444',data:errRates,fmt:v=>v.toFixed(1)},
    ]);
    const llmRates=calcRate(ts,'total_llm_calls');
    const costRates=calcRate(ts,'total_llm_cost_usd');
    chartLlm.setData([
      {label:'LLM 调用/s',color:'#22c55e',fill:'rgba(34,197,94,0.15)',data:llmRates,fmt:v=>v.toFixed(2)},
      {label:'成本/s (USD)',color:'#f59e0b',axis:'right',data:costRates,fmt:v=>'$'+v.toFixed(4)},
    ]);
  }else{
    chartReq.setData([
      {label:'请求总数',color:'#3b82f6',fill:'rgba(59,130,246,0.15)',data:ts.map(p=>({t:p.ts,v:p.total_requests}))},
      {label:'5xx 错误',color:'#ef4444',data:ts.map(p=>({t:p.ts,v:p.total_errors_5xx}))},
    ]);
    chartLlm.setData([
      {label:'LLM 调用',color:'#22c55e',fill:'rgba(34,197,94,0.15)',data:ts.map(p=>({t:p.ts,v:p.total_llm_calls}))},
      {label:'成本 (USD)',color:'#f59e0b',axis:'right',data:ts.map(p=>({t:p.ts,v:p.total_llm_cost_usd})),fmt:v=>'$'+v.toFixed(4)},
    ]);
  }

  chartDb.setData([
    {label:'已借出',color:'#a855f7',fill:'rgba(168,85,247,0.15)',data:ts.map(p=>({t:p.ts,v:p.db_pool_checked_out}))},
    {label:'池大小',color:'#4a5b7e',data:ts.map(p=>({t:p.ts,v:p.db_pool_size}))},
  ]);

  const latSnap=snap.http?.latency||{};
  const llmLatSnap=snap.llm?.latency||{};
  const reqRateTs=calcRate(ts,'total_requests');
  chartLat.setData([
    {label:'P50 ('+fmtMs(latSnap.p50)+')',color:'#22c55e',data:reqRateTs.map(p=>({t:p.t,v:latSnap.p50||0})),fmt:v=>fmtMs(v)},
    {label:'P95 ('+fmtMs(latSnap.p95)+')',color:'#f59e0b',data:reqRateTs.map(p=>({t:p.t,v:latSnap.p95||0})),fmt:v=>fmtMs(v)},
    {label:'P99 ('+fmtMs(latSnap.p99)+')',color:'#ef4444',data:reqRateTs.map(p=>({t:p.t,v:latSnap.p99||0})),fmt:v=>fmtMs(v)},
  ]);
  chartLlmLat.setData([
    {label:'P50 ('+fmtMs(llmLatSnap.p50)+')',color:'#22c55e',data:reqRateTs.map(p=>({t:p.t,v:llmLatSnap.p50||0})),fmt:v=>fmtMs(v)},
    {label:'P95 ('+fmtMs(llmLatSnap.p95)+')',color:'#f59e0b',data:reqRateTs.map(p=>({t:p.t,v:llmLatSnap.p95||0})),fmt:v=>fmtMs(v)},
    {label:'P99 ('+fmtMs(llmLatSnap.p99)+')',color:'#ef4444',data:reqRateTs.map(p=>({t:p.t,v:llmLatSnap.p99||0})),fmt:v=>fmtMs(v)},
  ]);
}

// ── Auto refresh with Page Visibility ──
function startAutoRefresh(){
  if(refreshTimer)clearInterval(refreshTimer);
  if(currentRefreshMs<=0)return; // 关闭
  refreshTimer=setInterval(()=>{
    if(document.hidden||!isTabVisible)return; // 标签页隐藏时暂停
    if(activeTab==='overview')fetchData();
  },currentRefreshMs);
}

document.getElementById('refreshInterval').addEventListener('change',(e)=>{
  currentRefreshMs=parseInt(e.target.value);
  startAutoRefresh();
  if(currentRefreshMs>0&&activeTab==='overview')fetchData();
});

// Page Visibility API
document.addEventListener('visibilitychange',()=>{
  isTabVisible=!document.hidden;
  if(isTabVisible&&currentRefreshMs>0&&activeTab==='overview'){
    fetchData(); // 回到页面时立即刷新一次
  }
});

// Rate mode toggle
document.getElementById('rateMode').addEventListener('change',()=>{
  if(lastData)renderData(lastData);
});

// Window resize
window.addEventListener('resize',()=>{
  if(lastData)renderData(lastData);
});

// ── Tab switching ──
document.querySelectorAll('.tab').forEach(tab=>{
  tab.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    tab.classList.add('active');
    activeTab=tab.dataset.tab;
    document.querySelectorAll('.tab-content').forEach(c=>c.style.display='none');
    document.getElementById('tab-'+activeTab).style.display='block';
    if(activeTab==='llm-logs')fetchLlmLogs();
    if(activeTab==='app-logs')fetchAppLogs();
  });
});

// ── LLM Logs ──
function setLlmLogFilter(f){
  llmLogFilter=f;
  document.querySelectorAll('[data-llm-filter]').forEach(b=>{
    b.classList.toggle('active',b.dataset.llmFilter===f);
  });
  fetchLlmLogs();
}

async function fetchLlmLogs(){
  try{
    const url=API_LLM_LOGS+'?status='+llmLogFilter+'&limit=50';
    const data=await fetchJSON(url);
    const logs=data.logs||[];
    document.getElementById('llmLogCount').textContent=data.count+' 条';
    const panel=document.getElementById('llmLogPanel');
    if(!logs.length){
      panel.innerHTML='<div class="loading">暂无日志记录</div>';
      return;
    }
    panel.innerHTML=logs.map(l=>{
      const cls=l.status==='FAILED'?'err':'ok';
      const time=l.created_at?new Date(l.created_at).toLocaleTimeString('zh-CN',{hour12:false}):'--';
      return '<div class="log-entry"><span class="log-ts">'+time+'</span><span class="log-level '+(l.status==='FAILED'?'ERROR':'INFO')+'">'+l.status+'</span><span class="log-msg">'+escHtml(l.scene)+' / '+escHtml(l.model)+' — '+(l.error?escHtml(l.error):'OK')+' <span class="log-source">['+l.duration_ms+'ms, $'+(l.cost_usd||0).toFixed(4)+', in:'+l.input_tokens+'/out:'+l.output_tokens+']</span></span></div>';
    }).join('');
  }catch(err){
    document.getElementById('llmLogPanel').innerHTML='<div class="loading">加载失败: '+escHtml(err.message)+'</div>';
  }
}

// ── App Logs ──
function setAppLogFilter(f){
  appLogFilter=f;
  document.querySelectorAll('[data-log-filter]').forEach(b=>{
    b.classList.toggle('active',b.dataset.logFilter===f);
  });
  fetchAppLogs();
}

async function fetchAppLogs(){
  try{
    const url=API_LOGS+'?level='+appLogFilter+'&limit=200';
    const data=await fetchJSON(url);
    const entries=data.entries||[];
    const summary=data.summary||{};
    document.getElementById('appLogCount').textContent=summary.total+' 条 / 上限 '+summary.capacity;
    const panel=document.getElementById('appLogPanel');
    if(!entries.length){
      panel.innerHTML='<div class="loading">暂无日志记录</div>';
      return;
    }
    panel.innerHTML=entries.map(e=>{
      const time=e.ts?new Date(e.ts).toLocaleTimeString('zh-CN',{hour12:false}):'--';
      return '<div class="log-entry"><span class="log-ts">'+time+'</span><span class="log-level '+e.level+'">'+e.level+'</span><span class="log-msg">'+escHtml(e.logger)+': '+escHtml(e.message)+' <span class="log-source">'+escHtml(e.source||'')+'</span></span></div>';
    }).join('');
  }catch(err){
    document.getElementById('appLogPanel').innerHTML='<div class="loading">加载失败: '+escHtml(err.message)+'</div>';
  }
}

// ── Init ──
fetchData();
startAutoRefresh();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(get_current_admin_user)])
async def dashboard():
    """内置监控大盘（自包含 HTML，零外部依赖；仅管理员可见）。"""
    return HTMLResponse(content=_DASHBOARD_HTML)
