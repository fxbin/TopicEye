'use client';

/**
 * Trending page 子组件（从 page.tsx 抽出的展示组件）。
 *
 * 9 个展示组件：
 * - WebnovelItemRow      网文榜单行（额外信息密度展示）
 * - TrendBadge           趋势方向徽章（up/down/new/stable）
 * - PanelTitle           面板标题（re-export 自 @/components/ui）
 * - StatTile             统计数字块（re-export 自 @/components/StatTile）
 * - ResonanceBadge       跨平台共鸣度徽章
 * - SourceMiniItem       单平台在跨平台聚类中的迷你链接
 * - AnglePanel           AI 角度推荐面板（含 fetchAngles 状态）
 * - ClusterCardExpanded  跨平台聚类卡片展开详情
 * - ClusterCard          跨平台聚类卡片（折叠/展开）
 *
 * 静态配置（CATEGORIES / SOURCE_BRAND / CATEGORY_COLORS / TREND_ICONS /
 * RESONANCE_COLORS / isWebnovelSource）来自 _trending-utils.ts。
 */

import React, { useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ExternalLink,
  Lightbulb,
  Star,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Panel, cx } from '@/components/ui';
// PanelTitle / StatTile 已收敛到公共组件层，此处 re-export 保持调用方 import 路径不变。
export { PanelTitle } from '@/components/ui';
export { StatTile } from '@/components/StatTile';
import {
  trendingApi,
  type CrossPlatformCluster,
  type CrossPlatformSourceItem,
  type TrendingAngleRecommendation,
  type TrendingItem,
} from '@/lib/api';
import {
  CATEGORY_COLORS,
  RESONANCE_COLORS,
  SOURCE_LABELS,
  TREND_ICONS,
  isWebnovelSource,
} from './_trending-utils';

