'use client';

import {
  AlertTriangle,
  Bookmark,
  BookmarkCheck,
  CheckCircle2,
  ExternalLink,
  Filter,
  GitBranch,
  Minus,
  PenLine,
  Plus,
  RefreshCw,
  SlidersHorizontal,
  TimerReset,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Badge, Button, Metric, Panel, Toolbar } from '@/components/ui';
import { T } from '@/lib/design-tokens';
import type { FeedbackType, ScoringFlowResponse, ScoringFlowSample } from '@/lib/api';

// 历史本地 COLORS 对象已删除，统一引用 @/lib/design-tokens.T。
// T 对象字段与原 COLORS 逐字相同（primary/teal/purple/amber/red/gray 系列）。

const STAGE_COLORS: Record<string, { color: string; bg: string; border: string; soft: string }> = {
  candidates: { color: T.gray700, bg: T.gray50, border: T.gray200, soft: '#F8FAFC' },
  quality: { color: T.teal, bg: T.tealLight, border: T.tealBorder, soft: '#F2FFFC' },
  risk: { color: T.amber, bg: T.amberLight, border: T.amberBorder, soft: '#FFFBEB' },
  freshness: { color: '#3B82F6', bg: '#EFF6FF', border: '#BFDBFE', soft: '#F8FBFF' },
  diversity: { color: T.purple, bg: T.purpleLight, border: T.purpleBorder, soft: '#FBF8FF' },
  selected: { color: T.primary, bg: T.primaryLight, border: T.primaryBorder, soft: '#FFF9F6' },
};

const MIX_TONES = {
  purple: { color: T.purple, bg: T.purpleLight, border: T.purpleBorder },
  teal: { color: T.teal, bg: T.tealLight, border: T.tealBorder },
} as const;

function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

function fmt(value: number | undefined, digits = 1) {
  return Number(value ?? 0).toFixed(digits);
}

function windowLabel(hours: number) {
  if (hours === 720) return '30 天';
  if (hours === 168) return '7 天';
  if (hours === 24) return '24 小时';
  return `${hours} 小时`;
}

function emptyReasonText(reason?: string) {
  const map: Record<string, { title: string; detail: string; action: string }> = {
    no_analyzed_content: {
      title: '还没有可评分内容',
      detail: '评分流程只读取已经写入 AI 分析结果的内容。当前数据库里还没有可用于评分的分析记录。',
      action: '先同步信源并运行内容分析，再回到这里查看评分路径。',
    },
    collected_not_analyzed: {
      title: '内容已采集，仍在等待分析',
      detail: '当前窗口有新内容进入内容流，但这些内容还没有写入 AI 分析结果，所以暂时不能进入评分漏斗。',
      action: '先运行内容分析任务；分析完成后，24 小时窗口会出现评分样本。',
    },
    no_content_in_window: {
      title: '当前观察窗口没有样本',
      detail: '数据库里有已分析内容，但不在当前时间窗口内。',
      action: '切换到 7 天或 30 天窗口查看历史样本，或刷新信源获取近期内容。',
    },
    candidate_limit_empty: {
      title: '候选查询没有返回内容',
      detail: '候选池查询结果为空，可能被忽略列表或筛选条件全部排除。',
      action: '检查忽略列表、内容状态和信源同步结果。',
    },
    no_scoring_inputs: {
      title: '候选内容缺少评分输入',
      detail: '候选内容存在，但没有足够的分析维度构造成评分输入。',
      action: '检查内容分析任务是否完整写入了质量、风险、创作价值等字段。',
    },
    all_candidates_filtered: {
      title: '候选被风险或规则过滤',
      detail: '评分输入存在，但进入评分引擎后没有样本留下。',
      action: '检查风险阈值、内容状态和评分配置。',
    },
    ok: {
      title: '评分流程正常',
      detail: '当前窗口有可评分样本。',
      action: '点击候选样本查看评分路径。',
    },
  };
  return map[reason || ''] || {
    title: '评分流程暂无样本',
    detail: '当前返回没有候选样本，原因未明确标记。',
    action: '刷新页面或扩大观察窗口后再检查。',
  };
}

