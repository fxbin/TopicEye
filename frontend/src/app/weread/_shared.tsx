/**
 * 微信读书书架页共享资产（常量 / 类型 / 辅助函数 / 子组件）。
 *
 * 从 app/weread/page.tsx 抽出：
 * - 常量：SHELF_PAGE_SIZE, WEREAD_FALLBACK_URL, SORT_OPTIONS, GROUP_OPTIONS, CHART_COLORS
 * - 类型：WeReadMeta, SortKey, SortOrder, GroupKey
 * - 辅助函数：parseWeReadMeta, getReadingStatus, wereadSearchUrl, wereadBookUrl, isPausedReading
 * - 内部组件：BookCard, DiscoverBookCard, BookDetailPanel, StatCard,
 *           StatusDonut, TopNBars, ProgressHistogram, CompletionFunnel,
 *           NoteDensityScatter, WeeklyPulse, BestBookmarksSection,
 *           ReadingStatsCard, ShelfComparison
 *
 * page.tsx 与 _tabs.tsx 通过 import 使用这些资产，保持主体只含数据获取与状态编排。
 */

'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpen,
  ExternalLink,
  RefreshCw,
  ChevronDown,
  Highlighter,
  MessageSquare,
  X,
  Star,
  Loader2,
  Clock,
  BookMarked,
  Timer,
  CalendarDays,
  Users,
  Layers,
} from 'lucide-react';
import { useDialogFocus } from '@/components/useDialogFocus';
import { integrationsApi } from '@/lib/api';
import { Panel, Badge, Surface, cx } from '@/components/ui';
import { AutoLink } from '@/components/AutoLink';
import type {
  ContentItem,
  WeReadSearchBook,
  WeReadReadData,
  WeReadBestBookmarks,
  WeReadShelfSync,
} from '@/types';

export const SHELF_PAGE_SIZE = 200; // 书架视图一次拉满，客户端排序/分组

// ── 从 summary 解析 WeRead 结构化数据 ──

export interface WeReadMeta {
  noteCount: number;
  reviewCount: number;
  readingProgress: number; // 0-100
}

export function parseWeReadMeta(item: ContentItem): WeReadMeta {
  const summary = item.summary || '';
  const raw = item.raw_content || '';
  const text = `${summary}\n${raw}`;
  const noteMatch = text.match(/(\d+)\s*条划线/);
  const reviewMatch = text.match(/(\d+)\s*条想法/);
  const progressMatch = text.match(/阅读进度\s*(\d+)%/);
  return {
    noteCount: noteMatch ? parseInt(noteMatch[1], 10) : 0,
    reviewCount: reviewMatch ? parseInt(reviewMatch[1], 10) : 0,
    readingProgress: progressMatch ? parseInt(progressMatch[1], 10) : 0,
  };
}

// ── 排序 & 分组类型 ──

export type SortKey = 'published_at' | 'title' | 'noteCount' | 'reviewCount' | 'readingProgress';
export type SortOrder = 'asc' | 'desc';
export type GroupKey = 'none' | 'author' | 'status' | 'weread_category';

export const SORT_OPTIONS: Array<{ value: SortKey; label: string }> = [
  { value: 'published_at', label: '最近笔记' },
  { value: 'title', label: '书名' },
  { value: 'noteCount', label: '划线数' },
  { value: 'reviewCount', label: '想法数' },
  { value: 'readingProgress', label: '阅读进度' },
];

export const GROUP_OPTIONS: Array<{ value: GroupKey; label: string }> = [
  { value: 'none', label: '不分组' },
  { value: 'author', label: '按作者' },
  { value: 'status', label: '按阅读状态' },
  { value: 'weread_category', label: '微信读书分类' },
];

export function getReadingStatus(progress: number): '未读' | '在读' | '已读' {
  if (progress >= 90) return '已读';
  if (progress > 0) return '在读';
  return '未读';
}

// ── 微信读书网页版跳转 URL ──

export const WEREAD_FALLBACK_URL = 'https://weread.qq.com/r/weread-skills';

