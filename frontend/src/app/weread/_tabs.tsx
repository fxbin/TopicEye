/**
 * 微信读书书架页 Tab 组件（纯展示，props 驱动）。
 *
 * 从 app/weread/page.tsx 抽出：
 * - ShelfTab     书架视图（统计栏 + 工具栏 + 网格 + 分页）
 * - StatsTab    统计分析视图（统计卡片 + 图表 + 阅读时长 + 书架对比）
 * - DiscoverTab 发现视图（全网搜书）
 *
 * 三个 Tab 共享 _shared.tsx 中的常量、类型、辅助函数与子组件。
 * page.tsx 通过 import 使用这些 Tab，保持主体只含数据获取与状态编排。
 */

'use client';

import React from 'react';
import {
  Search,
  ChevronDown,
  ChevronUp,
  Library,
  Highlighter,
  MessageSquare,
  BarChart3,
  PieChart,
  TrendingUp,
  Filter,
  Grid3x3,
  Users,
  Zap,
  X,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { Panel, Surface, cx } from '@/components/ui';
import { Pagination } from '@/components/Pagination';
import type {
  ContentItem,
  WeReadSearchBook,
  WeReadShelfSync,
} from '@/types';
import {
  BookCard,
  DiscoverBookCard,
  StatCard,
  StatusDonut,
  TopNBars,
  ProgressHistogram,
  CompletionFunnel,
  NoteDensityScatter,
  WeeklyPulse,
  ReadingStatsCard,
  ShelfComparison,
  SORT_OPTIONS,
  GROUP_OPTIONS,
} from './_shared';
import type {
  WeReadMeta,
  SortKey,
  SortOrder,
  GroupKey,
} from './_shared';

// ── ShelfTab：书架视图 ──

export interface ShelfTabProps {
  stats: { totalBooks: number; totalNotes: number; totalReviews: number; avgProgress: number };
  searchQuery: string;
  onSearchChange: (q: string) => void;
  sortKey: SortKey;
  onSortKeyChange: (k: SortKey) => void;
  sortOrder: SortOrder;
  onToggleSortOrder: () => void;
  groupKey: GroupKey;
  onGroupKeyChange: (k: GroupKey) => void;
  pagedGrouped: Array<{ label: string; items: Array<{ item: ContentItem; meta: WeReadMeta }> }>;
  sortedLength: number;
  totalPages: number;
  currentPage: number;
  onPageChange: (updater: number | ((page: number) => number)) => void;
  onExpand: (id: number) => void;
}

export function ShelfTab({
  stats,
  searchQuery,
  onSearchChange,
  sortKey,
  onSortKeyChange,
  sortOrder,
  onToggleSortOrder,
  groupKey,
  onGroupKeyChange,
  pagedGrouped,
  sortedLength,
  totalPages,
  currentPage,
  onPageChange,
  onExpand,
}: ShelfTabProps) {
  return (
    <>
      {/* 紧凑统计栏 */}
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
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索书名 / 作者 / 笔记…"
            className="w-full rounded-md border border-gray-200 py-1.5 pl-9 pr-3 text-xs text-gray-700 placeholder:text-gray-400 focus:border-primary-border focus:outline-none"
          />
        </div>

        {/* 排序 */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-bold text-gray-400">排序</span>
          <select
            value={sortKey}
            onChange={(e) => onSortKeyChange(e.target.value as SortKey)}
            className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs font-bold text-gray-700 focus:border-primary-border focus:outline-none"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={onToggleSortOrder}
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
            onChange={(e) => onGroupKeyChange(e.target.value as GroupKey)}
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
            筛选到 {sortedLength} 本
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
                  onExpand={() => onExpand(item.id)}
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
          onPage={onPageChange}
          summary={<span className="text-xs font-bold text-gray-500">{currentPage} / {totalPages}</span>}
        />
      )}
    </>
  );
}

// ── StatsTab：统计分析视图 ──

export interface StatsTabProps {
  stats: { totalBooks: number; totalNotes: number; totalReviews: number; avgProgress: number };
  itemsWithMeta: Array<{ item: ContentItem; meta: WeReadMeta }>;
  showCharts: boolean;
  onToggleCharts: () => void;
  chartData: { topNotes: Array<{ label: string; value: number; sub: string }>; topAuthors: Array<{ label: string; value: number; sub: string }> };
  onShelfData: (shelfData: WeReadShelfSync) => void;
}

