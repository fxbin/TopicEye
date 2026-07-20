'use client';

/**
 * Novel page 子组件（从 page.tsx 抽出的 10 个展示组件）。
 *
 * - MetricPill          小指标徽章
 * - MovementBadge        涨跌幅方向徽章
 * - MovementList         涨跌幅列表（含标题）
 * - WebnovelWeeklyPanel  网文周报面板（含平台汇总/分类/涨跌幅）
 * - WebnovelCard         单条网文趋势卡片
 * - BookCard             通用小说卡片（番茄/七猫/知乎/黑岩/点众 5 平台统一）
 * - FilterGroup          筛选组容器（标题 + children）
 * - SummaryMetric        汇总指标（label + value）
 * - MiniMetric           迷你指标
 * - FilterChip           筛选 chip 按钮
 * - SummaryTile          汇总方块
 *
 * 静态配置 + 工具函数来自 _novel-utils.ts。
 */

import React, { useEffect, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  Crown,
  ExternalLink,
  Filter,
  LineChart,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  TrendingUp,
  X,
} from 'lucide-react';
import { Button, Panel, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import type { TrendingItem, WebnovelMovementItem, WebnovelWeeklyReport } from '@/lib/api';
import {
  type Platform,
  type BookItem,
  PLATFORM_META,
  formatCount,
  formatDate,
  getItemTitle,
  getItemAuthor,
  getItemAbstract,
  getItemCover,
  getItemUrl,
  getPositionChange,
  getBookStableId,
  getBookFavoriteMeta,
  chipStyle,
  GROUP_LABELS,
  RANK_TYPE_LABELS,
  QIMAO_RANK_LABELS,
  QIMAO_CHANNEL_LABELS,
  ZHIHU_SORT_LABELS,
  ZHIHU_SUBCATS,
  ISHUGUI_RANK_LABELS,
  ISHUGUI_SHELF_TO_RANK,
  HEIYAN_SORT_STYLE,
  HEIYAN_SORT_FALLBACK,
  HEIYAN_HOME_SHELF_LABELS,
  HEIYAN_TYPE_STYLE,
} from './_novel-utils';

export function MetricPill({ children, color = '#6B7280', bg = '#F3F4F6' }: { children: React.ReactNode; color?: string; bg?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ background: bg, color }}>
      {children}
    </span>
  );
}