/** 构造微信读书网页版搜索 URL，用于书架中没有直接 deepLink 的书 */
export function wereadSearchUrl(title: string): string {
  return `https://weread.qq.com/#search/${encodeURIComponent(title)}`;
}

/** 获取书架书籍的微信读书跳转 URL：有真实 URL 用 URL，否则用搜索 URL */
export function wereadBookUrl(item: ContentItem): string {
  if (item.url && item.url !== WEREAD_FALLBACK_URL) {
    return item.url;
  }
  return wereadSearchUrl(item.title);
}

/** 检测是否为暂停阅读：进度 < 50% 且 30 天无笔记活动 */
export function isPausedReading(meta: WeReadMeta, publishedAt: string | null): boolean {
  if (meta.readingProgress >= 50) return false;
  if (!publishedAt) return false;
  const date = new Date(publishedAt);
  if (Number.isNaN(date.getTime())) return false;
  const daysSince = (Date.now() - date.getTime()) / (1000 * 60 * 60 * 24);
  return daysSince >= 30;
}

// ── 书架卡片 ──

export function BookCard({ item, meta, onExpand }: {
  item: ContentItem;
  meta: WeReadMeta;
  onExpand: () => void;
}) {
  const status = getReadingStatus(meta.readingProgress);
  const statusColor = status === '已读' ? 'teal' : status === '在读' ? 'primary' : 'neutral';
  const paused = isPausedReading(meta, item.published_at || null);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onExpand}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onExpand(); }}
      className="group relative flex cursor-pointer flex-col items-center text-center transition hover:-translate-y-1"
    >
      {/* 封面 */}
      <div className="relative mb-2 h-[140px] w-[100px] shrink-0">
        {item.cover_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.cover_url}
            alt=""
            className="h-full w-full rounded-md object-cover shadow-sm transition group-hover:shadow-lg"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
              const sib = (e.target as HTMLImageElement).nextElementSibling as HTMLElement | null;
              if (sib) sib.style.display = 'flex';
            }}
          />
        ) : null}
        <div
          className={cx(
            'absolute inset-0 grid place-items-center rounded-md bg-gray-100 shadow-sm',
            item.cover_url ? 'hidden' : 'flex',
          )}
        >
          <BookOpen size={20} className="text-gray-300" />
        </div>

        {/* 进度条叠加在封面底部 */}
        {meta.readingProgress > 0 && (
          <div className="absolute bottom-0 left-0 right-0 overflow-hidden rounded-b-md bg-black/50 backdrop-blur-sm">
            <div
              className={cx(
                'h-1',
                status === '已读' ? 'bg-teal' : 'bg-primary',
              )}
              style={{ width: `${meta.readingProgress}%` }}
            />
          </div>
        )}

        {/* 跳转微信读书按钮 — 悬停显示 */}
        <a
          href={wereadBookUrl(item)}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="在微信读书中打开"
          className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 opacity-0 shadow-md transition group-hover:opacity-100 hover:bg-white hover:text-primary"
        >
          <ExternalLink size={11} />
        </a>
      </div>

      {/* 书名 */}
      <h3 className="line-clamp-2 max-w-[110px] text-xs font-bold leading-4 text-gray-800">
        {item.title}
      </h3>

      {/* 作者 */}
      {item.author && (
        <p className="mt-0.5 line-clamp-1 max-w-[110px] text-[10px] text-gray-400">
          {item.author}
        </p>
      )}

      {/* 划线/想法徽章 */}
      <div className="mt-1 flex items-center gap-1">
        {meta.noteCount > 0 && (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-primary-light px-1.5 py-0.5 text-[9px] font-bold text-primary">
            <Highlighter size={8} />
            {meta.noteCount}
          </span>
        )}
        {meta.reviewCount > 0 && (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-teal-light px-1.5 py-0.5 text-[9px] font-bold text-teal">
            <MessageSquare size={8} />
            {meta.reviewCount}
          </span>
        )}
        {meta.noteCount === 0 && meta.reviewCount === 0 && (
          <span className="text-[9px] text-gray-300">无笔记</span>
        )}
      </div>

      {/* 状态标签 */}
      <span
        className={cx(
          'mt-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold',
          statusColor === 'teal' && 'bg-teal-light text-teal',
          statusColor === 'primary' && 'bg-primary-light text-primary',
          statusColor === 'neutral' && 'bg-gray-100 text-gray-400',
        )}
      >
        {status}
      </span>
      {/* 暂停阅读标记 */}
      {paused && (
        <span className="mt-0.5 inline-flex items-center gap-0.5 rounded-full bg-amber-light px-1.5 py-0.5 text-[9px] font-bold text-amber">
          <Clock size={8} />
          暂停
        </span>
      )}
    </div>
  );
}