export function WebnovelItemRow({ item, rank }: { item: TrendingItem; rank: number }) {
  const extra = (item.extra || {}) as Record<string, unknown>;
  const author = (extra.author as string) || '';
  const words = (extra.words_str as string) || (extra.total_word_size as string) || '';
  const tags = Array.isArray(extra.tags)
    ? (extra.tags as unknown[]).map(String)
    : Array.isArray(extra.tag_v3)
      ? (extra.tag_v3 as unknown[]).map(String)
      : [];
  const shelf = (extra.shelf as string) || item.hot_value_raw || '';
  const score = extra.book_score != null ? String(extra.book_score) : '';
  const isShort = (extra.type as number) === 1 || (extra.words as number) <= 30000;

  return (
    <a
      href={item.url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      className={cx(
        'flex items-start gap-2.5 border-b border-gray-100 px-3.5 py-2 no-underline transition hover:bg-purple-light',
        rank <= 3 ? 'bg-gray-50' : 'bg-white',
      )}
    >
      <span className={cx(
        'mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-xs font-mono text-[11px] font-black',
        rank === 1 ? 'bg-gradient-to-br from-purple to-[#C084FC] text-white'
          : rank === 2 ? 'bg-gradient-to-br from-amber to-[#FFB870] text-white'
            : rank === 3 ? 'bg-gradient-to-br from-[#FFD59E] to-[#FFE0B2] text-white'
              : 'bg-gray-100 text-gray-500',
      )}>
        {rank}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-black leading-snug text-gray-900">
          {item.title}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-gray-500">
          {author && <span>{author}</span>}
          {words && <span>· {words}</span>}
          {isShort && <span className="rounded-xs bg-purple-light px-1 py-px font-bold text-purple">短篇</span>}
          {score && <span className="text-amber">★ {score}</span>}
        </div>
        {tags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {tags.slice(0, 3).map((t, i) => (
              <span key={i} className="rounded-xs bg-gray-100 px-1 py-px text-[9px] text-gray-600">
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      <span className="mt-0.5 shrink-0 whitespace-nowrap text-[9px] text-gray-400">
        {shelf}
      </span>
    </a>
  );
}

export function TrendBadge({ trend }: { trend: string | null }) {
  if (!trend || trend === 'stable') return null;
  const colors: Record<string, { className: string; fill: string }> = {
    up: { className: 'bg-red-light text-red', fill: 'none' },
    down: { className: 'bg-teal-light text-teal', fill: 'none' },
    new: { className: 'bg-primary-light text-primary', fill: 'currentColor' },
  };
  const c = colors[trend] || { className: 'bg-gray-100 text-gray-600', fill: 'none' };
  const Icon = TREND_ICONS[trend] || ArrowRight;
  return (
    <span className={cx('inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-black', c.className)}>
      <Icon size={11} strokeWidth={2.2} fill={c.fill} />
    </span>
  );
}

export function ResonanceBadge({ resonance }: { resonance: number }) {
  const c = RESONANCE_COLORS[resonance] || RESONANCE_COLORS[2];
  return (
    <span className={cx('whitespace-nowrap rounded-xs px-2 py-0.5 text-[11px] font-black', c.bgClass, c.textClass)}>
      {c.label} · {resonance}平台
    </span>
  );
}

export function SourceMiniItem({ item }: { item: CrossPlatformSourceItem }) {
  return (
    <a
      href={item.url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      className="flex min-w-0 flex-1 items-center gap-2 rounded-xs border border-gray-100 bg-white px-2.5 py-1.5 no-underline transition hover:border-primary-border hover:bg-primary-light"
    >
      <span className={cx('min-w-4 text-[10px] font-black', item.rank <= 3 ? 'text-primary' : 'text-gray-400')}>
        #{item.rank}
      </span>
      <span className="flex-1 truncate text-xs text-gray-700">
        {item.title}
      </span>
      <span className="shrink-0 text-[10px] text-gray-400">
        {SOURCE_LABELS[item.source] || item.source}
      </span>
    </a>
  );
}

export function AnglePanel({ cluster }: { cluster: CrossPlatformCluster }) {
  const { currentUser } = useAppContext();
  const [angles, setAngles] = useState<TrendingAngleRecommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetched, setFetched] = useState(false);

  const fetchAngles = async () => {
    if (fetched || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await trendingApi.angles(cluster.topic);
      setAngles(data);
      setFetched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '角度生成失败');
    } finally {
      setLoading(false);
    }
  };

  if (!currentUser) return null;

  return (
    <div className="mt-2 rounded-sm border border-amber-border bg-amber-light px-3.5 py-2.5">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[11px] font-black text-amber">AI 角度推荐</span>
        {!fetched && !loading && (
          <button
            type="button"
            onClick={fetchAngles}
            className="rounded-full bg-amber px-2 py-0.5 text-[10px] font-black text-white"
          >
            生成反差角度
          </button>
        )}
        {loading && <span className="text-[10px] text-amber">生成中...</span>}
      </div>

      {angles && angles.common_angles.length > 0 && (
        <div className="mb-2">
          <div className="mb-1 text-[10px] font-black text-amber">
            大众角度（不要写）：
          </div>
          <div className="flex flex-wrap gap-1">
            {angles.common_angles.map((a, i) => (
              <span key={i} className="rounded-xs bg-amber-light px-1.5 py-0.5 text-[10px] text-amber line-through">
                {a}
              </span>
            ))}
          </div>
        </div>
      )}

      {angles && angles.contrast_angles.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-black text-teal">
            反差角度（值得写）：
          </div>
          {angles.contrast_angles.map((c, i) => (
            <div key={i} className="mb-1.5 rounded-xs bg-teal-light px-2.5 py-1.5">
              <div className="mb-0.5 text-xs font-black text-teal">
                <span className="inline-flex items-center gap-1.5">
                  <ArrowRight size={12} strokeWidth={2} />
                  {c.angle}
                </span>
              </div>
              <div className="text-[10px] text-teal">{c.reasoning}</div>
            </div>
          ))}
        </div>
      )}

      {angles && angles.angle_note && (
        <div className="mt-1.5 flex items-start gap-1.5 rounded-xs bg-teal-light px-2 py-1 text-[10px] italic text-teal">
          <Lightbulb size={12} strokeWidth={2} className="mt-px shrink-0" />
          <span>{angles.angle_note}</span>
        </div>
      )}

      {error && <div className="text-[10px] text-red">{error}</div>}
    </div>
  );
}

export function ClusterCardExpanded({ cluster }: { cluster: CrossPlatformCluster }) {
  return (
    <>
      <div className="mb-2 text-[11px] font-black uppercase tracking-[0.05em] text-gray-500">
        各平台排名
      </div>
      <div className="flex flex-wrap gap-1.5">
        {cluster.source_items.map((item) => (
          <SourceMiniItem key={`${item.source}-${item.rank}`} item={item} />
        ))}
      </div>
      <div className="mt-2.5 flex items-center justify-between gap-3 border-t border-dashed border-gray-200 pt-2">
        <span className="text-[11px] text-gray-400">
          平均排名 #{cluster.avg_rank} · {cluster.total_hot.toLocaleString()} 总热度
        </span>
        <a
          href={cluster.source_items[0]?.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[11px] font-black text-primary no-underline"
        >
          查看详情
          <ExternalLink size={12} strokeWidth={2} />
        </a>
      </div>

      <AnglePanel cluster={cluster} />
    </>
  );
}

export function ClusterCard({ cluster }: { cluster: CrossPlatformCluster }) {
  const [expanded, setExpanded] = useState(false);
  const resonanceMeta = RESONANCE_COLORS[cluster.resonance] || RESONANCE_COLORS[2];

  return (
    <Panel className="overflow-hidden shadow-[0_10px_26px_rgba(15,23,42,0.04)] transition hover:border-gray-300 hover:shadow-md">
      <div
        onClick={() => setExpanded(!expanded)}
        className={cx('cursor-pointer px-4 py-3.5', expanded ? 'bg-primary-light/60' : 'bg-white')}
      >
        <div className="flex items-start gap-2.5">
          <div className={cx('flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-md border', resonanceMeta.bgClass, resonanceMeta.textClass, resonanceMeta.borderClass)}>
            <span className="text-base font-black leading-none">{cluster.resonance}</span>
            <span className="mt-0.5 text-[8px] font-black">平台</span>
          </div>

          <div className="min-w-0 flex-1">
            <div className="line-clamp-2 text-sm font-bold leading-snug text-gray-900">
              {cluster.topic}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {cluster.keywords.slice(0, 4).map((kw) => (
                <span key={kw} className="rounded bg-gray-100 px-1.5 py-px text-[10px] text-gray-500">
                  #{kw}
                </span>
              ))}
            </div>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <ResonanceBadge resonance={cluster.resonance} />
            <span className="inline-flex items-center gap-1 text-[11px] text-gray-400">
              {expanded ? '收起' : '展开'}
              {expanded ? <ArrowUp size={12} strokeWidth={2} /> : <ArrowDown size={12} strokeWidth={2} />}
            </span>
          </div>
        </div>

        <div className="mt-2.5 flex gap-1.5 overflow-x-auto pb-1">
          {cluster.source_labels.map((label, i) => (
            <span key={i} className="shrink-0 whitespace-nowrap rounded-full bg-teal-light px-2 py-0.5 text-[10px] font-semibold text-teal">
              {label}
            </span>
          ))}
          <span className="ml-1 shrink-0 text-[10px] text-gray-400">
            {cluster.item_count}条相关内容
          </span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 bg-primary-light/60 px-4 pb-3.5 pt-2.5">
          <ClusterCardExpanded cluster={cluster} />
        </div>
      )}
    </Panel>
  );
}