export function MovementBadge({ change }: { change: number }) {
  const rising = change > 0;
  return (
    <span className={cx('inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 font-mono text-[11px] font-black', rising ? 'bg-teal-light text-teal' : 'bg-red-light text-red')}>
      {rising ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
      {Math.abs(change)}
    </span>
  );
}

export function MovementList({ title, items, tone }: { title: string; items: WebnovelMovementItem[]; tone: 'up' | 'down' }) {
  return (
    <Panel className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[13px] font-black text-gray-800">
          {tone === 'up' ? <ArrowUp size={16} className="text-teal" /> : <ArrowDown size={16} className="text-red" />}
          {title}
        </div>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 font-mono text-[11px] text-gray-600">{items.length}</span>
      </div>
      <div className="flex flex-col gap-2">
        {items.length === 0 ? (
          <div className="rounded-sm border border-gray-100 bg-gray-50 p-4 text-center text-xs text-gray-500">暂无明显变化</div>
        ) : items.map((item, index) => (
          <a
            key={`${item.platform}-${item.title}-${item.rank_type}-${index}`}
            href={item.url || undefined}
            target="_blank"
            rel="noreferrer"
            className="grid grid-cols-[24px_minmax(0,1fr)_auto] items-start gap-2 rounded-sm border border-gray-100 bg-gray-50 p-3 text-left transition hover:border-primary-border hover:bg-white"
          >
            <div className="grid h-6 w-6 place-items-center rounded-xs bg-white font-mono text-[11px] font-black text-gray-500">{index + 1}</div>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-black text-gray-900">{item.title}</div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-gray-400">
                <span>{item.platform_label}</span>
                <span>{item.category}</span>
                <span>#{item.position}</span>
              </div>
            </div>
            <MovementBadge change={item.change} />
          </a>
        ))}
      </div>
    </Panel>
  );
}

export function WebnovelWeeklyPanel({ report, loading, onRefresh, days, onDaysChange }: { report: WebnovelWeeklyReport | null; loading: boolean; onRefresh: () => void; days: number; onDaysChange: (d: number) => void }) {
  const maxDaily = Math.max(...(report?.daily_counts?.map((item) => item.count) || [1]), 1);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-[18px]">
      {loading ? (
        <LoadingState label="正在生成网文周报" />
      ) : !report ? (
        <EmptyState icon={BookOpen} title="暂无网文周报" desc="同步网文榜单后再刷新周报。" />
      ) : (
        <div className="mx-auto flex max-w-6xl flex-col gap-4">
          {/* 时间窗切换：'按 X 天上升最快' */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-gray-500">时间窗：</span>
            {[3, 7, 14, 30].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => onDaysChange(d)}
                className={cx(
                  'rounded-sm border px-2.5 py-0.5 text-[12px] transition',
                  days === d
                    ? 'border-orange bg-orange text-white'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                )}
              >
                {d} 天
              </button>
            ))}
          </div>
          <Panel className="overflow-hidden p-0">
            <div className="border-b border-gray-100 bg-white px-5 py-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-2 flex items-center gap-2 text-xs font-black text-primary">
                    <LineChart size={16} />
                    WEBNOVEL WEEKLY
                  </div>
                  <h2 className="m-0 text-[24px] font-black text-gray-900">网文周报</h2>
                  <p className="mt-1 text-xs text-gray-500">{report.period?.label || ''} · 覆盖 {report.platforms?.length || 0} 个平台 · {report.summary?.snapshot_days || 0} 天历史快照</p>
                </div>
                <Button type="button" variant="secondary" onClick={onRefresh}>
                  <RefreshCw size={15} />
                  刷新周报
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-0 border-b border-gray-100 md:grid-cols-4">
              <SummaryMetric label="榜单样本" value={report.summary?.total_items || 0} />
              <SummaryMetric label="上升作品" value={report.summary?.rising_count || 0} tone="teal" />
              <SummaryMetric label="下跌作品" value={report.summary?.falling_count || 0} tone="red" />
              <SummaryMetric label="阅读增量" value={formatCount(report.summary?.read_count_delta || 0)} />
            </div>
            <div className="grid grid-cols-1 gap-3 p-4 lg:grid-cols-3">
              {(report.platforms || []).map((platform) => (
                <div key={platform.platform} className="rounded-sm border border-gray-100 bg-gray-50 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-sm font-black text-gray-900">{platform.label}</div>
                    <span className="rounded-full bg-white px-2 py-0.5 font-mono text-[11px] text-gray-500">{platform.history_days}d</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <MiniMetric label="样本" value={platform.item_count} />
                    <MiniMetric label="上升" value={platform.rising_count} tone="teal" />
                    <MiniMetric label="下跌" value={platform.falling_count} tone="red" />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <MovementList title="上升最快" items={report.top_risers || []} tone="up" />
              <MovementList title="下跌明显" items={report.top_fallers || []} tone="down" />
            </div>

            <div className="flex flex-col gap-4">
              <Panel className="p-4">
                <div className="mb-3 flex items-center gap-2 text-[13px] font-black text-gray-800">
                  <LineChart size={16} className="text-primary" />
                  番茄快照覆盖
                </div>
                <div className="flex items-end gap-1.5">
                  {(report.daily_counts || []).length === 0 ? (
                    <div className="rounded-sm border border-gray-100 bg-gray-50 p-4 text-center text-xs text-gray-400">暂无历史快照</div>
                  ) : (report.daily_counts || []).map((item) => (
                    <div key={item.date} className="flex flex-1 flex-col items-center gap-1.5">
                      <div className="w-full rounded-t-xs bg-primary" style={{ height: `${Math.max(12, (item.count / maxDaily) * 86)}px` }} />
                      <span className="text-[10px] text-gray-400">{formatDate(item.date)}</span>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel className="p-4">
                <div className="mb-3 flex items-center gap-2 text-[13px] font-black text-gray-800">
                  <Sparkles size={16} className="text-amber" />
                  分类热度
                </div>
                <div className="flex flex-col gap-3">
                  {Object.entries(report.category_mix || {}).map(([platform, items]) => (
                    <div key={platform}>
                      <div className="mb-1.5 text-[11px] font-black text-gray-400">{PLATFORM_META[platform as Platform]?.label || platform}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {items.slice(0, 6).map((item, idx) => (
                          <span key={`${platform}-${item.category}-${idx}`} className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] font-bold text-gray-600">
                            {item.category} · {item.count}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel className="p-4">
                <div className="mb-2 text-[13px] font-black text-gray-800">数据说明</div>
                <div className="space-y-2 text-xs leading-6 text-gray-500">
                  {(report.notes || []).map((note, index) => (
                    <p key={index} className="m-0">{note}</p>
                  ))}
                </div>
              </Panel>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 黑岩 / 点众卡片: 取 trending item extra 里的元数据 (author/words/tags/shelf) */
export function WebnovelCard({ item, platform }: { item: TrendingItem; platform: Platform }) {
  const ex = (item.extra || {}) as Record<string, unknown>;
  const author = (ex.author as string) || '';
  const words = (ex.words_str as string) || (ex.total_word_size as string) || '';
  const intro = (ex.intro as string) || '';
  const tags = Array.isArray(ex.tags)
    ? (ex.tags as string[])
    : Array.isArray(ex.tag_v3)
      ? (ex.tag_v3 as string[])
      : [];
  const shelf = (ex.shelf as string) || item.hot_value_raw || '';
  const score = ex.book_score != null ? String(ex.book_score) : '';
  const isShort = (ex.type as number) === 1 || (ex.words as number) <= 30000;
  const finished = ex.finished === true;
  const platformMeta = PLATFORM_META[platform];

  return (
    <article className="fanqie-book-card flex gap-3 rounded-sm border border-gray-200 bg-white p-3 transition hover:border-primary-border">
      <a
        href={item.url || '#'}
        target="_blank"
        rel="noopener noreferrer"
        className="relative h-[100px] w-[68px] shrink-0 overflow-hidden rounded-xs bg-gray-100"
      >
        {item.cover_url ? (
          <img src={item.cover_url} alt={item.title} className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[10px] text-gray-400">无封面</div>
        )}
      </a>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <a
            href={item.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="line-clamp-1 text-[13px] font-black leading-snug text-gray-900 no-underline"
          >
            {item.title}
          </a>
          <span className="font-mono text-[10px] text-gray-400">#{item.rank}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-gray-500">
          {author && <span>{author}</span>}
          {words && <span>· {words}</span>}
          {isShort && <span className="rounded-xs px-1 py-px font-bold" style={{ background: platformMeta.bg, color: platformMeta.color }}>短篇</span>}
          {finished && <span className="rounded-xs bg-gray-100 px-1 py-px font-bold text-gray-600">完结</span>}
          {score && <span className="text-amber">★ {score}</span>}
        </div>
        {intro && (
          <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-gray-500">{intro}</p>
        )}
        {tags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {tags.slice(0, 3).map((t, i) => (
              <span key={i} className="rounded-xs bg-gray-100 px-1 py-px text-[9px] text-gray-600">{t}</span>
            ))}
          </div>
        )}
        <div className="mt-1 flex items-center justify-between text-[10px] text-gray-400">
          <span>{shelf}</span>
          {item.url && (
            <a href={item.url} target="_blank" rel="noreferrer" title="打开原文" className="rounded-xs p-1 text-gray-400 transition hover:bg-gray-100 hover:text-primary">
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

export function BookCard({
  item,
  platform,
  rankTab,
  favorite,
  favoritePending,
  onFavorite,
}: {
  item: BookItem;
  platform: Platform;
  rankTab: string;
  favorite: boolean;
  favoritePending: boolean;
  onFavorite: (item: BookItem) => void;
}) {
  const [coverFailed, setCoverFailed] = useState(false);
  const pos = item.position;
  const title = getItemTitle(item);
  const author = getItemAuthor(item);
  const cover = getItemCover(item);
  const coverSrc = cover && !coverFailed ? cover : null;
  const abstract = getItemAbstract(item);
  const itemUrl = getItemUrl(item);
  const diff = getPositionChange(item);
  const isTop = pos <= 3;
  const platformMeta = PLATFORM_META[platform];

  useEffect(() => {
    setCoverFailed(false);
  }, [cover]);

  const meta = (() => {
    if (platform === 'fanqie' && 'read_count' in item) {
      const rankInfo = RANK_TYPE_LABELS[rankTab as keyof typeof RANK_TYPE_LABELS];
      return (
        <>
          <MetricPill color={rankInfo?.color} bg={rankInfo?.bg}>{rankInfo?.label || '榜单'}</MetricPill>
          <MetricPill>{formatCount(item.read_count)}阅读</MetricPill>
          <MetricPill>{formatCount(item.word_number)}字</MetricPill>
        </>
      );
    }
    if (platform === 'qimao' && 'collect_count' in item) {
      return (
        <>
          {item.is_continue_top === 1 && <MetricPill color="#D97706" bg="#FFFBEB"><Crown size={12} />霸榜</MetricPill>}
          {item.is_over === 1 && <MetricPill color="#4B5563" bg="#F3F4F6"><CheckCircle2 size={12} />完结</MetricPill>}
          <MetricPill color="#DC2626" bg="#FEF2F2">{formatCount(item.collect_count)}收藏</MetricPill>
          <MetricPill>{item.words_num}</MetricPill>
        </>
      );
    }
    if (platform === 'zhihu' && 'price_yuan' in item) {
      const sortInfo = ZHIHU_SORT_LABELS[item.sort_type as keyof typeof ZHIHU_SORT_LABELS] || ZHIHU_SORT_LABELS.hottest;
      return (
        <>
          <MetricPill color={sortInfo.color} bg={sortInfo.bg}>{sortInfo.label}</MetricPill>
          {item.is_exclusive && <MetricPill color="#D97706" bg="#FFFBEB">独家</MetricPill>}
          {item.tag === '会员专享' && <MetricPill color="#2563EB" bg="#EFF6FF">会员</MetricPill>}
          {item.chapter_text && <MetricPill>{item.chapter_text}</MetricPill>}
          {item.price_yuan && item.price_yuan !== '免费' && <MetricPill color="#DC2626" bg="#FEF2F2">{item.price_yuan}</MetricPill>}
        </>
      );
    }
    return null;
  })();

  const categoryText = (() => {
    if ('category1_name' in item && item.category1_name) {
      return [item.category1_name, item.category2_name].filter(Boolean).join(' · ');
    }
    return '';
  })();

  return (
    <article
      className={cx(
        'fanqie-book-card grid min-w-0 gap-[var(--fanqie-card-gap,16px)] rounded-sm border bg-white p-4 shadow-sm',
        isTop ? 'border-amber-border shadow-amber-100' : 'border-gray-200',
      )}
      style={{ gridTemplateColumns: 'var(--fanqie-card-cols, 44px 82px minmax(0, 1fr))' }}
    >
      <div className="flex flex-col items-center gap-1.5">
        <div className={cx('grid h-[34px] w-[34px] place-items-center rounded-sm font-mono text-base font-black', isTop ? 'bg-amber-light text-amber' : 'bg-gray-50 text-gray-400')}>
          {pos}
        </div>
        {typeof diff === 'number' && diff !== 0 && (
          <span className={cx('inline-flex items-center gap-0.5 font-mono text-[11px] font-extrabold', diff > 0 ? 'text-teal' : 'text-red')}>
            {diff > 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
            {Math.abs(diff)}
          </span>
        )}
      </div>

      {coverSrc ? (
        // eslint-disable-next-line @next/next/no-img-element -- Covers come from multiple external book platforms.
        <img
          src={coverSrc}
          alt={title}
          className="h-[var(--fanqie-cover-h,108px)] w-[var(--fanqie-cover-w,82px)] rounded-sm bg-gray-100 object-cover shadow-lg"
          onError={() => setCoverFailed(true)}
        />
      ) : (
        <div
          aria-label={`${title} 封面占位`}
          style={{
            width: 'var(--fanqie-cover-w, 82px)',
            height: 'var(--fanqie-cover-h, 108px)',
            background: `linear-gradient(160deg, ${platformMeta.bg}, #FAFAFA)`,
            color: platformMeta.color,
          }}
          className="grid place-items-center rounded-sm border border-gray-200 p-2 text-center text-[13px] font-black leading-tight shadow-md"
        >
          {title.slice(0, 2) || '书'}
        </div>
      )}

      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="m-0 truncate text-[17px] font-black leading-tight text-gray-900">{title}</h2>
            <div className="mt-1 text-xs text-gray-500">
              {author}{categoryText && <span className="text-gray-400"> · {categoryText}</span>}
            </div>
          </div>
          <button
            type="button"
            disabled={favoritePending}
            onClick={() => onFavorite(item)}
            title={favorite ? '移出收藏' : '收藏作品'}
            className={cx(
              'grid h-7 w-7 shrink-0 place-items-center rounded-xs border transition disabled:cursor-wait disabled:opacity-60',
              favorite ? 'border-amber-border bg-amber-light text-amber' : 'border-gray-200 bg-white text-gray-400 hover:border-amber-border hover:text-amber',
            )}
          >
            <Star size={15} strokeWidth={2.1} fill={favorite ? 'currentColor' : 'none'} />
          </button>
          {itemUrl && (
            <a href={itemUrl} target="_blank" rel="noreferrer" title="打开官网原文" className="rounded-xs p-1 text-gray-400 transition hover:bg-gray-100 hover:text-primary">
              <ExternalLink size={16} />
            </a>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">{meta}</div>

        {abstract && (
          <p className="line-clamp-3 m-0 text-xs leading-6 text-gray-500">
            {abstract}
          </p>
        )}

        {'latest_chapter_title' in item && item.latest_chapter_title && (
          <div className="truncate text-[11px] text-gray-400">更新 {item.latest_chapter_title}</div>
        )}
        {'last_chapter_title' in item && item.last_chapter_title && (
          <div className="truncate text-[11px] text-gray-400">更新 {item.last_chapter_title}</div>
        )}
      </div>
    </article>
  );
}

export function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-extrabold text-gray-500">{title}</div>
      <div className="flex w-full flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

export function SummaryMetric({ label, value, tone = 'neutral' }: { label: string; value: string | number; tone?: 'neutral' | 'teal' | 'red' }) {
  const toneClass = tone === 'teal' ? 'text-teal' : tone === 'red' ? 'text-red' : 'text-gray-900';
  return (
    <div className="border-r border-gray-100 p-4 last:border-r-0">
      <div className="mb-1 text-[11px] text-gray-400">{label}</div>
      <div className={cx('font-mono text-2xl font-black leading-none', toneClass)}>{value}</div>
    </div>
  );
}

export function MiniMetric({ label, value, tone = 'neutral' }: { label: string; value: string | number; tone?: 'neutral' | 'teal' | 'red' }) {
  const toneClass = tone === 'teal' ? 'text-teal' : tone === 'red' ? 'text-red' : 'text-gray-900';
  return (
    <div className="rounded-xs bg-white px-2 py-2">
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className={cx('mt-0.5 font-mono text-sm font-black', toneClass)}>{value}</div>
    </div>
  );
}

export function FilterChip({
  active,
  color,
  onClick,
  children,
  className,
  title,
}: {
  active: boolean;
  color: string;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cx('whitespace-nowrap rounded-xs border px-3 py-2 text-xs font-bold transition', className)}
      style={chipStyle(active, color)}
    >
      {children}
    </button>
  );
}

export function SummaryTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
      <div className="mb-1 text-[11px] text-gray-400">{label}</div>
      <div className="font-mono text-xl font-black text-gray-900">{value}</div>
    </div>
  );
}
