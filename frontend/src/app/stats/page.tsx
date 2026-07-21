'use client';

import React, { useState } from 'react';
import {
  Activity,
  BarChart3,
  Database,
  Gauge,
  PieChart,
  RefreshCw,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Badge, Button, Panel, PanelTitle, Surface, cx } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import {
  statsApi,
  type StatsOverview,
  type StatsSourceItem,
  type StatsCategoryItem,
  type StatsTrendItem,
  type StatsNovelPlatform,
} from '@/lib/api';
import { timeAgoShort } from '@/lib/datetime';

// ── Color helpers ──────────────────────────────────────────────
const BAR_COLORS = ['#FF6B35', '#00C9A7', '#D97706', '#2563EB', '#E11D48', '#059669', '#D97706', '#64748B'];
const SOURCE_TYPE_COLOR: Record<string, string> = {
  rss: '#00C9A7',
  rsshub: '#059669',
  hackernews: '#8B5CF6',
  api: '#FF6B35',
  reddit: '#D97706',
  zhihu: '#2563EB',
  unknown: '#9CA3AF',
};

function barColor(idx: number) {
  return BAR_COLORS[idx % BAR_COLORS.length];
}

// ── Reusable chart components ──────────────────────────────────

function MiniBar({ value, max, color, height = 8 }: { value: number; max: number; color: string; height?: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="w-full overflow-hidden bg-gray-200" style={{ height, borderRadius: height / 2 }}>
      <div
        className="h-full transition-[width] duration-300"
        style={{
          width: `${pct}%`,
          background: color,
          borderRadius: height / 2,
        }}
      />
    </div>
  );
}

// 注：PanelTitle 与 Surface 已收敛到 @/components/ui 公共版，本地定义删除。
// 历史本地版 Surface 用 PanelTitle 内部组合 + px-5 py-4.5 padding，
// 公共版用 p-4.5 sm:p-5 + 自包含 header，视觉差异可接受。



