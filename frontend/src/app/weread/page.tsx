'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BookOpen,
  ExternalLink,
  RefreshCw,
  Search,
  ChevronDown,
  ChevronUp,
  Highlighter,
  MessageSquare,
  BarChart3,
  Library,
  X,
  PieChart,
  TrendingUp,
  Users,
  Sparkles,
  Star,
  Loader2,
} from 'lucide-react';
import { contentsApi, integrationsApi } from '@/lib/api';
import { Panel, Badge, Surface, cx } from '@/components/ui';
import { Pagination } from '@/components/Pagination';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import type { ContentItem, WeReadSearchBook } from '@/types';
import { AutoLink } from '@/components/AutoLink';

const SHELF_PAGE_SIZE = 200; // 书架视图一次拉满，客户端排序/分组

// ── 从 summary 解析 WeRead 结构化数据 ──

interface WeReadMeta {
  noteCount: number;
  reviewCount: number;
  readingProgress: number; // 0-100
}

function parseWeReadMeta(item: ContentItem): WeReadMeta {
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

type SortKey = 'published_at' | 'title' | 'noteCount' | 'reviewCount' | 'readingProgress';
type SortOrder = 'asc' | 'desc';
type GroupKey = 'none' | 'author' | 'status';

const SORT_OPTIONS: Array<{ value: SortKey; label: string }> = [
  { value: 'published_at', label: '最近笔记' },
  { value: 'title', label: '书名' },
  { value: 'noteCount', label: '划线数' },
  { value: 'reviewCount', label: '想法数' },
  { value: 'readingProgress', label: '阅读进度' },
];

const GROUP_OPTIONS: Array<{ value: GroupKey; label: string }> = [
  { value: 'none', label: '不分组' },
  { value: 'author', label: '按作者' },
  { value: 'status', label: '按阅读状态' },
];

function getReadingStatus(progress: number): '未读' | '在读' | '已读' {
  if (progress >= 90) return '已读';
  if (progress > 0) return '在读';
  return '未读';
}

// ── 微信读书网页版跳转 URL ──

const WEREAD_FALLBACK_URL = 'https://weread.qq.com/r/weread-skills';

/** 构造微信读书网页版搜索 URL，用于书架中没有直接 deepLink 的书 */
function wereadSearchUrl(title: string): string {
  return `https://weread.qq.com/#search/${encodeURIComponent(title)}`;
}

/** 获取书架书籍的微信读书跳转 URL：有真实 URL 用 URL，否则用搜索 URL */
function wereadBookUrl(item: ContentItem): string {
  if (item.url && item.url !== WEREAD_FALLBACK_URL) {
    return item.url;
  }
  return wereadSearchUrl(item.title);
}

// ── 书架卡片 ──

function BookCard({ item, meta, onExpand }: {
  item: ContentItem;
  meta: WeReadMeta;
  onExpand: () => void;
}) {
  const status = getReadingStatus(meta.readingProgress);
  const statusColor = status === '已读' ? 'teal' : status === '在读' ? 'primary' : 'neutral';

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
    </div>
  );
}

// ── 发现模式搜索结果卡片 ──

