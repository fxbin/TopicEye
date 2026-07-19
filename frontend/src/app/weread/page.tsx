'use client';

import React, { useCallback, useMemo, useState } from 'react';
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
} from 'lucide-react';
import { contentsApi, integrationsApi } from '@/lib/api';
import { Panel, Badge, cx } from '@/components/ui';
import { Pagination } from '@/components/Pagination';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import type { ContentItem } from '@/types';
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

type SortKey = 'created_at' | 'title' | 'noteCount' | 'reviewCount' | 'readingProgress';
type SortOrder = 'asc' | 'desc';
type GroupKey = 'none' | 'author' | 'status';

const SORT_OPTIONS: Array<{ value: SortKey; label: string }> = [
  { value: 'created_at', label: '同步时间' },
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

// ── 书架卡片 ──

function BookCard({ item, meta, onExpand }: {
  item: ContentItem;
  meta: WeReadMeta;
  onExpand: () => void;
}) {
  const status = getReadingStatus(meta.readingProgress);
  const statusColor = status === '已读' ? 'teal' : status === '在读' ? 'primary' : 'neutral';

  return (
    <button
      type="button"
      onClick={onExpand}
      className="group flex flex-col items-center text-center transition hover:-translate-y-1"
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
    </button>
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

        {/* 外链 */}
        {item.url && item.url !== 'https://weread.qq.com/r/weread-skills' && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline"
          >
            在微信读书中查看
            <ExternalLink size={12} />
          </a>
        )}
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

// ── 主页面 ──

export default function WeReadPage() {
  const [page, setPage] = useState(1);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [groupKey, setGroupKey] = useState<GroupKey>('none');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data, loading, error, refetch } = useFetch(
    () => contentsApi.list({
      platform: '微信读书',
      page: 1,
      page_size: SHELF_PAGE_SIZE,
      sort_by: 'created_at',
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
        case 'created_at':
          cmp = (a.item.created_at || '').localeCompare(b.item.created_at || '');
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
        {allItems.length === 0 && !loading && (
          <Panel className="p-8 text-center">
            <BookOpen size={32} className="mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-bold text-gray-500">还没有微信读书素材</p>
            <p className="mt-1 text-xs text-gray-400">
              请先在
              <a href="/profile" className="mx-0.5 text-primary hover:underline">个人中心</a>
              配置微信读书 API Key，然后点击右上角「同步素材」。
            </p>
          </Panel>
        )}

        {allItems.length > 0 && (
          <>
            {/* 统计卡片 */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard icon={Library} label="书籍总数" value={stats.totalBooks} tone="primary" />
              <StatCard icon={Highlighter} label="划线总数" value={stats.totalNotes} tone="teal" />
              <StatCard icon={MessageSquare} label="想法总数" value={stats.totalReviews} tone="purple" />
              <StatCard icon={BarChart3} label="平均进度" value={`${stats.avgProgress}%`} tone="amber" />
            </div>

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
