/**
 * 微信读书统计图表组件。
 *
 * 从 _shared.tsx 拆出：StatusDonut, TopNBars, ProgressHistogram,
 * CompletionFunnel, NoteDensityScatter, WeeklyPulse
 */

'use client';

import React, { useMemo } from 'react';
import { cx } from '@/components/ui';
import type { ContentItem } from '@/types';
import { type WeReadMeta, getReadingStatus } from './_weread-utils';

export const CHART_COLORS = ['#FF6B35', '#00C9A7', '#D97706', '#2563EB', '#8B5CF6', '#E11D48', '#059669', '#06B6D4', '#64748B', '#EC4899'];

/** 环形图：阅读状态分布 */
export function StatusDonut({ items }: { items: Array<{ meta: WeReadMeta }> }) {
  const counts = useMemo(() => {
    let read = 0, reading = 0, unread = 0;
    for (const { meta } of items) {
      const s = getReadingStatus(meta.readingProgress);
      if (s === '已读') read++;
      else if (s === '在读') reading++;
      else unread++;
    }
    return { read, reading, unread, total: items.length };
  }, [items]);

  if (counts.total === 0) return <div className="py-3 text-[13px] text-gray-400">暂无数据</div>;

  const segments = [
    { label: '已读', value: counts.read, color: '#00C9A7' },
    { label: '在读', value: counts.reading, color: '#FF6B35' },
    { label: '未读', value: counts.unread, color: '#D1D5DB' },
  ];
  const total = counts.total;
  // CSS conic-gradient 环形图
  let accumulated = 0;
  const gradientStops = segments.map((s) => {
    const start = (accumulated / total) * 360;
    accumulated += s.value;
    const end = (accumulated / total) * 360;
    return `${s.color} ${start}deg ${end}deg`;
  }).join(', ');

  return (
    <div className="flex items-center gap-4">
      <div
        className="relative h-[120px] w-[120px] shrink-0 rounded-full"
        style={{ background: `conic-gradient(${gradientStops})` }}
      >
        <div className="absolute inset-[18px] grid place-items-center rounded-full bg-white">
          <div className="text-center">
            <div className="font-mono text-2xl font-black text-gray-900">{total}</div>
            <div className="text-[10px] text-gray-400">总书籍</div>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        {segments.map((s) => (
          <div key={s.label} className="flex items-center gap-2">
            <div className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
            <span className="text-xs font-bold text-gray-600">{s.label}</span>
            <span className="font-mono text-xs text-gray-900">{s.value}</span>
            <span className="font-mono text-[10px] text-gray-400">
              {total > 0 ? Math.round((s.value / total) * 100) : 0}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 水平条形图：Top N */
export function TopNBars({ data, unit }: {
  data: Array<{ label: string; value: number; sub?: string }>;
  unit: string;
}) {
  if (data.length === 0) return <div className="py-3 text-[13px] text-gray-400">暂无数据</div>;
  const maxVal = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="flex flex-col gap-2">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-[100px] shrink-0 truncate text-right text-[12px] font-medium text-gray-700" title={d.label}>
            {d.label}
          </div>
          <div className="min-w-0 flex-1">
            <div className="h-3.5 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{
                  width: `${(d.value / maxVal) * 100}%`,
                  background: CHART_COLORS[i % CHART_COLORS.length],
                }}
              />
            </div>
          </div>
          <div className="w-16 shrink-0 text-right font-mono text-[11px] text-gray-600">
            {d.value}{unit}
            {d.sub && <span className="ml-0.5 text-[9px] text-gray-400">{d.sub}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

/** 进度分布直方图 */
export function ProgressHistogram({ items }: { items: Array<{ meta: WeReadMeta }> }) {
  const bins = useMemo(() => {
    const buckets = [
      { label: '0%', range: '未开始', count: 0, color: '#E5E7EB' },
      { label: '1-25%', range: '刚开始', count: 0, color: '#FFD0B5' },
      { label: '26-50%', range: '阅读中', count: 0, color: '#FF6B35' },
      { label: '51-75%', range: '过半', count: 0, color: '#D97706' },
      { label: '76-99%', range: '快读完', count: 0, color: '#00C9A7' },
      { label: '100%', range: '已完成', count: 0, color: '#059669' },
    ];
    for (const { meta } of items) {
      const p = meta.readingProgress;
      if (p === 0) buckets[0].count++;
      else if (p <= 25) buckets[1].count++;
      else if (p <= 50) buckets[2].count++;
      else if (p <= 75) buckets[3].count++;
      else if (p < 100) buckets[4].count++;
      else buckets[5].count++;
    }
    return buckets;
  }, [items]);

  const maxCount = Math.max(...bins.map((b) => b.count), 1);

  return (
    <div className="flex items-end justify-between gap-1.5" style={{ height: 120 }}>
      {bins.map((b, i) => (
        <div key={i} className="flex flex-1 flex-col items-center gap-1.5">
          <div className="font-mono text-[10px] font-bold text-gray-500">{b.count}</div>
          <div className="flex w-full flex-1 items-end">
            <div
              className="w-full rounded-t-sm transition-[height] duration-500"
              style={{
                height: `${(b.count / maxCount) * 100}%`,
                background: b.color,
                minHeight: b.count > 0 ? '4px' : '0',
              }}
            />
          </div>
          <div className="text-center">
            <div className="text-[10px] font-bold text-gray-600">{b.label}</div>
            <div className="text-[9px] text-gray-400">{b.range}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** 完成率漏斗图：开始→25%→50%→75%→100% */
export function CompletionFunnel({ items }: { items: Array<{ meta: WeReadMeta }> }) {
  const stages = useMemo(() => {
    let started = 0, reached25 = 0, reached50 = 0, reached75 = 0, finished = 0;
    for (const { meta } of items) {
      const p = meta.readingProgress;
      if (p > 0) started++;
      if (p >= 25) reached25++;
      if (p >= 50) reached50++;
      if (p >= 75) reached75++;
      if (p >= 100) finished++;
    }
    return { started, reached25, reached50, reached75, finished };
  }, [items]);

  const funnelStages = [
    { label: '开始阅读', count: stages.started, color: '#FF6B35' },
    { label: '读到 25%', count: stages.reached25, color: '#D97706' },
    { label: '读到 50%', count: stages.reached50, color: '#F59E0B' },
    { label: '读到 75%', count: stages.reached75, color: '#00C9A7' },
    { label: '读完', count: stages.finished, color: '#059669' },
  ];

  const maxCount = Math.max(...funnelStages.map(s => s.count), 1);

  return (
    <div className="flex flex-col gap-2">
      {funnelStages.map((stage, i) => {
        const prevCount = i > 0 ? funnelStages[i - 1].count : 0;
        const rate = prevCount > 0 ? Math.round((stage.count / prevCount) * 100) : 100;
        const widthPct = (stage.count / maxCount) * 100;
        return (
          <div key={i} className="flex items-center gap-2">
            <div className="w-16 shrink-0 text-right text-[11px] font-bold text-gray-600">
              {stage.label}
            </div>
            <div className="min-w-0 flex-1">
              <div className="h-7 overflow-hidden rounded-md bg-gray-50">
                <div
                  className="flex h-full items-center justify-end rounded-md px-2 transition-[width] duration-500"
                  style={{
                    width: `${Math.max(widthPct, 8)}%`,
                    background: stage.color + '20',
                    borderRight: `3px solid ${stage.color}`,
                  }}
                >
                  <span className="font-mono text-[11px] font-bold" style={{ color: stage.color }}>
                    {stage.count}
                  </span>
                </div>
              </div>
            </div>
            <div className="w-12 shrink-0 text-right font-mono text-[10px] text-gray-400">
              {i > 0 && stage.count > 0 ? `${rate}%` : ''}
            </div>
          </div>
        );
      })}
      <p className="mt-1 text-[10px] text-gray-400">百分比 = 相比上一阶段的留存率</p>
    </div>
  );
}

/** 笔记密度散点图：X=进度, Y=划线数, 气泡=总笔记数 */
export function NoteDensityScatter({ items }: { items: Array<{ item: ContentItem; meta: WeReadMeta }> }) {
  const points = useMemo(() => {
    return items
      .filter(({ meta }) => meta.noteCount > 0 || meta.reviewCount > 0)
      .map(({ item, meta }) => ({
        title: item.title,
        progress: meta.readingProgress,
        noteCount: meta.noteCount,
        totalNotes: meta.noteCount + meta.reviewCount,
        status: getReadingStatus(meta.readingProgress),
      }));
  }, [items]);

  if (points.length === 0) return <div className="py-3 text-[13px] text-gray-400">暂无笔记数据</div>;

  const maxNotes = Math.max(...points.map(p => p.noteCount), 1);
  const W = 320;
  const H = 180;
  const padding = { left: 32, right: 16, top: 16, bottom: 28 };
  const plotW = W - padding.left - padding.right;
  const plotH = H - padding.top - padding.bottom;

  const xScale = (progress: number) => padding.left + (progress / 100) * plotW;
  const yScale = (notes: number) => padding.top + plotH - (notes / maxNotes) * plotH;
  const rScale = (total: number) => 3 + Math.sqrt(total) * 1.5;

  const statusColor = (status: string) =>
    status === '已读' ? '#059669' : status === '在读' ? '#FF6B35' : '#D1D5DB';

  const yTicks = [0, Math.ceil(maxNotes / 2), maxNotes];
  const xTicks = [0, 25, 50, 75, 100];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 220 }}>
        {/* Grid lines */}
        {yTicks.map((tick, i) => (
          <g key={`y-${i}`}>
            <line
              x1={padding.left}
              y1={yScale(tick)}
              x2={W - padding.right}
              y2={yScale(tick)}
              stroke="#F3F4F6"
              strokeWidth={1}
            />
            <text x={padding.left - 6} y={yScale(tick) + 3} textAnchor="end" fontSize={9} fill="#9CA3AF">
              {tick}
            </text>
          </g>
        ))}
        {/* X axis ticks */}
        {xTicks.map((tick, i) => (
          <text key={`x-${i}`} x={xScale(tick)} y={H - 10} textAnchor="middle" fontSize={9} fill="#9CA3AF">
            {tick}%
          </text>
        ))}
        {/* Axis labels */}
        <text x={W / 2} y={H - 1} textAnchor="middle" fontSize={8} fill="#6B7280">
          阅读进度
        </text>
        <text
          x={10}
          y={H / 2}
          textAnchor="middle"
          fontSize={8}
          fill="#6B7280"
          transform={`rotate(-90 10 ${H / 2})`}
        >
          划线数
        </text>
        {/* Data points */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={xScale(p.progress)}
            cy={yScale(p.noteCount)}
            r={rScale(p.totalNotes)}
            fill={statusColor(p.status) + '50'}
            stroke={statusColor(p.status)}
            strokeWidth={1}
          >
            <title>{`${p.title}: 进度${p.progress}% · ${p.noteCount}划线 · ${p.totalNotes}总笔记`}</title>
          </circle>
        ))}
      </svg>
      {/* Legend */}
      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[10px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full" style={{ background: '#059669' }} />
          已读
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full" style={{ background: '#FF6B35' }} />
          在读
        </span>
        <span className="text-gray-400">气泡大小 = 总笔记数</span>
      </div>
    </div>
  );
}

/** 本周阅读脉搏 */
export function WeeklyPulse({ items }: { items: Array<{ item: ContentItem; meta: WeReadMeta }> }) {
  const pulse = useMemo(() => {
    const now = new Date();
    const dayOfWeek = now.getDay() || 7;
    const thisWeekStart = new Date(now);
    thisWeekStart.setDate(now.getDate() - dayOfWeek + 1);
    thisWeekStart.setHours(0, 0, 0, 0);
    const lastWeekStart = new Date(thisWeekStart);
    lastWeekStart.setDate(thisWeekStart.getDate() - 7);

    let thisWeekNotes = 0;
    const thisWeekBooks = new Set<number>();
    let lastWeekNotes = 0;
    const lastWeekBooks = new Set<number>();

    for (const { item, meta } of items) {
      if (!item.published_at) continue;
      const date = new Date(item.published_at);
      if (Number.isNaN(date.getTime())) continue;
      const notes = meta.noteCount + meta.reviewCount;
      if (date >= thisWeekStart) {
        thisWeekNotes += notes;
        thisWeekBooks.add(item.id);
      } else if (date >= lastWeekStart) {
        lastWeekNotes += notes;
        lastWeekBooks.add(item.id);
      }
    }

    const notesTrend = lastWeekNotes > 0
      ? Math.round(((thisWeekNotes - lastWeekNotes) / lastWeekNotes) * 100)
      : thisWeekNotes > 0 ? 100 : 0;
    const booksTrend = lastWeekBooks.size > 0
      ? Math.round(((thisWeekBooks.size - lastWeekBooks.size) / lastWeekBooks.size) * 100)
      : thisWeekBooks.size > 0 ? 100 : 0;

    return {
      thisWeekNotes,
      thisWeekBooks: thisWeekBooks.size,
      lastWeekNotes,
      lastWeekBooks: lastWeekBooks.size,
      notesTrend,
      booksTrend,
    };
  }, [items]);

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="text-[10px] font-bold text-gray-400">本周新增笔记</div>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className="font-mono text-xl font-black text-gray-900">{pulse.thisWeekNotes}</span>
          {pulse.notesTrend !== 0 && (
            <span className={cx('text-[10px] font-bold', pulse.notesTrend > 0 ? 'text-teal' : 'text-red')}>
              {pulse.notesTrend > 0 ? '↑' : '↓'}{Math.abs(pulse.notesTrend)}%
            </span>
          )}
          {pulse.notesTrend === 0 && pulse.lastWeekNotes > 0 && (
            <span className="text-[10px] font-bold text-gray-400">持平</span>
          )}
        </div>
        <div className="mt-0.5 text-[9px] text-gray-400">上周 {pulse.lastWeekNotes}</div>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="text-[10px] font-bold text-gray-400">本周活跃书籍</div>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className="font-mono text-xl font-black text-gray-900">{pulse.thisWeekBooks}</span>
          {pulse.booksTrend !== 0 && (
            <span className={cx('text-[10px] font-bold', pulse.booksTrend > 0 ? 'text-teal' : 'text-red')}>
              {pulse.booksTrend > 0 ? '↑' : '↓'}{Math.abs(pulse.booksTrend)}%
            </span>
          )}
          {pulse.booksTrend === 0 && pulse.lastWeekBooks > 0 && (
            <span className="text-[10px] font-bold text-gray-400">持平</span>
          )}
        </div>
        <div className="mt-0.5 text-[9px] text-gray-400">上周 {pulse.lastWeekBooks}</div>
      </div>
    </div>
  );
}
