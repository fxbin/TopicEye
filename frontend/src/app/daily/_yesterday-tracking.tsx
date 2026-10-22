'use client';

/**
 * 昨日追踪卡（一期补连续性闭环）。
 *
 * 展示昨日 top picks 的今日进展：24h 热度 delta + lifecycle 验证
 * （上升期→确认/反转）+ 是否仍在榜。scope=mine 时额外展示「我标过的」。
 *
 * 设计目标：让日报从「每天一张静态榜单」变成「连续追更的编辑台」，
 * 创作者能一眼看到昨天推的选题今天是否兑现。
 */

import React from 'react';
import { ArrowRight, Loader2, TrendingDown, TrendingUp, Minus } from 'lucide-react';
import { Panel, cx } from '@/components/ui';
import type { YesterdayTrackingData, YesterdayPickStatus } from '@/types';
import { LIFECYCLE_META } from './_daily-utils';

function LifecycleChip({ lifecycle }: { lifecycle: string | null }) {
  if (!lifecycle) {
    return <span className="text-[12px] text-gray-500">—</span>;
  }
  const meta = LIFECYCLE_META[lifecycle];
  if (!meta) {
    return <span className="text-[12px] text-gray-500">{lifecycle}</span>;
  }
  return (
    <span className={cx('rounded-xs px-1.5 py-0.5 text-[12px] font-bold', meta.color, meta.bg)}>
      {meta.label}
    </span>
  );
}

// 状态判定 → 中文标签 + 配色
const STATUS_META: Record<YesterdayPickStatus, { label: string; color: string; bg: string }> = {
  confirmed: { label: '兑现', color: 'text-teal-text', bg: 'bg-teal-light' },
  reversed: { label: '反转', color: 'text-amber-800', bg: 'bg-amber-light' },
  persisted: { label: '仍在榜', color: 'text-primary-text', bg: 'bg-primary-light' },
  dropped: { label: '掉出', color: 'text-gray-500', bg: 'bg-gray-100' },
};

function HeatDelta({ pct }: { pct: number | null }) {
  if (pct === null) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[12px] font-bold text-gray-500">
        <Minus size={11} /> —
      </span>
    );
  }
  const up = pct > 0;
  const flat = Math.abs(pct) < 1;
  const Icon = flat ? Minus : up ? TrendingUp : TrendingDown;
  const color = flat ? 'text-gray-500' : up ? 'text-teal-text' : 'text-red-700';
  const sign = up ? '+' : '';
  return (
    <span className={cx('inline-flex items-center gap-0.5 text-[12px] font-bold tabular-nums', color)}>
      <Icon size={11} /> {sign}
      {pct.toFixed(0)}%
    </span>
  );
}

function StatusBadge({ status }: { status: YesterdayPickStatus }) {
  const meta = STATUS_META[status];
  return (
    <span className={cx('rounded-xs px-1.5 py-0.5 text-[12px] font-bold', meta.color, meta.bg)}>
      {meta.label}
    </span>
  );
}

export default function YesterdayTracking({ data, loading = false }: { data: YesterdayTrackingData | null; loading?: boolean }) {

  // 加载中且尚未有数据：显示骨架占位，避免内容跳动
  if (loading && !data) {
    return (
      <Panel className="mb-4 animate-pulse border-gray-100 bg-gray-50 px-4 py-3">
        <div className="flex items-center gap-2 text-[12px] text-gray-500">
          <Loader2 size={12} className="animate-spin" />
          昨日追踪加载中…
        </div>
      </Panel>
    );
  }

  // 明确区分无对照报告与加载失败。
  if (!data || !data.has_yesterday || data.picks.length === 0) {
    return <p className="py-2 text-sm text-gray-500">{data ? '暂无可对照的昨日情报' : '昨日追踪暂时不可用'}</p>;
  }

  return (
    <Panel className="mb-4 border-gray-200 bg-white px-4 py-3.5">
      {/* 标题行 */}
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-1.5">
          <span className="whitespace-nowrap text-[13px] font-bold text-gray-700">昨日追踪</span>
          <span className="whitespace-nowrap text-[12px] text-gray-500">{data.report_date}</span>
        </div>
        <span className="whitespace-nowrap text-[12px] text-gray-500">
          {data.picks.length} 个选题 · 24h 复盘
        </span>
      </div>

      {/* 昨日 top picks 追踪列表 */}
      <ul className="divide-y divide-gray-50">
        {data.picks.slice(0, 8).map((pick) => (
          <li key={`${pick.rank}-${pick.source_title}`} className="grid grid-cols-[16px_minmax(0,1fr)] items-start gap-x-2 gap-y-2 py-3">
            {/* 排名 */}
            <span className="w-4 shrink-0 text-center text-[12px] font-bold text-gray-500">
              {pick.rank + 1}
            </span>
            {/* 标题 */}
            <span className="min-w-0 break-words text-[13px] leading-6 text-gray-700">
              {pick.title}
            </span>
            <div className="col-span-2 flex flex-wrap items-center gap-x-3 gap-y-2">
            {/* lifecycle 变化 */}
            <span className="flex shrink-0 items-center gap-1">
              <LifecycleChip lifecycle={pick.yesterday_lifecycle} />
              <ArrowRight size={10} className="text-gray-500" />
              <LifecycleChip lifecycle={pick.today_lifecycle} />
            </span>
            {/* 热度 delta */}
            <span className="shrink-0 text-right">
              <HeatDelta pct={pick.heat_delta_pct} />
            </span>
            {/* 状态 badge */}
            <span className="shrink-0 text-right">
              <StatusBadge status={pick.status} />
            </span>
            </div>
          </li>
        ))}
      </ul>

      {/* scope=mine：我标过的昨日选题今日进展（二期个性化数据预留） */}
      {data.your_marked.length > 0 && (
        <div className="mt-2.5 border-t border-gray-100 pt-2.5">
          <div className="mb-1.5 text-[12px] font-bold text-gray-500">
            我标过的（{data.your_marked.length}）
          </div>
          <ul className="space-y-1">
            {data.your_marked.map((m, idx) => (
              <li key={idx} className="flex items-center gap-2">
                <span
                  className={cx(
                    'rounded-xs px-1 py-0.5 text-[12px] font-bold',
                    m.mark === 'write' ? 'bg-teal-light text-teal-text' : 'bg-amber-light text-amber-800',
                  )}
                >
                  {m.mark === 'write' ? '已选' : '观察'}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] text-gray-600" title={m.title}>
                  {m.title}
                </span>
                <LifecycleChip lifecycle={m.today_lifecycle} />
                <StatusBadge status={m.status} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