// ── 发现模式搜索结果卡片 ──

export function DiscoverBookCard({ book, inShelf }: {
  book: WeReadSearchBook;
  inShelf: boolean;
}) {
  const ratingLabel = book.newRatingDetail?.title;
  const ratingColor =
    ratingLabel === '神作' ? 'teal' :
    ratingLabel === '好评如潮' || ratingLabel === '值得一读' ? 'primary' :
    'neutral';

  return (
    <div className="group flex flex-col items-center text-center transition hover:-translate-y-1">
      {/* 封面 */}
      <div className="relative mb-2 h-[140px] w-[100px] shrink-0">
        {book.cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={book.cover}
            alt=""
            className="h-full w-full rounded-md object-cover shadow-sm transition group-hover:shadow-lg"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
              const sib = (e.target as HTMLImageElement).nextElementSibling as HTMLElement | null;
              if (sib) sib.style.display = 'flex';
            }}
          />
        ) : null}
        <div
          className={cx(
            'absolute inset-0 grid place-items-center rounded-md bg-gray-100 shadow-sm',
            book.cover ? 'hidden' : 'flex',
          )}
        >
          <BookOpen size={20} className="text-gray-300" />
        </div>

        {/* 已在书架角标 */}
        {inShelf && (
          <div className="absolute right-0 top-0 rounded-bl-md rounded-tr-md bg-teal px-1.5 py-0.5 text-[9px] font-black text-white shadow">
            书架中
          </div>
        )}
      </div>

      {/* 书名 */}
      <h3 className="line-clamp-2 max-w-[110px] text-xs font-bold leading-4 text-gray-800">
        {book.title}
      </h3>

      {/* 作者 */}
      {book.author && (
        <p className="mt-0.5 line-clamp-1 max-w-[110px] text-[10px] text-gray-400">
          {book.author}
        </p>
      )}

      {/* 评分徽章 */}
      <div className="mt-1 flex items-center gap-1">
        {book.newRating && (
          <span
            className={cx(
              'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-bold',
              ratingColor === 'teal' && 'bg-teal-light text-teal',
              ratingColor === 'primary' && 'bg-primary-light text-primary',
              ratingColor === 'neutral' && 'bg-gray-100 text-gray-400',
            )}
          >
            <Star size={8} className="fill-current" />
            {(book.newRating / 10).toFixed(1)}
          </span>
        )}
        {book.readingCount !== undefined && book.readingCount > 0 && (
          <span className="text-[9px] text-gray-400">
            {book.readingCount > 10000 ? `${(book.readingCount / 10000).toFixed(1)}万` : book.readingCount} 人在读
          </span>
        )}
      </div>

      {/* 外链 — 始终显示 */}
      <a
        href={book.deepLink || wereadSearchUrl(book.title)}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 inline-flex items-center gap-0.5 text-[9px] font-bold text-primary hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        去读
        <ExternalLink size={8} />
      </a>
    </div>
  );
}

// ── 划线详情面板 ──