export function StatsTab({
  stats,
  itemsWithMeta,
  showCharts,
  onToggleCharts,
  chartData,
  onShelfData,
}: StatsTabProps) {
  return (
    <>
      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard icon={Library} label="书籍总数" value={stats.totalBooks} tone="primary" />
        <StatCard icon={Highlighter} label="划线总数" value={stats.totalNotes} tone="teal" />
        <StatCard icon={MessageSquare} label="想法总数" value={stats.totalReviews} tone="purple" />
        <StatCard icon={BarChart3} label="平均进度" value={`${stats.avgProgress}%`} tone="amber" />
      </div>

      {/* 本周阅读脉搏 */}
      <Surface icon={Zap} title="本周阅读脉搏" hint="近两周笔记活动对比">
        <WeeklyPulse items={itemsWithMeta} />
      </Surface>

      {/* 图表展开/收起按钮 */}
      <button
        type="button"
        onClick={onToggleCharts}
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
          <Surface icon={Filter} title="完成率漏斗" hint="各阶段转化率，发现阅读瓶颈">
            <CompletionFunnel items={itemsWithMeta} />
          </Surface>
          <Surface icon={Grid3x3} title="笔记密度分布" hint="进度 vs 划线数，气泡=总笔记">
            <NoteDensityScatter items={itemsWithMeta} />
          </Surface>
          <Surface icon={Highlighter} title="划线最多 Top 10" hint="按划线数量排序">
            <TopNBars data={chartData.topNotes} unit="条" />
          </Surface>
          <Surface icon={Users} title="最活跃作者 Top 10" hint="按划线+想法总数排序">
            <TopNBars data={chartData.topAuthors} unit="条" />
          </Surface>
        </div>
      )}

      {/* 阅读统计 + 书架对比 */}
      <ReadingStatsCard />
      <ShelfComparison notebookCount={itemsWithMeta.length} onShelfData={onShelfData} />
    </>
  );
}

// ── DiscoverTab：发现视图 ──

export interface DiscoverTabProps {
  keyword: string;
  onKeywordChange: (k: string) => void;
  loading: boolean;
  error: string | null;
  results: WeReadSearchBook[];
  shelfTitleSet: Set<string>;
}

export function DiscoverTab({
  keyword,
  onKeywordChange,
  loading,
  error,
  results,
  shelfTitleSet,
}: DiscoverTabProps) {
  return (
    <>
      {/* 搜索框 */}
      <Panel className="p-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={keyword}
            onChange={(e) => onKeywordChange(e.target.value)}
            placeholder="搜索微信读书书库：书名 / 作者 / 关键词…"
            className="w-full rounded-md border border-gray-200 py-2 pl-9 pr-9 text-sm text-gray-700 placeholder:text-gray-400 focus:border-primary-border focus:outline-none"
            autoFocus
          />
          {keyword && (
            <button
              type="button"
              onClick={() => onKeywordChange('')}
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
      {loading && (
        <Panel className="flex items-center justify-center gap-2 p-12">
          <Loader2 size={20} className="animate-spin text-primary" />
          <span className="text-sm font-bold text-gray-500">正在搜索微信读书书库…</span>
        </Panel>
      )}

      {/* 搜索错误 */}
      {error && !loading && (
        <Panel className="p-6 text-center">
          <p className="text-sm font-bold text-red">{error}</p>
          <p className="mt-1 text-xs text-gray-400">请确保已配置微信读书 API Key</p>
        </Panel>
      )}

      {/* 搜索结果 */}
      {!loading && !error && results.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-black text-gray-700">搜索结果</span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-500">
              {results.length} 本
            </span>
            {keyword && (
              <span className="text-[11px] text-gray-400">
                关键词「{keyword}」
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-4 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
            {results.map((book) => (
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
      {!loading && !error && results.length === 0 && !keyword.trim() && (
        <Panel className="p-12 text-center">
          <Sparkles size={32} className="mx-auto mb-3 text-gray-300" />
          <p className="text-sm font-bold text-gray-500">搜索微信读书全网书库</p>
          <p className="mt-1 text-xs text-gray-400">
            输入书名、作者或关键词，发现书架之外的好书。
          </p>
        </Panel>
      )}

      {/* 无结果 */}
      {!loading && !error && results.length === 0 && keyword.trim() && (
        <Panel className="p-12 text-center">
          <Search size={32} className="mx-auto mb-3 text-gray-300" />
          <p className="text-sm font-bold text-gray-500">未找到相关书籍</p>
          <p className="mt-1 text-xs text-gray-400">
            试试其他关键词？
          </p>
        </Panel>
      )}
    </>
  );
}
