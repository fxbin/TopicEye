/**
 * 微信读书数据拉取组件。
 *
 * 从 _shared.tsx 拆出：BestBookmarksSection, ReadingStatsCard, ShelfComparison
 */

'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw,
  ChevronDown,
  Loader2,
  BookMarked,
  Timer,
  CalendarDays,
  Users,
  Layers,
} from 'lucide-react';
import { integrationsApi } from '@/lib/api';
import { Surface, cx } from '@/components/ui';
import type {
  ContentItem,
  WeReadBestBookmarks,
  WeReadReadData,
  WeReadShelfSync,
} from '@/types';

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