export function BookDetailPanel({ item, meta, onClose }: {
  item: ContentItem;
  meta: WeReadMeta;
  onClose: () => void;
}) {
  const { dialogRef, onKeyDown } = useDialogFocus<HTMLDivElement>(true, onClose);
  const status = getReadingStatus(meta.readingProgress);
  return (
    <>
      <div aria-hidden="true" className="fixed inset-0 z-50 bg-black/40" onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="weread-book-detail-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="pointer-events-none fixed inset-0 z-[51] flex items-center justify-center p-4"
      >
        <Panel className="pointer-events-auto max-h-[85vh] w-full max-w-2xl overflow-y-auto p-6">
        {/* 头部 */}
        <div className="mb-4 flex items-start gap-4">
          <div className="h-[120px] w-[90px] shrink-0">
            {item.cover_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.cover_url}
                alt=""
                className="h-full w-full rounded-md object-cover shadow-md"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
            ) : (
              <div className="grid h-full w-full place-items-center rounded-md bg-gray-100">
                <BookOpen size={24} className="text-gray-300" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="weread-book-detail-title" className="mb-1 break-words text-lg font-black text-gray-900">{item.title}</h2>
            {item.author && (
              <p className="mb-2 text-sm text-gray-500">{item.author}</p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {meta.noteCount > 0 && (
                <Badge tone="primary">
                  <Highlighter size={10} className="mr-1" />
                  {meta.noteCount} 条划线
                </Badge>
              )}
              {meta.reviewCount > 0 && (
                <Badge tone="teal">
                  <MessageSquare size={10} className="mr-1" />
                  {meta.reviewCount} 条想法
                </Badge>
              )}
              <Badge tone={status === '已读' ? 'teal' : status === '在读' ? 'primary' : 'neutral'}>
                阅读进度 {meta.readingProgress}% · {status}
              </Badge>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="关闭书籍详情"
          >
            <X size={18} />
          </button>
        </div>

        {/* 进度条 */}
        {meta.readingProgress > 0 && (
          <div className="mb-4">
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className={cx('h-full rounded-full', status === '已读' ? 'bg-teal' : 'bg-primary')}
                style={{ width: `${meta.readingProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* 划线/笔记内容 */}
        {item.summary && (
          <div className="mb-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-black text-gray-500">
              <Highlighter size={12} />
              笔记摘要
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50 p-4 text-[13px] leading-7 text-gray-700">
              <AutoLink text={item.summary} />
            </div>
          </div>
        )}

        {/* 热门划线 */}
        <BestBookmarksSection item={item} />

        {item.raw_content && item.raw_content !== item.summary && (
          <div className="mb-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-black text-gray-500">
              <BookOpen size={12} />
              原始划线内容
            </div>
            <div className="max-h-[300px] overflow-y-auto rounded-lg border border-gray-100 bg-white p-4 text-[13px] leading-7 text-gray-600">
              <AutoLink text={item.raw_content} />
            </div>
          </div>
        )}

        {/* 外链 — 始终显示，没有直接 URL 时用搜索 */}
        <a
          href={wereadBookUrl(item)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline"
        >
          在微信读书中{item.url && item.url !== WEREAD_FALLBACK_URL ? '查看' : '搜索'}
          <ExternalLink size={12} />
        </a>
        </Panel>
      </div>
    </>
  );
}

// ── 统计卡片 ──

export function StatCard({ icon: Icon, label, value, tone }: {
  icon: typeof BookOpen;
  label: string;
  value: string | number;
  tone: 'primary' | 'teal' | 'purple' | 'amber';
}) {
  const toneClass = {
    primary: 'bg-primary-light text-primary',
    teal: 'bg-teal-light text-teal',
    purple: 'bg-purple-light text-purple',
    amber: 'bg-amber-light text-amber',
  }[tone];
  return (
    <Panel className="flex items-center gap-3 p-3.5">
      <div className={cx('flex h-9 w-9 items-center justify-center rounded-sm', toneClass)}>
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[10px] font-bold text-gray-400">{label}</div>
        <div className="font-mono text-lg font-black text-gray-900">{value}</div>
      </div>
    </Panel>
  );
}

// ── 统计图表组件 ──

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

// ── Phase 2: 热门划线 / 阅读统计 / 书架对比 ──


/** 热门划线区域 — 嵌入 BookDetailPanel，按需加载 */
export function BestBookmarksSection({ item }: { item: ContentItem }) {
  const [data, setData] = useState<WeReadBestBookmarks | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  // 从 item.url 中提取 bookId
  const bookId = useMemo(() => {
    const url = item.url || '';
    const m = url.match(/bookId[=:](\w+)/) || url.match(/\/book\/(\d+)/) || url.match(/weread\.qq\.com\/.*?(\d{6,})/);
    return m ? m[1] : '';
  }, [item.url]);

  const handleFetch = useCallback(async () => {
    if (!bookId) {
      setError('无法获取书籍 ID');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await integrationsApi.getWeReadBookmarks(bookId, 10);
      setData(result);
      setExpanded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取热门划线失败');
    } finally {
      setLoading(false);
    }
  }, [bookId]);

  if (!bookId) return null;

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={expanded ? undefined : handleFetch}
        disabled={loading}
        className={cx(
          'flex w-full items-center justify-between rounded-lg border px-3 py-2 text-xs font-bold transition',
          expanded
            ? 'border-gray-200 bg-gray-50 text-gray-600'
            : 'border-primary-border bg-primary-light text-primary hover:bg-primary-light/80',
        )}
      >
        <span className="flex items-center gap-1.5">
          <BookMarked size={12} />
          {expanded ? '热门划线' : '查看热门划线'}
          {data && data.total > 0 && (
            <span className="rounded-full bg-white px-1.5 py-0.5 text-[9px] text-gray-500">
              {data.total} 条
            </span>
          )}
        </span>
        {loading ? (
          <Loader2 size={12} className="animate-spin" />
        ) : expanded ? null : (
          <ChevronDown size={12} />
        )}
      </button>

      {error && (
        <p className="mt-1.5 text-[11px] text-red">{error}</p>
      )}

      {expanded && data && data.bookmarks.length > 0 && (
        <div className="mt-2 max-h-[280px] space-y-2 overflow-y-auto rounded-lg border border-gray-100 bg-white p-3">
          {data.bookmarks.map((bm, i) => (
            <div key={i} className="border-l-2 border-primary-border pl-3">
              {bm.chapter_name && (
                <div className="mb-0.5 text-[10px] font-bold text-gray-400">
                  {bm.chapter_name}
                </div>
              )}
              <p className="text-[12px] leading-6 text-gray-700">{bm.text}</p>
            </div>
          ))}
        </div>
      )}

      {expanded && data && data.bookmarks.length === 0 && (
        <p className="mt-2 text-[11px] text-gray-400">暂无热门划线数据</p>
      )}
    </div>
  );
}


/** 阅读统计卡片 — 按需加载阅读时长、天数等 */
export function ReadingStatsCard({ initialData }: { initialData?: WeReadReadData | null }) {
  const [data, setData] = useState<WeReadReadData | null>(initialData ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readType, setReadType] = useState<'all' | 'week' | 'month' | 'year'>('all');

  const handleFetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await integrationsApi.getWeReadReadData(readType, true);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取阅读统计失败');
    } finally {
      setLoading(false);
    }
  }, [readType]);

  // 切换周期时自动刷新（已有数据时）
  useEffect(() => {
    if (data) handleFetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readType]);

  // 页面预取数据到达时自动填充
  useEffect(() => {
    if (initialData) setData(initialData);
  }, [initialData]);

  // 格式化阅读时长（秒 → 小时分钟）
  const formatTime = (seconds: number) => {
    if (!seconds || seconds <= 0) return '0分钟';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}小时${minutes > 0 ? `${minutes}分` : ''}`;
    return `${minutes}分钟`;
  };

  const typeLabels: Record<string, string> = {
    all: '总计', week: '本周', month: '本月', year: '本年',
  };

  // 从 read_longest 提取读书最久的书名
  const longestBookTitle = useMemo(() => {
    if (!data?.read_longest?.length) return '';
    const first = data.read_longest[0] as Record<string, unknown>;
    const book = (first.book || first) as Record<string, unknown>;
    return String(book.title || '');
  }, [data]);

  return (
    <Surface icon={Timer} title="阅读时长统计" hint="来自微信读书阅读数据">
      <div className="flex items-center gap-2">
        {/* 周期切换 */}
        <div className="flex items-center gap-1">
          {(['all', 'week', 'month', 'year'] as const).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => { setReadType(t); }}
              className={cx(
                'rounded-md px-2 py-1 text-[10px] font-bold transition',
                readType === t
                  ? 'bg-primary-light text-primary'
                  : 'bg-gray-100 text-gray-500 hover:text-gray-700',
              )}
            >
              {typeLabels[t]}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={handleFetch}
          disabled={loading}
          className="flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-[10px] font-bold text-gray-600 hover:text-primary hover:border-primary-border disabled:opacity-50"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
          {data ? '刷新' : '获取'}
        </button>
      </div>

      {error && (
        <p className="mt-2 text-[11px] text-red">{error}</p>
      )}

      {data && (
        <div className="mt-3 space-y-2.5">
          {/* 核心指标 */}
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <div className="rounded-lg border border-gray-200 bg-white p-2.5">
              <div className="flex items-center gap-1 text-[9px] font-bold text-gray-400">
                <Timer size={9} />
                阅读时长
              </div>
              <div className="mt-0.5 font-mono text-base font-black text-gray-900">
                {formatTime(data.total_read_time)}
              </div>
              {data.compare !== 0 && (
                <div className={cx('text-[9px] font-bold', data.compare > 0 ? 'text-teal' : 'text-red')}>
                  {data.compare > 0 ? '↑' : '↓'}{Math.abs(Math.round(data.compare * 100))}% 环比
                </div>
              )}
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-2.5">
              <div className="flex items-center gap-1 text-[9px] font-bold text-gray-400">
                <CalendarDays size={9} />
                阅读天数
              </div>
              <div className="mt-0.5 font-mono text-base font-black text-gray-900">
                {data.read_days}
                <span className="ml-0.5 text-[10px] font-normal text-gray-400">天</span>
              </div>
              <div className="text-[9px] text-gray-400">
                日均 {formatTime(data.day_average_read_time)}
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-2.5">
              <div className="flex items-center gap-1 text-[9px] font-bold text-gray-400">
                <Users size={9} />
                朋友排名
              </div>
              <div className="mt-0.5 text-xs font-black text-gray-900">
                {data.rank_text || '暂无排名'}
              </div>
            </div>
          </div>

          {/* 偏好分析 */}
          <div className="grid grid-cols-2 gap-2.5">
            {data.prefer_category_word && (
              <div className="rounded-lg border border-gray-200 bg-white p-2.5">
                <div className="text-[9px] font-bold text-gray-400">偏好分类</div>
                <div className="mt-0.5 text-xs font-bold text-primary">
                  {data.prefer_category_word}
                </div>
              </div>
            )}
            {data.prefer_author && (
              <div className="rounded-lg border border-gray-200 bg-white p-2.5">
                <div className="text-[9px] font-bold text-gray-400">偏好作者</div>
                <div className="mt-0.5 text-xs font-bold text-teal">
                  {data.prefer_author}
                  {data.author_count > 0 && (
                    <span className="ml-1 text-[9px] text-gray-400">（{data.author_count}位）</span>
                  )}
                </div>
              </div>
            )}
            {data.prefer_time_word && (
              <div className="rounded-lg border border-gray-200 bg-white p-2.5">
                <div className="text-[9px] font-bold text-gray-400">偏好阅读时段</div>
                <div className="mt-0.5 text-xs font-bold text-purple">
                  {data.prefer_time_word}
                </div>
              </div>
            )}
            {longestBookTitle && (
              <div className="rounded-lg border border-gray-200 bg-white p-2.5">
                <div className="text-[9px] font-bold text-gray-400">读书最久</div>
                <div className="mt-0.5 line-clamp-1 text-xs font-bold text-amber" title={longestBookTitle}>
                  {longestBookTitle}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {!data && !error && !loading && (
        <p className="mt-2 text-[11px] text-gray-400">
          正在从微信读书拉取阅读统计数据…
        </p>
      )}
    </Surface>
  );
}


/** 书架对比 — 拉取完整书架与笔记本对比 */
export function ShelfComparison({ notebookCount, onShelfData, initialData }: {
  notebookCount: number;
  onShelfData?: (data: WeReadShelfSync) => void;
  initialData?: WeReadShelfSync | null;
}) {
  const [data, setData] = useState<WeReadShelfSync | null>(initialData ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await integrationsApi.getWeReadShelf(true);
      setData(result);
      onShelfData?.(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取书架失败');
    } finally {
      setLoading(false);
    }
  }, [onShelfData]);

  if (!data && !loading && !error) {
    return (
      <Surface icon={Layers} title="书架 vs 笔记本对比" hint="加载中…">
        <div className="flex items-center gap-2 py-4">
          <Loader2 size={16} className="animate-spin text-primary" />
          <span className="text-xs text-gray-500">正在拉取完整书架…</span>
        </div>
      </Surface>
    );
  }

  if (loading) {
    return (
      <Surface icon={Layers} title="书架 vs 笔记本对比" hint="加载中…">
        <div className="flex items-center gap-2 py-4">
          <Loader2 size={16} className="animate-spin text-primary" />
          <span className="text-xs text-gray-500">正在拉取完整书架…</span>
        </div>
      </Surface>
    );
  }

  if (error || !data) {
    return (
      <Surface icon={Layers} title="书架 vs 笔记本对比" hint="获取失败">
        <p className="text-[11px] text-red">{error}</p>
        <button
          type="button"
          onClick={handleFetch}
          className="mt-2 rounded-md border border-gray-200 px-2.5 py-1 text-[10px] font-bold text-gray-600 hover:text-primary"
        >
          重试
        </button>
      </Surface>
    );
  }

  const noNotesPct = data.total > 0 ? Math.round((data.no_notes / data.total) * 100) : 0;
  const finishedPct = data.total > 0 ? Math.round((data.finished_count / data.total) * 100) : 0;
  const hasNotesPct = data.total > 0 ? Math.round((data.has_notes / data.total) * 100) : 0;

  return (
    <Surface icon={Layers} title="书架 vs 笔记本对比" hint={`${data.total} 本 vs ${notebookCount} 本有笔记`}>
      {/* 刷新按钮 */}
      <div className="mb-3 flex justify-end">
        <button
          type="button"
          onClick={handleFetch}
          className="flex items-center gap-1 rounded-md border border-gray-200 px-2 py-0.5 text-[10px] font-bold text-gray-500 hover:text-primary"
        >
          <RefreshCw size={9} />
          刷新
        </button>
      </div>

      {/* 对比指标 */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-2.5">
          <div className="text-[9px] font-bold text-gray-400">书架总数</div>
          <div className="mt-0.5 font-mono text-lg font-black text-gray-900">{data.total}</div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-2.5">
          <div className="text-[9px] font-bold text-gray-400">有笔记</div>
          <div className="mt-0.5 font-mono text-lg font-black text-teal">{data.has_notes}</div>
          <div className="text-[9px] text-gray-400">{hasNotesPct}%</div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-2.5">
          <div className="text-[9px] font-bold text-gray-400">无笔记</div>
          <div className="mt-0.5 font-mono text-lg font-black text-amber">{data.no_notes}</div>
          <div className="text-[9px] text-gray-400">{noNotesPct}%</div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-2.5">
          <div className="flex items-center gap-0.5 text-[9px] font-bold text-gray-400">
            <BookMarked size={9} />
            已读完
          </div>
          <div className="mt-0.5 font-mono text-lg font-black text-purple">{data.finished_count}</div>
          <div className="text-[9px] text-gray-400">{finishedPct}%</div>
        </div>
      </div>

      {/* 分类分布 Top 10 */}
      {data.categories.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-[10px] font-bold text-gray-500">书架分类分布（Top 10）</div>
          <div className="flex flex-wrap gap-1.5">
            {data.categories.slice(0, 10).map(([cat, count]) => {
              const pct = data.total > 0 ? Math.round((count / data.total) * 100) : 0;
              return (
                <span
                  key={cat}
                  className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-bold text-gray-600"
                  title={`${cat}: ${count}本 (${pct}%)`}
                >
                  {cat}
                  <span className="font-mono text-gray-400">{count}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* 囤书分析提示 */}
      {noNotesPct >= 60 && (
        <div className="mt-3 rounded-lg border border-amber-border bg-amber-light px-3 py-2 text-[11px] text-amber">
          书架中 {noNotesPct}% 的书没有笔记，可能存在囤书习惯。考虑集中阅读已有书籍，或清理不再需要的书。
        </div>
      )}
    </Surface>
  );
}