function FactorBar({ label, value, color }: { label: string; value: number; color: string }) {
  const width = Math.max(4, Math.min(100, value * 100));
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-[11px] text-gray-500">
        <span>{label}</span>
        <span className="font-mono">{fmt(value, 2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
        <div className="h-full rounded-full" style={{ width: `${width}%`, background: color }} />
      </div>
    </div>
  );
}

function ProgressRow({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="grid grid-cols-[78px_minmax(0,1fr)_46px] items-center gap-2">
      <div className="truncate text-xs text-gray-500">{label}</div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
        <div className="h-full rounded-full" style={{ width: `${Math.max(3, Math.min(100, value))}%`, background: color }} />
      </div>
      <div className="text-right font-mono text-[11px] text-gray-600">{fmt(value)}</div>
    </div>
  );
}

export function AlgorithmHeader({
  hours,
  loading,
  onHoursChange,
  onRefresh,
}: {
  hours: number;
  loading: boolean;
  onHoursChange: (hours: number) => void;
  onRefresh: () => void;
}) {
  return (
    <header className="relative mb-5 overflow-hidden rounded-lg border border-gray-200 bg-white px-5 py-5 shadow-[0_14px_36px_rgba(15,23,42,0.06)]">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary to-teal" />
      <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge tone="primary" className="gap-1.5 font-mono">
              <GitBranch size={13} strokeWidth={2.4} />
              SCORING FLOW
            </Badge>
            <span className="text-xs font-bold text-gray-500">最近 {windowLabel(hours)}</span>
          </div>
          <h1 className="m-0 text-[28px] font-black leading-tight text-gray-900">算法流程</h1>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-gray-500">
            从候选样本进入评分漏斗，沿质量、风险、时效和多样性路径扣分或加权，最终形成精选输出；人工反馈会回写到样本的路径分。
          </p>
        </div>

        <Toolbar className="lg:justify-end">
          <div className="inline-flex rounded-sm border border-gray-200 bg-gray-100 p-1">
            {[24, 48, 168, 720].map((h) => {
              const active = hours === h;
              return (
                <button
                  key={h}
                  onClick={() => onHoursChange(h)}
                  className={`min-h-8 rounded-xs px-3 text-xs font-black transition ${
                    active ? 'bg-white text-primary shadow-[0_1px_3px_rgba(15,23,42,0.08)]' : 'text-gray-500 hover:text-gray-800'
                  }`}
                >
                  {h === 720 ? '30天' : h === 168 ? '7天' : `${h}h`}
                </button>
              );
            })}
          </div>
          <Button
            onClick={onRefresh}
            disabled={loading}
            title="刷新"
            variant="secondary"
            className="h-9 w-9 px-0 py-0"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </Button>
        </Toolbar>
      </div>
    </header>
  );
}

export function FlowErrorPanel({
  message,
  loading,
  onRetry,
}: {
  message: string;
  loading: boolean;
  onRetry: () => void;
}) {
  return (
    <Panel className="p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-red-light text-red">
            <AlertTriangle size={18} />
          </div>
          <div className="min-w-0">
            <div className="text-base font-black text-gray-900">评分流程暂时不可用</div>
            <div className="mt-1 text-sm leading-6 text-gray-500">{message}</div>
            <div className="mt-2 text-xs font-bold text-gray-700">服务恢复后可直接重试，页面会重新读取当前窗口的评分样本。</div>
          </div>
        </div>
        <Button
          type="button"
          variant="primary"
          disabled={loading}
          onClick={onRetry}
          className="shrink-0"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          重新加载
        </Button>
      </div>
    </Panel>
  );
}

export function SummaryGrid({ data }: { data: ScoringFlowResponse }) {
  const cards: Array<{ label: string; value: number | string; icon: LucideIcon; colorClass: string; iconClass: string }> = [
    { label: '采集内容', value: data.diagnostics?.collected_window_total ?? data.total, icon: SlidersHorizontal, colorClass: 'text-gray-800', iconClass: 'text-gray-800' },
    { label: '待分析', value: data.diagnostics?.pending_analysis_total ?? 0, icon: AlertTriangle, colorClass: 'text-amber', iconClass: 'text-amber' },
    { label: '参与评分', value: data.scored, icon: GitBranch, colorClass: 'text-teal', iconClass: 'text-teal' },
    { label: '精选输出', value: data.stages.find((s) => s.key === 'selected')?.count || 0, icon: CheckCircle2, colorClass: 'text-primary', iconClass: 'text-primary' },
  ];

  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <Metric
            key={card.label}
            label={card.label}
            value={card.value}
            colorClass={card.colorClass}
            icon={<Icon size={15} className={card.iconClass} />}
          />
        );
      })}
    </div>
  );
}