function HorizontalBarChart({
  items,
  valueKey,
  labelKey,
  extraKey,
}: {
  items: Array<Record<string, unknown>>;
  valueKey: string;
  labelKey: string;
  extraKey?: string;
}) {
  if (!items || items.length === 0)
    return <div className="py-3 text-[13px] text-gray-400">暂无数据</div>;

  const maxVal = Math.max(...items.map(it => (it[valueKey] as number) || 0), 1);

  return (
    <div className="flex flex-col gap-2.5">
      {items.map((it, i) => {
        const val = (it[valueKey] as number) || 0;
        const label = (it[labelKey] as string) || '-';
        const extra = extraKey ? (it[extraKey] as string | number | null) : null;
        return (
          <div key={i} className="flex items-center gap-2.5">
            <div className="w-20 shrink-0 truncate text-right text-[13px] font-medium text-gray-700">
              {label}
            </div>
            <div className="min-w-0 flex-1">
              <MiniBar value={val} max={maxVal} color={barColor(i)} height={14} />
            </div>
            <div className="w-14 text-right font-mono text-xs text-gray-600">
              {val}
              {extra !== null && extra !== undefined && (
                <span className="ml-1 text-[10px] text-gray-400">{extra}</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SourcePieChart({ sources }: { sources: StatsSourceItem[] }) {
  if (sources.length === 0) {
    return <div className="text-[13px] text-gray-400">暂无数据</div>;
  }

  const total = sources.reduce((sum, item) => sum + item.content_count, 0) || 1;

  return (
    <div>
      <div className="mb-3.5 flex h-[18px] overflow-hidden rounded">
        {sources.map((source, index) => {
          const pct = (source.content_count / total) * 100;
          if (pct < 0.5) return null;
          return (
            <div
              key={`${source.source_name}-${index}`}
              className="transition-[width] duration-300"
              style={{
                width: `${pct}%`,
                background: barColor(index),
              }}
              title={`${source.source_name}: ${source.content_count} (${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>

      <div className="flex flex-wrap gap-2">
        {sources.slice(0, 10).map((source, index) => (
          <div key={`${source.source_name}-${index}`} className="flex items-center gap-1 text-xs">
            <div
              className="h-2 w-2 shrink-0 rounded-full"
              style={{
                background: barColor(index),
              }}
            />
            <span className="max-w-[120px] truncate text-gray-600">{source.source_name}</span>
            <span className="font-mono text-[11px] text-gray-400">{source.content_count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatDayKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** avg_score → 顺序色阶（浅黄→中绿→深绿），高分=深绿 */
function scoreColor(score: number): string {
  if (!score || score <= 0) return '#E5E7EB'; // 灰=无数据
  if (score >= 85) return '#065F46'; // 深绿
  if (score >= 78) return '#059669'; // 中绿
  if (score >= 70) return '#65A30D'; // 黄绿
  if (score >= 60) return '#D97706'; // 琥珀
  return '#F59E0B'; // 浅黄
}

const TOP_N_CATEGORY = 10;
// 蓝海定义：低量（≤100条）且高分（≥75）且非噪音（≥5条，过滤 1-2 条的分类标签错误）
const BLUE_OCEAN_MAX_COUNT = 100;
const BLUE_OCEAN_MIN_SCORE = 75;
const BLUE_OCEAN_MIN_COUNT = 5;

function CategoryDistribution({ categories }: { categories: StatsCategoryItem[] }) {
  const [showAll, setShowAll] = useState(false);
  if (!categories || categories.length === 0) {
    return <div className="py-3 text-[13px] text-gray-400">暂无数据</div>;
  }

  const total = categories.reduce((s, c) => s + c.content_count, 0) || 1;
  const sorted = [...categories].sort((a, b) => b.content_count - a.content_count);
  const top = sorted.slice(0, TOP_N_CATEGORY);
  const tail = sorted.slice(TOP_N_CATEGORY);
  const visible = showAll ? sorted : top;
  const tailCount = tail.length;
  const tailTotal = tail.reduce((s, c) => s + c.content_count, 0);
  const tailPct = ((tailTotal / total) * 100).toFixed(1);

  // 迷你条用 √count 归一（视觉辅助，真实值在右侧数字里）——避免 AI 极端离群值压扁其他条
  const sqrtMax = Math.sqrt(sorted[0]?.content_count || 1);

  // 蓝海：低量高分，主动捞出升到独立区
  const blueOcean = sorted
    .filter(c => c.content_count >= BLUE_OCEAN_MIN_COUNT
              && c.content_count <= BLUE_OCEAN_MAX_COUNT
              && c.avg_score >= BLUE_OCEAN_MIN_SCORE)
    .sort((a, b) => b.avg_score - a.avg_score)
    .slice(0, 4);

  return (
    <div>
      {/* ① 概览条（Top5 彩色 + 灰色其他）——回答「内容集中在哪」 */}
      <div className="mb-3 flex h-[14px] overflow-hidden rounded">
        {top.slice(0, 5).map((c) => {
          const pct = (c.content_count / total) * 100;
          if (pct < 0.5) return null;
          return (
            <div
              key={c.category}
              className="transition-[width] duration-300"
              style={{ width: `${pct}%`, background: scoreColor(c.avg_score) }}
              title={`${c.category}: ${c.content_count} (${pct.toFixed(1)}%) · 均分${c.avg_score || '-'}`}
            />
          );
        })}
        {tail.length > 0 && (
          <div
            className="transition-[width] duration-300 bg-gray-200"
            style={{ width: `${(tailTotal / total) * 100}%` }}
            title={`其他 ${tailCount} 个分类: ${tailTotal} (${tailPct}%)`}
          />
        )}
      </div>

      {/* ② 主流赛道 Top10 表——回答「谁大、谁卷」 */}
      <div className="flex flex-col gap-1.5">
        {visible.map((c) => (
          <div key={c.category} className="flex items-center gap-2">
            <div className="w-16 shrink-0 truncate text-right text-[12px] font-medium text-gray-700" title={c.category}>
              {c.category}
            </div>
            <div className="min-w-0 flex-1">
              <MiniBar value={Math.sqrt(c.content_count)} max={sqrtMax} color={scoreColor(c.avg_score)} height={13} />
            </div>
            <div className="w-20 shrink-0 text-right font-mono text-[11px] text-gray-600">
              {c.content_count.toLocaleString()}
              {c.avg_score > 0 && (
                <span className="ml-1" style={{ color: scoreColor(c.avg_score) }}>·{c.avg_score}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* ③ 蓝海机会——回答「有没有小而美方向」 */}
      <div className="mt-3">
        <div className="mb-1.5 text-[11px] font-medium text-teal">🌊 蓝海机会 · 低量高分</div>
        {blueOcean.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {blueOcean.map((c) => (
              <span
                key={c.category}
                className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px]"
                style={{ border: '1px solid rgba(5,150,105,0.35)', background: 'rgba(5,150,105,0.06)' }}
                title={`${c.category}: ${c.content_count}条 · 均分${c.avg_score}`}
              >
                <span className="font-medium text-gray-800">{c.category}</span>
                <span className="text-gray-400">{c.content_count}条</span>
                <span className="font-mono font-semibold" style={{ color: scoreColor(c.avg_score) }}>{c.avg_score}</span>
              </span>
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-gray-400">暂无明显蓝海分类</div>
        )}
      </div>

      {/* ④ 长尾折叠——给刨根究底的人保留入口，不污染主视图 */}
      {tailCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(v => !v)}
          className="mt-3 w-full rounded border border-gray-200 bg-gray-50 py-1.5 text-[11px] font-medium text-gray-500 transition hover:border-primary-border hover:text-primary"
        >
          {showAll ? '收起' : `展开全部 ${categories.length} 个（尾部 ${tailCount} 类占 ${tailPct}%）`}
        </button>
      )}
    </div>
  );
}

function formatShortDate(dateKey: string) {
  const date = new Date(`${dateKey}T00:00:00`);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function formatRatePercent(part: number, total: number) {
  if (part <= 0 || total <= 0) return 0;
  const value = (part / total) * 100;
  return value < 0.1 ? 0.1 : Number(value.toFixed(1));
}

function getHeatColor(value: number, max: number) {
  if (value <= 0) return '#F3F4F6';
  const ratio = value / Math.max(max, 1);
  if (ratio >= 0.82) return '#00C9A7';
  if (ratio >= 0.56) return '#FF6B35';
  if (ratio >= 0.28) return '#FFD0B5';
  return '#FFF4EE';
}

function ContributionHeatmap({ data, days }: { data: StatsTrendItem[]; days: number }) {
  const byDate = new Map(data.map(day => [day.date, day]));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const sortedDates = data
    .map(day => new Date(`${day.date}T00:00:00`))
    .filter(date => !Number.isNaN(date.getTime()))
    .sort((a, b) => a.getTime() - b.getTime());
  const start = sortedDates[0] ? new Date(sortedDates[0]) : new Date(today);
  if (!sortedDates[0]) {
    start.setDate(today.getDate() - Math.max(days - 1, 0));
  }
  const end = sortedDates[sortedDates.length - 1] ? new Date(sortedDates[sortedDates.length - 1]) : new Date(today);
  if (end.getTime() < today.getTime()) {
    end.setTime(today.getTime());
  }

  const cells: Array<{ date: string; item: StatsTrendItem | null; empty?: boolean }> = [];
  const startWeekday = start.getDay();
  for (let i = 0; i < startWeekday; i += 1) {
    cells.push({ date: `empty-${i}`, item: null, empty: true });
  }
  const spanDays = Math.max(1, Math.floor((end.getTime() - start.getTime()) / 86400000) + 1);
  for (let i = 0; i < spanDays; i += 1) {
    const date = new Date(start);
    date.setDate(start.getDate() + i);
    const dateKey = formatDayKey(date);
    cells.push({ date: dateKey, item: byDate.get(dateKey) ?? null });
  }

  const total = data.reduce((sum, day) => sum + day.content_count, 0);
  const curated = data.reduce((sum, day) => sum + day.curated_count, 0);
  const maxCount = Math.max(...data.map(day => day.content_count), 1);
  const peak = data.reduce<StatsTrendItem | null>(
    (current, day) => (!current || day.content_count > current.content_count ? day : current),
    null,
  );

  return (
    <div>
      <div className="mb-3.5 grid grid-cols-[repeat(auto-fit,minmax(118px,1fr))] gap-2.5">
        {[
          { label: '入库总量', value: total, color: 'text-primary' },
          { label: '精选内容', value: curated, color: 'text-teal' },
          { label: '峰值日期', value: peak ? peak.content_count : 0, color: 'text-gray-700', sub: peak ? formatShortDate(peak.date) : '-' },
        ].map(item => (
          <div key={item.label} className="min-w-0 rounded-sm border border-gray-200 bg-gray-50 px-3 py-2.5">
            <div className="mb-1 text-[11px] font-black text-gray-500">{item.label}</div>
            <div className="flex min-w-0 items-baseline gap-1.5">
              <span className={cx('font-mono text-[22px] font-black leading-none', item.color)}>
                {item.value}
              </span>
              <span className="text-[11px] text-gray-400">{item.sub ?? '条'}</span>
            </div>
          </div>
        ))}
      </div>

      {cells.length > 0 ? (
        <div className="overflow-x-auto pb-0.5">
          <div
            className="grid w-max min-w-full gap-1"
            style={{
              gridTemplateRows: 'repeat(7, 14px)',
              gridAutoFlow: 'column',
              gridAutoColumns: 14,
            }}
          >
            {cells.map(cell => {
              const count = cell.item?.content_count ?? 0;
              const curatedCount = cell.item?.curated_count ?? 0;
              const analyzedCount = cell.item?.analyzed_count ?? 0;
              return (
                <div
                  key={cell.date}
                  title={
                    cell.empty
                      ? ''
                      : `${cell.date}: 入库 ${count} 条，精选 ${curatedCount} 条，已分析 ${analyzedCount} 条`
                  }
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 3,
                    background: cell.empty ? 'transparent' : getHeatColor(count, maxCount),
                    border: cell.empty ? '1px solid transparent' : `1px solid ${count > 0 ? 'rgba(255,107,53,0.16)' : '#E5E7EB'}`,
                  }}
                />
              );
            })}
          </div>
        </div>
      ) : (
        <div className="py-3 text-[13px] text-gray-400">暂无趋势数据</div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-3.5 text-[11px] text-gray-500">
          <span>起始 {formatShortDate(formatDayKey(start))}</span>
          <span>结束 {formatShortDate(formatDayKey(today))}</span>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
          <span>少</span>
          {[0, 1, 3, 6, 9].map(level => (
            <span
              key={level}
              style={{
                width: 12,
                height: 12,
                borderRadius: 3,
                border: `1px solid ${level === 0 ? '#E5E7EB' : 'rgba(255,107,53,0.16)'}`,
                background: getHeatColor(level, 9),
              }}
            />
          ))}
          <span>多</span>
        </div>
      </div>
    </div>
  );
}

function formatSyncLabel(lastSync: string | null) {
  if (!lastSync) return '未同步';
  return timeAgoShort(lastSync);
}

function NovelPlatformStats({ platforms }: { platforms: StatsNovelPlatform[] }) {
  if (platforms.length === 0) {
    return <div className="text-[13px] text-gray-400">暂无数据</div>;
  }

  // 统一到主色系 *-light / *-border / *-text 三层，与全局设计 token 对齐，
  // 不再引入主色板之外的独立蓝色。
  const platformColors = [
    { bg: 'bg-primary-light', color: 'text-primary', border: 'border-primary-border' },
    { bg: 'bg-teal-light', color: 'text-teal', border: 'border-teal-border' },
    { bg: 'bg-purple-light', color: 'text-purple', border: 'border-purple-border' },
    { bg: 'bg-amber-light', color: 'text-amber', border: 'border-amber-border' },
  ];

  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
      {platforms.map((platform, i) => {
        const pc = platformColors[i % platformColors.length];
        return (
          <div
            key={platform.table}
            className={cx('flex min-w-0 flex-col rounded-sm border px-4 py-3.5', pc.bg, pc.border)}
          >
            <div className={cx('mb-2 text-[13px] font-black', pc.color)}>
              {platform.name}
            </div>
            <div className={cx('font-mono text-3xl font-black leading-none', pc.color)}>
              {platform.count}
              <span className="ml-1 text-xs font-medium text-gray-400">条</span>
            </div>
            <div className="mt-2.5 flex min-w-0 items-center gap-1.5 text-[11px] text-gray-500">
              <span
                className={cx('inline-block h-1.5 w-1.5 shrink-0 rounded-full', platform.last_sync ? 'bg-teal' : 'bg-gray-300')}
              />
              <span className="truncate">
                最近同步: {formatSyncLabel(platform.last_sync)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  unit,
  color,
  sub,
  tone = 'neutral',
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  unit: string;
  color: string;
  sub: string;
  tone?: 'primary' | 'teal' | 'amber' | 'neutral';
}) {
  const toneClass = {
    primary: 'border-primary-border bg-primary-light',
    teal: 'border-teal-border bg-teal-light',
    amber: 'border-amber-border bg-amber-light',
    neutral: 'border-gray-200 bg-white',
  }[tone];

  return (
    <div className={cx('min-w-0 rounded-lg border px-4.5 py-4', toneClass)}>
      <div className="mb-2.5 flex items-center gap-2">
        <Icon size={15} strokeWidth={2.2} style={{ color }} />
        <span className="text-xs font-black text-gray-500">{label}</span>
      </div>
      <div className="font-mono text-[28px] font-black leading-tight" style={{ color }}>
        {value}
        <span className="ml-1 text-[13px] font-medium text-gray-500">{unit}</span>
      </div>
      <div className="mt-1.5 text-[11px] text-gray-500">{sub}</div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────

export default function StatsPage() {
  const days = 30;

  const { data: dashboard, loading, error, refetch } = useFetch(
    () => statsApi.getDashboard(days),
    [days],
  );

  const overview = dashboard?.overview ?? null;
  const sources = dashboard?.sources ?? [];
  const categories = dashboard?.categories ?? [];
  const trend = dashboard?.trend ?? [];
  const novelPlatforms = dashboard?.platforms ?? [];

  const curatedRate = overview ? formatRatePercent(overview.curated, overview.total) : 0;

  return (
    <div className="flex-1 overflow-y-auto bg-page">
      <div className="mx-auto max-w-[1480px] px-10 pb-16 pt-7">
        <Panel className="relative mb-4.5 overflow-hidden px-6 py-5.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] before:absolute before:left-0 before:right-0 before:top-0 before:h-1 before:bg-gradient-to-r before:from-primary before:to-teal">
          <div className="relative grid grid-cols-[minmax(0,1fr)_auto] items-start gap-5 max-md:grid-cols-1">
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-2.5">
                <Badge tone="primary" className="gap-1.5 font-mono">
                  <BarChart3 size={13} strokeWidth={2.4} />
                  DATA DESK
                </Badge>
                <span className="text-xs font-bold text-gray-500">最近 {days} 天</span>
              </div>
              <h1 className="display-title m-0 text-[28px] leading-[1.12] text-gray-900">
                数据统计工作台
              </h1>
              <p className="mt-2 max-w-[760px] text-[13px] leading-7 text-gray-500">
                观察内容入库、精选效率、信源结构和分类覆盖，判断当前选题池是否健康、是否需要调整信源和筛选策略。
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <span className="rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-bold text-gray-500">
                近 30 天
              </span>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void refetch()}
                title="刷新"
                className="h-9 w-9 px-0"
              >
                <RefreshCw size={15} />
              </Button>
            </div>
          </div>
        </Panel>

        {loading && (
          <div className="space-y-3.5">
            {/* KPI 骨架 */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,170px),1fr))] gap-3">
              {[1, 2, 3, 4].map(i => (
                <Panel key={i} className="px-5 py-4">
                  <div className="mb-2 h-3 w-16 animate-pulse rounded bg-gray-200" />
                  <div className="h-7 w-24 animate-pulse rounded bg-gray-200" />
                </Panel>
              ))}
            </div>
            {/* 图表骨架 */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,360px),1fr))] gap-3.5">
              {[1, 2].map(i => (
                <Panel key={i} className="px-5 py-4.5">
                  <div className="mb-4 h-4 w-20 animate-pulse rounded bg-gray-200" />
                  <div className="space-y-2.5">
                    {[1, 2, 3, 4, 5].map(j => (
                      <div key={j} className="flex items-center gap-2.5">
                        <div className="h-3 w-16 animate-pulse rounded bg-gray-100" />
                        <div className="h-3 flex-1 animate-pulse rounded bg-gray-100" />
                        <div className="h-3 w-10 animate-pulse rounded bg-gray-100" />
                      </div>
                    ))}
                  </div>
                </Panel>
              ))}
            </div>
          </div>
        )}

        {error && !loading && (
          <div className="mb-5">
            <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
          </div>
        )}

        {!loading && (
          <>
            {/* ═══════════════════════════════════════════════════
                A. 入库趋势 + 网文雷达
                ═══════════════════════════════════════════════════ */}
            <div
              className="mb-3.5 grid grid-cols-[repeat(auto-fit,minmax(min(100%,360px),1fr))] items-start gap-3.5"
            >
              <Surface title="每日入库趋势" hint={`最近 ${days} 天`}>
                <ContributionHeatmap data={trend} days={days} />
              </Surface>

              <Surface title="网文雷达统计">
                <NovelPlatformStats platforms={novelPlatforms} />
              </Surface>
            </div>

            {/* ═══════════════════════════════════════════════════
                B. 内容总览 KPI Cards
                ═══════════════════════════════════════════════════ */}
            <div className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
              {[
                {
                  icon: Database,
                  label: '总内容数',
                  value: overview?.total ?? 0,
                  unit: '条',
                  color: '#374151',
                  sub: `已分析 ${overview?.analyzed ?? 0}`,
                  tone: 'neutral' as const,
                },
                {
                  icon: Gauge,
                  label: '精选内容',
                  value: overview?.curated ?? 0,
                  unit: '条',
                  color: 'var(--color-primary-text)',
                  sub: `精选率 ${curatedRate}%`,
                  tone: 'primary' as const,
                },
                {
                  icon: Activity,
                  label: '今日新增',
                  value: overview?.today_new ?? 0,
                  unit: '条',
                  color: 'var(--color-teal-text)',
                  sub: '今日 0:00 起',
                  tone: 'teal' as const,
                },
                {
                  icon: PieChart,
                  label: '精选率',
                  value: curatedRate,
                  unit: '%',
                  color: '#374151',
                  sub: `${overview?.curated ?? 0} / ${overview?.total ?? 0}`,
                  tone: 'neutral' as const,
                },
              ].map(card => <KpiCard key={card.label} {...card} />)}
            </div>

            {/* ═══════════════════════════════════════════════════
                C. 信源分布 + D. 分类分布 (side by side)
                ═══════════════════════════════════════════════════ */}
            <div className="mb-3.5 grid grid-cols-[repeat(auto-fit,minmax(360px,1fr))] items-start gap-3.5">
              {/* B. 信源分布 */}
              <Surface title="信源分布" hint={`${sources.length} 个信源`}>
                <SourcePieChart sources={sources} />

                {/* Source table */}
                {sources.length > 0 && (
                  <div className="mt-4">
                    <table className="w-full border-collapse text-xs">
                      <thead>
                        <tr className="border-b border-gray-200">
                          {['信源', '类型', '数量', '精选', '精选率'].map(h => (
                            <th
                              key={h}
                              className="px-1.5 py-1 text-left text-[11px] font-normal text-gray-400"
                            >
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sources.slice(0, 8).map((src, i) => {
                          const color = SOURCE_TYPE_COLOR[src.source_type.toLowerCase()] || '#9CA3AF';
                          return (
                            <tr key={i} className="border-b border-gray-100">
                              <td className="max-w-[100px] truncate p-1.5 font-medium text-gray-800">
                                {src.source_name}
                              </td>
                              <td className="p-1.5">
                                <span
                                  className="inline-block rounded-full px-1.5 py-px text-[10px]"
                                  style={{
                                    background: color + '20',
                                    color: color,
                                  }}
                                >
                                  {src.source_type.toUpperCase()}
                                </span>
                              </td>
                              <td className="p-1.5 font-mono text-gray-600">
                                {src.content_count}
                              </td>
                              <td className="p-1.5 font-mono text-primary">
                                {src.curated_count}
                              </td>
                              <td className="p-1.5 font-mono text-[11px] text-teal">
                                {src.curation_rate}%
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Surface>

              {/* C. 分类分布 */}
              <Surface title="分类分布" hint={`${categories.length} 个分类 · Top10 + 蓝海`}>
                <CategoryDistribution categories={categories} />
              </Surface>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