function DiscoverBookCard({ book, inShelf }: {
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

function BookDetailPanel({ item, meta, onClose }: {
  item: ContentItem;
  meta: WeReadMeta;
  onClose: () => void;
}) {
  const status = getReadingStatus(meta.readingProgress);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <Panel
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
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
            <h2 className="mb-1 break-words text-lg font-black text-gray-900">{item.title}</h2>
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
  );
}

// ── 统计卡片 ──

function StatCard({ icon: Icon, label, value, tone }: {
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

const CHART_COLORS = ['#FF6B35', '#00C9A7', '#D97706', '#2563EB', '#8B5CF6', '#E11D48', '#059669', '#06B6D4', '#64748B', '#EC4899'];

/** 环形图：阅读状态分布 */
function StatusDonut({ items }: { items: Array<{ meta: WeReadMeta }> }) {
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
function TopNBars({ data, unit }: {
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
function ProgressHistogram({ items }: { items: Array<{ meta: WeReadMeta }> }) {
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

// ── 主页面 ──

export default function WeReadPage() {
  const [page, setPage] = useState(1);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('published_at');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [groupKey, setGroupKey] = useState<GroupKey>('none');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const [showCharts, setShowCharts] = useState(false);

  // ── 发现模式（全网搜书）──
  const [searchMode, setSearchMode] = useState<'shelf' | 'discover'>('shelf');
  const [discoverResults, setDiscoverResults] = useState<WeReadSearchBook[]>([]);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [discoverKeyword, setDiscoverKeyword] = useState('');
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data, loading, error, refetch } = useFetch(
    () => contentsApi.list({
      platform: '微信读书',
      page: 1,
      page_size: SHELF_PAGE_SIZE,
      sort_by: 'published_at',
      sort_order: 'desc',
    }),
    [],
  );

  const allItems = data?.items ?? [];
  const total = data?.total ?? 0;

  // 解析所有 items 的 WeRead 元数据
  const itemsWithMeta = useMemo(() => {
    return allItems.map((item) => ({
      item,
      meta: parseWeReadMeta(item),
    }));
  }, [allItems]);

  // 书架中书名的归一化集合，用于发现模式标记"已在书架"
  const shelfTitleSet = useMemo(() => {
    const s = new Set<string>();
    for (const { item } of itemsWithMeta) {
      const normalized = (item.title || '').trim().toLowerCase();
      if (normalized) s.add(normalized);
    }
    return s;
  }, [itemsWithMeta]);

  // 发现模式：防抖搜索微信读书全网书库
  useEffect(() => {
    if (searchMode !== 'discover') return;
    const keyword = discoverKeyword.trim();
    if (!keyword) {
      setDiscoverResults([]);
      setDiscoverError(null);
      return;
    }
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(async () => {
      setDiscoverLoading(true);
      setDiscoverError(null);
      try {
        const result = await integrationsApi.searchWeRead(keyword, 20);
        setDiscoverResults(result.books);
      } catch (err) {
        setDiscoverError(err instanceof Error ? err.message : '搜索失败');
        setDiscoverResults([]);
      } finally {
        setDiscoverLoading(false);
      }
    }, 500);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [discoverKeyword, searchMode]);

  // 搜索过滤
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return itemsWithMeta;
    const q = searchQuery.trim().toLowerCase();
    return itemsWithMeta.filter(({ item }) =>
      item.title.toLowerCase().includes(q) ||
      (item.author || '').toLowerCase().includes(q) ||
      (item.summary || '').toLowerCase().includes(q),
    );
  }, [itemsWithMeta, searchQuery]);

  // 排序
  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortOrder === 'desc' ? -1 : 1;
    arr.sort((a, b) => {
      let cmp = 0;
        switch (sortKey) {
          case 'published_at':
            cmp = (a.item.published_at || '').localeCompare(b.item.published_at || '');
            break;
        case 'title':
          cmp = a.item.title.localeCompare(b.item.title, 'zh-CN');
          break;
        case 'noteCount':
          cmp = a.meta.noteCount - b.meta.noteCount;
          break;
        case 'reviewCount':
          cmp = a.meta.reviewCount - b.meta.reviewCount;
          break;
        case 'readingProgress':
          cmp = a.meta.readingProgress - b.meta.readingProgress;
          break;
      }
      return cmp * dir;
    });
    return arr;
  }, [filtered, sortKey, sortOrder]);

  // 分组
  const grouped = useMemo(() => {
    if (groupKey === 'none') {
      return [{ label: '', items: sorted }];
    }
    const groups = new Map<string, typeof sorted>();
    for (const entry of sorted) {
      let key: string;
      if (groupKey === 'author') {
        key = entry.item.author || '未知作者';
      } else {
        key = getReadingStatus(entry.meta.readingProgress);
      }
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(entry);
    }
    // 分组排序：作者按字母序，状态按 已读 > 在读 > 未读
    const statusOrder = ['已读', '在读', '未读'];
    return Array.from(groups.entries())
      .map(([label, items]) => ({ label, items }))
      .sort((a, b) => {
        if (groupKey === 'status') {
          return statusOrder.indexOf(a.label) - statusOrder.indexOf(b.label);
        }
        return a.label.localeCompare(b.label, 'zh-CN');
      });
  }, [sorted, groupKey]);

  // 统计数据
  const stats = useMemo(() => {
    const totalNotes = itemsWithMeta.reduce((s, e) => s + e.meta.noteCount, 0);
    const totalReviews = itemsWithMeta.reduce((s, e) => s + e.meta.reviewCount, 0);
    const avgProgress = itemsWithMeta.length > 0
      ? Math.round(itemsWithMeta.reduce((s, e) => s + e.meta.readingProgress, 0) / itemsWithMeta.length)
      : 0;
    return { totalBooks: itemsWithMeta.length, totalNotes, totalReviews, avgProgress };
  }, [itemsWithMeta]);

  // 图表数据
  const chartData = useMemo(() => {
    // Top 10 划线书籍
    const topNotes = [...itemsWithMeta]
      .filter((e) => e.meta.noteCount > 0)
      .sort((a, b) => b.meta.noteCount - a.meta.noteCount)
      .slice(0, 10)
      .map((e) => ({
        label: e.item.title.length > 12 ? e.item.title.slice(0, 12) + '…' : e.item.title,
        value: e.meta.noteCount,
        sub: `${e.meta.reviewCount}想法`,
      }));

    // Top 10 活跃作者
    const authorMap = new Map<string, { books: number; notes: number; reviews: number }>();
    for (const { item, meta } of itemsWithMeta) {
      const author = item.author || '未知作者';
      const entry = authorMap.get(author) || { books: 0, notes: 0, reviews: 0 };
      entry.books++;
      entry.notes += meta.noteCount;
      entry.reviews += meta.reviewCount;
      authorMap.set(author, entry);
    }
    const topAuthors = Array.from(authorMap.entries())
      .map(([author, data]) => ({
        label: author.length > 12 ? author.slice(0, 12) + '…' : author,
        value: data.notes + data.reviews,
        sub: `${data.books}本`,
      }))
      .filter((d) => d.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);

    return { topNotes, topAuthors };
  }, [itemsWithMeta]);

  // 分页（客户端）
  const PAGE_VIEW = 60;
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_VIEW));
  const currentPage = Math.min(page, totalPages);
  const pagedGrouped = useMemo(() => {
    if (groupKey !== 'none') return grouped; // 分组模式不分页
    const start = (currentPage - 1) * PAGE_VIEW;
    return [{ label: '', items: sorted.slice(start, start + PAGE_VIEW) }];
  }, [grouped, sorted, currentPage, groupKey]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const result = await integrationsApi.syncWeRead();
      setSyncMsg(`同步完成：新 ${result.new} 条，重复 ${result.duplicates} 条，共获取 ${result.fetched} 条`);
      setPage(1);
      refetch();
    } catch (err) {
      setSyncMsg(err instanceof Error ? err.message : '同步失败，请先在个人中心配置微信读书 API Key');
    } finally {
      setSyncing(false);
    }
  };

  const toggleSortOrder = useCallback(() => {
    setSortOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'));
  }, []);

  const expandedEntry = useMemo(() => {
    if (expandedId === null) return null;
    return itemsWithMeta.find(({ item }) => item.id === expandedId) ?? null;
  }, [expandedId, itemsWithMeta]);

  if (loading && allItems.length === 0) return <LoadingState />;
  if (error && allItems.length === 0) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-4 p-4">
        {/* 头部 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Library size={20} className="text-primary" />
            <h1 className="text-lg font-black text-gray-900">微信读书书架</h1>
            {total > 0 && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-bold text-gray-500">
                {total} 本
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className={cx(
              'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-bold transition',
              syncing
                ? 'border-gray-200 text-gray-300'
                : 'border-gray-200 text-gray-600 hover:text-primary hover:border-primary-border',
            )}
          >
            <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
            {syncing ? '同步中…' : '同步素材'}
          </button>
        </div>

        {/* 同步反馈 */}
        {syncMsg && (
          <div
            className={cx(
              'rounded-lg border px-3 py-2 text-xs',
              syncMsg.startsWith('同步完成')
                ? 'border-teal-border bg-teal-light text-teal'
                : 'border-red-light bg-red-light text-red',
            )}
          >
            {syncMsg}
          </div>
        )}

        {/* 空状态 */}
        {allItems.length === 0 && !loading && searchMode === 'shelf' && (
          <Panel className="p-8 text-center">
            <BookOpen size={32} className="mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-bold text-gray-500">还没有微信读书素材</p>
            <p className="mt-1 text-xs text-gray-400">
              请先在
              <a href="/profile" className="mx-0.5 text-primary hover:underline">个人中心</a>
              配置微信读书 API Key，然后点击右上角「同步素材」。
            </p>
            <p className="mt-2 text-xs text-gray-400">
              或切换到
              <button
                type="button"
                onClick={() => setSearchMode('discover')}
                className="mx-0.5 text-primary hover:underline font-bold"
              >发现</button>
              模式搜索微信读书书库。
            </p>
          </Panel>
        )}

        {/* 搜索模式切换 */}
        <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-1">
          <button
            type="button"
            onClick={() => setSearchMode('shelf')}
            className={cx(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition',
              searchMode === 'shelf'
                ? 'bg-primary-light text-primary'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Library size={13} />
            书架
          </button>
          <button
            type="button"
            onClick={() => setSearchMode('discover')}
            className={cx(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition',
              searchMode === 'discover'
                ? 'bg-primary-light text-primary'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Sparkles size={13} />
            发现
          </button>
        </div>

        {searchMode === 'shelf' && allItems.length > 0 && (
          <>
            {/* 统计卡片 */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard icon={Library} label="书籍总数" value={stats.totalBooks} tone="primary" />
              <StatCard icon={Highlighter} label="划线总数" value={stats.totalNotes} tone="teal" />
              <StatCard icon={MessageSquare} label="想法总数" value={stats.totalReviews} tone="purple" />
              <StatCard icon={BarChart3} label="平均进度" value={`${stats.avgProgress}%`} tone="amber" />
            </div>

            {/* 图表展开/收起按钮 */}
            <button
              type="button"
              onClick={() => setShowCharts((v) => !v)}
              className={cx(
                'flex w-full items-center justify-center gap-1.5 rounded-lg border py-2 text-xs font-bold transition',
                showCharts
                  ? 'border-primary-border bg-primary-light text-primary'
                  : 'border-gray-200 bg-white text-gray-500 hover:text-primary hover:border-primary-border',
              )}
            >
              <PieChart size={14} />
              {showCharts ? '收起统计图表' : '展开统计图表'}
              {showCharts ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>

            {/* 统计图表区域 */}
            {showCharts && (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Surface icon={PieChart} title="阅读状态分布" hint="已读 / 在读 / 未读">
                  <StatusDonut items={itemsWithMeta} />
                </Surface>
                <Surface icon={TrendingUp} title="阅读进度分布" hint="按进度区间统计">
                  <ProgressHistogram items={itemsWithMeta} />
                </Surface>
                <Surface icon={Highlighter} title="划线最多 Top 10" hint="按划线数量排序">
                  <TopNBars data={chartData.topNotes} unit="条" />
                </Surface>
                <Surface icon={Users} title="最活跃作者 Top 10" hint="按划线+想法总数排序">
                  <TopNBars data={chartData.topAuthors} unit="条" />
                </Surface>
              </div>
            )}

            {/* 工具栏 */}
            <Panel className="flex flex-wrap items-center gap-3 p-3">
              {/* 搜索 */}
              <div className="relative min-w-[180px] flex-1">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
                  placeholder="搜索书名 / 作者 / 笔记…"
                  className="w-full rounded-md border border-gray-200 py-1.5 pl-9 pr-3 text-xs text-gray-700 placeholder:text-gray-400 focus:border-primary-border focus:outline-none"
                />
              </div>

              {/* 排序 */}
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-bold text-gray-400">排序</span>
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                  className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs font-bold text-gray-700 focus:border-primary-border focus:outline-none"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={toggleSortOrder}
                  className="flex h-7 w-7 items-center justify-center rounded-md border border-gray-200 text-gray-500 hover:text-primary"
                  title={sortOrder === 'desc' ? '降序' : '升序'}
                >
                  {sortOrder === 'desc' ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
              </div>

              {/* 分组 */}
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-bold text-gray-400">分组</span>
                <select
                  value={groupKey}
                  onChange={(e) => { setGroupKey(e.target.value as GroupKey); setPage(1); }}
                  className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs font-bold text-gray-700 focus:border-primary-border focus:outline-none"
                >
                  {GROUP_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              {/* 筛选结果计数 */}
              {searchQuery && (
                <span className="text-[11px] text-gray-400">
                  筛选到 {sorted.length} 本
                </span>
              )}
            </Panel>

            {/* 书架网格 */}
            {pagedGrouped.map((group) => (
              <div key={group.label || 'all'} className="space-y-3">
                {group.label && (
                  <div className="flex items-center gap-2 border-b border-gray-100 pb-2">
                    <span className="text-sm font-black text-gray-700">{group.label}</span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-500">
                      {group.items.length} 本
                    </span>
                  </div>
                )}
                {group.items.length === 0 ? (
                  <p className="py-8 text-center text-xs text-gray-400">无匹配书籍</p>
                ) : (
                  <div className="grid grid-cols-3 gap-4 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
                    {group.items.map(({ item, meta }) => (
                      <BookCard
                        key={item.id}
                        item={item}
                        meta={meta}
                        onExpand={() => setExpandedId(item.id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* 分页（仅非分组模式） */}
            {groupKey === 'none' && totalPages > 1 && (
              <Pagination
                page={currentPage}
                totalPages={totalPages}
                onPage={setPage}
                summary={<span className="text-xs font-bold text-gray-500">{currentPage} / {totalPages}</span>}
              />
            )}
          </>
        )}

        {/* ── 发现模式：全网搜书 ── */}
        {searchMode === 'discover' && (
          <>
            {/* 搜索框 */}
            <Panel className="p-3">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={discoverKeyword}
                  onChange={(e) => setDiscoverKeyword(e.target.value)}
                  placeholder="搜索微信读书书库：书名 / 作者 / 关键词…"
                  className="w-full rounded-md border border-gray-200 py-2 pl-9 pr-9 text-sm text-gray-700 placeholder:text-gray-400 focus:border-primary-border focus:outline-none"
                  autoFocus
                />
                {discoverKeyword && (
                  <button
                    type="button"
                    onClick={() => setDiscoverKeyword('')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
              <p className="mt-2 text-[11px] text-gray-400">
                搜索微信读书全网书库，发现书架之外的好书。已在书架的书会标记「书架中」。
              </p>
            </Panel>

            {/* 搜索中 */}
            {discoverLoading && (
              <Panel className="flex items-center justify-center gap-2 p-12">
                <Loader2 size={20} className="animate-spin text-primary" />
                <span className="text-sm font-bold text-gray-500">正在搜索微信读书书库…</span>
              </Panel>
            )}

            {/* 搜索错误 */}
            {discoverError && !discoverLoading && (
              <Panel className="p-6 text-center">
                <p className="text-sm font-bold text-red">{discoverError}</p>
                <p className="mt-1 text-xs text-gray-400">请确保已配置微信读书 API Key</p>
              </Panel>
            )}

            {/* 搜索结果 */}
            {!discoverLoading && !discoverError && discoverResults.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-black text-gray-700">搜索结果</span>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-500">
                    {discoverResults.length} 本
                  </span>
                  {discoverKeyword && (
                    <span className="text-[11px] text-gray-400">
                      关键词「{discoverKeyword}」
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-4 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
                  {discoverResults.map((book) => (
                    <DiscoverBookCard
                      key={book.bookId}
                      book={book}
                      inShelf={shelfTitleSet.has(book.title.trim().toLowerCase())}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* 空搜索提示 */}
            {!discoverLoading && !discoverError && discoverResults.length === 0 && !discoverKeyword.trim() && (
              <Panel className="p-12 text-center">
                <Sparkles size={32} className="mx-auto mb-3 text-gray-300" />
                <p className="text-sm font-bold text-gray-500">搜索微信读书全网书库</p>
                <p className="mt-1 text-xs text-gray-400">
                  输入书名、作者或关键词，发现书架之外的好书。
                </p>
              </Panel>
            )}

            {/* 无结果 */}
            {!discoverLoading && !discoverError && discoverResults.length === 0 && discoverKeyword.trim() && (
              <Panel className="p-12 text-center">
                <Search size={32} className="mx-auto mb-3 text-gray-300" />
                <p className="text-sm font-bold text-gray-500">未找到相关书籍</p>
                <p className="mt-1 text-xs text-gray-400">
                  试试其他关键词？
                </p>
              </Panel>
            )}
          </>
        )}
      </div>

      {/* 划线详情弹窗 */}
      {expandedEntry && (
        <BookDetailPanel
          item={expandedEntry.item}
          meta={expandedEntry.meta}
          onClose={() => setExpandedId(null)}
        />
      )}
    </div>
  );
}
