'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BookOpen,
  RefreshCw,
  Library,
  BarChart3,
  Sparkles,
} from 'lucide-react';
import { contentsApi, integrationsApi } from '@/lib/api';
import { Panel, cx } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import type {
  WeReadSearchBook,
  WeReadShelfSync,
  WeReadReadData,
} from '@/types';
import {
  SHELF_PAGE_SIZE,
  parseWeReadMeta,
  getReadingStatus,
  BookDetailPanel,
} from './_shared';
import type {
  SortKey,
  SortOrder,
  GroupKey,
} from './_shared';
import {
  ShelfTab,
  StatsTab,
  DiscoverTab,
} from './_tabs';

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

  // ── 页面进入时自动预取统计/书架数据（后台静默，不阻塞书架列表）──
  const [autoReadData, setAutoReadData] = useState<WeReadReadData | null>(null);
  const [autoShelfData, setAutoShelfData] = useState<WeReadShelfSync | null>(null);
  useEffect(() => {
    integrationsApi.getWeReadReadData('all', true).then(setAutoReadData).catch(() => {});
    integrationsApi.getWeReadShelf().then(setAutoShelfData).catch(() => {});
  }, []);

  // ── 书架分类映射（由 ShelfComparison 组件填充）──
  const [shelfCategoryMap, setShelfCategoryMap] = useState<Map<string, string>>(new Map());

  // 当选择「微信读书分类」分组但还未加载书架数据时，自动拉取
  const shelfCategoryLoaded = shelfCategoryMap.size > 0;
  useEffect(() => {
    if (groupKey === 'weread_category' && !shelfCategoryLoaded) {
      integrationsApi.getWeReadShelf().then(result => {
        const m = new Map<string, string>();
        for (const book of result.books) {
          const normalized = (book.title || '').trim().toLowerCase();
          if (normalized && book.category) {
            m.set(normalized, book.category);
          }
        }
        setShelfCategoryMap(m);
      }).catch(() => {});
    }
  }, [groupKey, shelfCategoryLoaded]);

  // ── Tab 切换: shelf / stats / discover ──
  const [activeTab, setActiveTab] = useState<'shelf' | 'stats' | 'discover'>('shelf');
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
    if (activeTab !== 'discover') return;
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
  }, [discoverKeyword, activeTab]);

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
      } else if (groupKey === 'status') {
        key = getReadingStatus(entry.meta.readingProgress);
      } else if (groupKey === 'weread_category') {
        const normalized = (entry.item.title || '').trim().toLowerCase();
        key = shelfCategoryMap.get(normalized) || '未分类';
      } else {
        key = '其他';
      }
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(entry);
    }
    // 分组排序
    const statusOrder = ['已读', '在读', '未读'];
    return Array.from(groups.entries())
      .map(([label, items]) => ({ label, items }))
      .sort((a, b) => {
        if (groupKey === 'status') {
          return statusOrder.indexOf(a.label) - statusOrder.indexOf(b.label);
        }
        if (groupKey === 'weread_category') {
          // 按数量降序
          return b.items.length - a.items.length;
        }
        return a.label.localeCompare(b.label, 'zh-CN');
      });
  }, [sorted, groupKey, shelfCategoryMap]);

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

  // 工具栏回调：搜索 / 分组切换时重置页码（保持原行为）
  const handleSearchChange = useCallback((q: string) => {
    setSearchQuery(q);
    setPage(1);
  }, []);
  const handleGroupKeyChange = useCallback((k: GroupKey) => {
    setGroupKey(k);
    setPage(1);
  }, []);

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
        {allItems.length === 0 && !loading && activeTab === 'shelf' && (
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
                onClick={() => setActiveTab('discover')}
                className="mx-0.5 text-primary hover:underline font-bold"
              >发现</button>
              tab 搜索微信读书书库。
            </p>
          </Panel>
        )}

        {/* Tab 切换 */}
        <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-1">
          <button
            type="button"
            onClick={() => setActiveTab('shelf')}
            className={cx(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition',
              activeTab === 'shelf'
                ? 'bg-primary-light text-primary'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Library size={13} />
            书架
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('stats')}
            className={cx(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition',
              activeTab === 'stats'
                ? 'bg-primary-light text-primary'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <BarChart3 size={13} />
            统计分析
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('discover')}
            className={cx(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition',
              activeTab === 'discover'
                ? 'bg-primary-light text-primary'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Sparkles size={13} />
            发现
          </button>
        </div>

        {activeTab === 'shelf' && allItems.length > 0 && (
          <ShelfTab
            stats={stats}
            searchQuery={searchQuery}
            onSearchChange={handleSearchChange}
            sortKey={sortKey}
            onSortKeyChange={setSortKey}
            sortOrder={sortOrder}
            onToggleSortOrder={toggleSortOrder}
            groupKey={groupKey}
            onGroupKeyChange={handleGroupKeyChange}
            pagedGrouped={pagedGrouped}
            sortedLength={sorted.length}
            totalPages={totalPages}
            currentPage={currentPage}
            onPageChange={setPage}
            onExpand={setExpandedId}
          />
        )}

        {/* ── 统计分析 Tab ── */}
        {activeTab === 'stats' && allItems.length > 0 && (
          <StatsTab
            stats={stats}
            itemsWithMeta={itemsWithMeta}
            showCharts={showCharts}
            onToggleCharts={() => setShowCharts((v) => !v)}
            chartData={chartData}
            initialReadData={autoReadData}
            initialShelfData={autoShelfData}
            onShelfData={(shelfData: WeReadShelfSync) => {
              const m = new Map<string, string>();
              for (const book of shelfData.books) {
                const normalized = (book.title || '').trim().toLowerCase();
                if (normalized && book.category) {
                  m.set(normalized, book.category);
                }
              }
              setShelfCategoryMap(m);
            }}
          />
        )}

        {/* ── 发现 Tab：全网搜书 ── */}
        {activeTab === 'discover' && (
          <DiscoverTab
            keyword={discoverKeyword}
            onKeywordChange={setDiscoverKeyword}
            loading={discoverLoading}
            error={discoverError}
            results={discoverResults}
            shelfTitleSet={shelfTitleSet}
          />
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