export function DiagnosticsPanel({
  data,
  onHoursChange,
  onAnalyzePending,
  analyzing = false,
  analysisNotice,
}: {
  data: ScoringFlowResponse;
  onHoursChange?: (hours: number) => void;
  onAnalyzePending?: () => void;
  analyzing?: boolean;
  analysisNotice?: string | null;
}) {
  const diagnostics = data.diagnostics;
  const config = data.scoring_config;
  const reason = emptyReasonText(diagnostics?.empty_reason);
  const isEmpty = !data.samples.length;

  return (
    <Panel className="mb-4 overflow-hidden p-4 lg:p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-sm"
            style={{ background: isEmpty ? T.amberLight : T.tealLight, color: isEmpty ? T.amber : T.teal }}
          >
            {isEmpty ? <AlertTriangle size={17} /> : <CheckCircle2 size={17} />}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-black text-gray-900">{reason.title}</div>
            <div className="mt-1 max-w-3xl text-xs leading-6 text-gray-500">{reason.detail}</div>
            <div className="mt-1 text-xs font-bold text-gray-700">{reason.action}</div>
            {isEmpty && diagnostics?.empty_reason === 'no_content_in_window' && onHoursChange && (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onHoursChange(168)}
                  className="rounded-xs border border-primary/25 bg-primary-light px-3 py-1.5 text-xs font-black text-primary transition hover:border-primary"
                >
                  查看 7 天调试样本
                </button>
                <button
                  type="button"
                  onClick={() => onHoursChange(720)}
                  className="rounded-xs border border-gray-200 bg-white px-3 py-1.5 text-xs font-black text-gray-600 transition hover:border-gray-300 hover:text-gray-900"
                >
                  查看 30 天历史样本
                </button>
              </div>
            )}
            {isEmpty && diagnostics?.empty_reason === 'collected_not_analyzed' && onAnalyzePending && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="primary"
                  disabled={analyzing}
                  onClick={onAnalyzePending}
                  className="min-h-8 px-3 py-1.5 text-xs"
                >
                  <RefreshCw size={13} className={analyzing ? 'animate-spin' : ''} />
                  {analyzing ? '提交中' : '分析最近内容'}
                </Button>
                <span className="text-[11px] font-medium text-gray-500">提交后台分析后会自动刷新评分样本。</span>
              </div>
            )}
            {analysisNotice && (
              <div className="mt-3 rounded-sm border border-teal/20 bg-teal-light px-3 py-2 text-xs font-bold text-teal">
                {analysisNotice}
              </div>
            )}
          </div>
        </div>
        <Badge tone={isEmpty ? 'amber' : 'teal'} className="gap-1.5 rounded-xs font-mono">
          <TimerReset size={12} />
          {data.hours === 720 ? '30D' : data.hours === 168 ? '7D' : `${data.hours}H`}
        </Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {[
          ['采集内容', diagnostics?.collected_window_total ?? 0],
          ['窗口候选', diagnostics?.window_total ?? data.total],
          ['待分析', diagnostics?.pending_analysis_total ?? 0],
          ['已加载', diagnostics?.loaded_count ?? data.samples.length],
          ['评分输入', diagnostics?.scoring_input_count ?? data.scored],
          ['忽略排除', diagnostics?.ignored_count ?? 0],
        ].map(([label, value]) => (
          <div key={label as string} className="rounded-sm border border-gray-100 bg-gray-50 px-3 py-2.5">
            <div className="text-[10px] font-bold text-gray-400">{label}</div>
            <div className="mt-1 font-mono text-lg font-black leading-none text-gray-800">{value}</div>
          </div>
        ))}
      </div>

      {diagnostics?.window_options?.length ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {diagnostics.window_options.map((option) => {
            const active = option.hours === data.hours;
            return (
              <button
                key={option.hours}
                type="button"
                onClick={() => onHoursChange?.(option.hours)}
                className={`rounded-sm border px-3 py-2.5 text-left transition ${
                  active
                    ? 'border-primary-border bg-primary-light'
                    : 'border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-xs font-black ${active ? 'text-primary' : 'text-gray-700'}`}>
                    {windowLabel(option.hours)}
                  </span>
                  {option.hours === diagnostics.recommended_hours && (
                    <span className="rounded-xs bg-teal-light px-1.5 py-0.5 text-[10px] font-black text-teal">可用</span>
                  )}
                </div>
                <div className="mt-1 font-mono text-lg font-black leading-none text-gray-900">{option.count}</div>
                <div className="mt-1 text-[10px] text-gray-400">候选样本</div>
              </button>
            );
          })}
        </div>
      ) : null}

      {diagnostics?.collected_window_options?.length ? (
        <div className="mt-3 rounded-sm border border-gray-100 bg-gray-50 p-3">
          <div className="mb-2 text-[11px] font-black text-gray-500">采集内容窗口分布</div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {diagnostics.collected_window_options.map((option) => (
              <div key={option.hours} className="rounded-xs bg-white px-3 py-2">
                <div className="text-[10px] font-bold text-gray-400">{windowLabel(option.hours)}</div>
                <div className="mt-1 font-mono text-base font-black text-gray-800">{option.count}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {config && (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-500">
          <span className="rounded-xs bg-gray-100 px-2 py-1 font-mono">mode={config.curation_mode}</span>
          <span className="rounded-xs bg-gray-100 px-2 py-1 font-mono">threshold={fmt(config.curation_threshold)}</span>
          <span className="rounded-xs bg-gray-100 px-2 py-1 font-mono">p{config.curation_percentile ?? '-'}</span>
          <span className="rounded-xs bg-gray-100 px-2 py-1 font-mono">risk&lt;={fmt(config.risk_threshold)}</span>
          <span className="rounded-xs bg-gray-100 px-2 py-1 font-mono">quality floor={fmt(config.quality_gate_floor, 2)}</span>
        </div>
      )}
    </Panel>
  );
}

export function Funnel({ data, selectedKey }: { data: ScoringFlowResponse; selectedKey?: string }) {
  const max = Math.max(...data.stages.map((s) => s.count), 1);
  const barWidth = (count: number) => {
    if (count <= 0) return 0;
    return Math.max(3, Math.min(100, (count / max) * 100));
  };

  return (
    <Panel className="overflow-hidden p-4 lg:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Filter size={16} color={T.primary} />
          <div className="text-sm font-black text-gray-800">评分漏斗</div>
        </div>
        <div className="text-xs text-gray-400">横向长度按累计留存比例缩放</div>
      </div>

      <div className="flex flex-col gap-2.5">
        {data.stages.map((stage, index) => {
          const palette = STAGE_COLORS[stage.key] || STAGE_COLORS.candidates;
          const width = barWidth(stage.count);
          const active = selectedKey === stage.key;
          const previous = data.stages[index - 1];
          const lost = previous ? Math.max(0, previous.count - stage.count) : 0;
          const stageShare = stage.count / max;
          return (
            <div
              key={stage.key}
              className="grid min-w-0 grid-cols-1 gap-2 rounded-sm border p-3 transition md:grid-cols-[116px_minmax(0,1fr)_84px_76px] md:items-center"
              style={{
                borderColor: active ? palette.color : palette.border,
                background: active ? palette.soft : '#FFFFFF',
                boxShadow: active ? `0 0 0 2px ${palette.color}18, 0 10px 22px rgba(15,23,42,0.05)` : 'none',
              }}
            >
              <div className="min-w-0">
                <div className="truncate text-xs font-black" style={{ color: palette.color }}>{stage.label}</div>
                <div className="mt-1 font-mono text-[11px] text-gray-400">{stage.key.toUpperCase()}</div>
              </div>

              <div className="min-w-0">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium text-gray-500">累计留存</span>
                  <span className="font-mono text-[11px] font-black text-gray-600">{pct(stageShare)}</span>
                </div>
                <div className="relative h-5 overflow-hidden rounded-xs bg-gray-100">
                  <div
                    className="absolute inset-y-0 left-0 rounded-xs transition-all"
                    style={{ width: `${width}%`, background: `linear-gradient(90deg, ${palette.color}, ${palette.border})` }}
                  />
                  {stage.count === 0 && (
                    <div className="absolute inset-y-0 left-0 w-1 rounded-xs" style={{ background: palette.border }} />
                  )}
                </div>
              </div>

              <div className="flex items-baseline justify-between gap-2 md:block md:text-right">
                <span className="text-[11px] text-gray-400 md:block">样本</span>
                <span className="font-mono text-lg font-black leading-none text-gray-900 md:mt-1 md:block">{stage.count}</span>
              </div>

              <div className="flex items-baseline justify-between gap-2 md:block md:text-right">
                <span className="text-[11px] text-gray-400 md:block">{previous ? '流失' : '入口'}</span>
                <div
                  className="font-mono text-sm font-black leading-none md:mt-1"
                  style={{ color: previous && lost > 0 ? T.red : T.gray500 }}
                >
                  {previous ? (lost > 0 ? `-${lost}` : '0') : stage.count}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

export function MixList({ title, items, tone }: { title: string; items: Array<{ label: string; count: number }>; tone: keyof typeof MIX_TONES }) {
  const max = Math.max(...items.map((i) => i.count), 1);
  const palette = MIX_TONES[tone];
  return (
    <Panel className="p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-black text-gray-800">{title}</div>
        <Badge tone={tone} className="font-mono text-[10px]">
          {items.length}
        </Badge>
      </div>
      <div className="flex flex-col gap-2.5">
        {items.length === 0 ? (
          <div className="text-xs text-gray-400">暂无样本</div>
        ) : items.map((item) => (
          <div key={item.label} className="grid grid-cols-[78px_minmax(0,1fr)_34px] items-center gap-2">
            <div title={item.label} className="truncate text-xs text-gray-600">
              {item.label}
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div className="h-full rounded-full" style={{ width: `${Math.max(4, (item.count / max) * 100)}%`, background: palette.color }} />
            </div>
            <div className="text-right font-mono text-[11px] text-gray-500">{item.count}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function SampleList({
  samples,
  selectedId,
  onSelect,
}: {
  samples: ScoringFlowSample[];
  selectedId?: number;
  onSelect: (sample: ScoringFlowSample) => void;
}) {
  return (
    <Panel className="min-h-[520px] overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3.5">
        <div>
          <div className="text-sm font-black text-gray-800">候选样本池</div>
          <div className="mt-0.5 text-[11px] text-gray-400">点击样本查看评分路径</div>
        </div>
        <div className="font-mono text-[11px] text-gray-400">FINAL SCORE</div>
      </div>
      <div className="max-h-[628px] overflow-y-auto">
        {samples.length === 0 ? (
          <div className="flex min-h-[300px] items-center justify-center px-6 text-center text-sm text-gray-400">
            当前没有候选样本。上方诊断面板会说明数据断点。
          </div>
        ) : samples.map((sample) => {
          const active = sample.id === selectedId;
          return (
            <button
              key={sample.id}
              onClick={() => onSelect(sample)}
              className={`w-full border-0 border-b border-gray-100 px-4 py-3.5 text-left transition ${
                active ? 'bg-primary-light' : 'bg-white hover:bg-gray-50'
              }`}
            >
              <div className="flex items-start gap-3">
                <div
                  className="w-11 shrink-0 text-right font-mono text-lg font-black leading-tight"
                  style={{ color: sample.selected ? T.primary : active ? T.gray800 : T.gray500 }}
                >
                  {Math.round(sample.final_score)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="line-clamp-2 text-[13px] font-bold leading-5 text-gray-800">{sample.title}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge tone="neutral" className="rounded-xs px-1.5 py-0.5 text-[10px] font-bold">
                      {sample.category}
                    </Badge>
                    <span className="max-w-[150px] truncate text-[10px] text-gray-500">{sample.source_name || '未知来源'}</span>
                    {sample.selected && (
                      <Badge tone="primary" className="rounded-xs bg-white px-1.5 py-0.5 text-[10px]">
                        SELECTED
                      </Badge>
                    )}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

export function PathPanel({
  sample,
  onFeedback,
  onFavorite,
  onCreate,
  feedbacking,
  favoritePending = false,
  createPending = false,
}: {
  sample?: ScoringFlowSample;
  onFeedback: (sample: ScoringFlowSample, type: FeedbackType) => void;
  onFavorite: (sample: ScoringFlowSample) => void;
  onCreate: (sample: ScoringFlowSample) => void;
  feedbacking: boolean;
  favoritePending?: boolean;
  createPending?: boolean;
}) {
  const dims = sample?.dimension_scores || {};
  const dimRows = [
    ['信息密度', Number(dims.info_density || 0)],
    ['可操作性', Number(dims.actionability || 0)],
    ['创作者价值', Number(dims.creator_value || 0)],
    ['爆文潜力', Number(dims.viral_potential || 0)],
    ['来源权威', Number(dims.source_authority || 0)],
    ['新鲜度', Number(dims.freshness || 0)],
  ] as const;

  return (
    <Panel className="min-h-[520px] p-4 lg:p-5">
      {!sample ? (
        <div className="flex min-h-[460px] items-center justify-center rounded-sm border border-dashed border-gray-200 bg-gray-50 px-6 text-center text-sm text-gray-400">
          选择一个候选样本查看路径
        </div>
      ) : (
        <>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Badge tone={sample.selected ? 'primary' : 'neutral'} className="mb-2">
                {sample.selected ? '进入精选输出' : '未进入精选'}
              </Badge>
              <div className="text-lg font-black leading-snug text-gray-900">{sample.title}</div>
            </div>
            {sample.url && (
              <a
                href={sample.url}
                target="_blank"
                rel="noreferrer"
                title="打开原文"
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-gray-200 text-gray-400 transition hover:border-primary-border hover:text-primary"
              >
                <ExternalLink size={16} />
              </a>
            )}
          </div>

          <div className="mb-4 rounded-sm border border-primary-border bg-primary-light p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-xs font-black text-gray-800">创作上下文</div>
              {sample.tags?.length ? (
                <div className="flex max-w-[180px] flex-wrap justify-end gap-1">
                  {sample.tags.slice(0, 3).map((tag) => (
                    <Badge key={tag} tone="primary" className="rounded-xs bg-white px-1.5 py-0.5 text-[10px]">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </div>
            <div className="space-y-2 text-xs leading-6 text-gray-700">
              {sample.recommendation && (
                <p className="m-0">
                  <span className="font-black text-primary">推荐理由：</span>
                  {sample.recommendation}
                </p>
              )}
              {sample.summary && (
                <p className="m-0">
                  <span className="font-black text-gray-900">摘要：</span>
                  {sample.summary}
                </p>
              )}
              {sample.creator_angles?.length ? (
                <div>
                  <div className="mb-1 font-black text-gray-900">可写角度</div>
                  <div className="space-y-1">
                    {sample.creator_angles.slice(0, 2).map((angle) => (
                      <div key={angle} className="rounded-xs bg-white/80 px-2 py-1 text-[11px] font-bold text-gray-600">
                        {angle}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {!sample.recommendation && !sample.summary && !sample.creator_angles?.length && (
                <div className="text-gray-500">暂无摘要，建议先打开原文或补跑内容分析。</div>
              )}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button
                variant={sample.is_favorited ? 'success' : 'secondary'}
                disabled={favoritePending}
                onClick={() => onFavorite(sample)}
              >
                {sample.is_favorited ? <BookmarkCheck size={13} /> : <Bookmark size={13} />}
                {sample.is_favorited ? '已收藏' : '收藏'}
              </Button>
              <Button
                variant="primary"
                disabled={createPending}
                onClick={() => onCreate(sample)}
              >
                <PenLine size={13} />
                进入创作台
              </Button>
            </div>
          </div>

          <div className="mb-4 grid grid-cols-3 gap-2.5">
            {[
              ['基础分', sample.base_score, T.gray800],
              ['最终分', sample.final_score, T.primary],
              ['门槛', sample.threshold_used, T.amber],
            ].map(([label, value, color]) => (
              <div key={label as string} className="min-w-0 rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                <div className="mb-1 text-[10px] text-gray-400">{label}</div>
                <div className="font-mono text-xl font-black leading-none" style={{ color: color as string }}>{fmt(value as number)}</div>
              </div>
            ))}
          </div>

          <div className="mb-4 rounded-sm border border-gray-100 p-3">
            <div className="mb-2.5 flex items-center justify-between">
              <div className="text-xs font-black text-gray-800">人工反馈</div>
              <div className="font-mono text-xs" style={{ color: sample.feedback_score >= 0 ? T.teal : T.red }}>
                {sample.feedback_score > 0 ? '+' : ''}{fmt(sample.feedback_score)}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button
                variant="success"
                disabled={feedbacking}
                onClick={() => onFeedback(sample, 'great_pick')}
              >
                <Plus size={13} />
                正向加分
              </Button>
              <Button
                variant="danger"
                disabled={feedbacking}
                onClick={() => onFeedback(sample, 'not_relevant')}
              >
                <Minus size={13} />
                负向扣分
              </Button>
            </div>
          </div>

          <div className="mb-5 flex flex-col gap-3 rounded-sm border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs font-black text-gray-800">路径因子</div>
            <FactorBar label="质量因子" value={sample.quality_factor} color={T.teal} />
            <FactorBar label="风险因子" value={sample.risk_factor} color={T.amber} />
            <FactorBar label="时效衰减" value={sample.time_decay} color="#3B82F6" />
            <FactorBar label="多样性因子" value={sample.diversity_factor} color={T.purple} />
          </div>

          <div className="border-t border-gray-100 pt-4">
            <div className="mb-3 text-sm font-black text-gray-800">特征评分路径</div>
            <div className="flex flex-col gap-2.5">
              {dimRows.map(([label, value]) => (
                <ProgressRow key={label} label={label} value={value} color={T.primary} />
              ))}
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}
