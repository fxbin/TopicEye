'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  Ban,
  BookOpen,
  Check,
  ChevronDown,
  Clock3,
  Eye,
  ExternalLink,
  Flame,
  PenLine,
  Star,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import Header from '@/components/Header';
import CategoryChip from '@/components/CategoryChip';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import { contentCategoriesApi, contentsApi, feedbackApi } from '@/lib/api';
import type { FeedbackType } from '@/lib/api';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import type { ContentItem, ContentAnalysis, RecommendLevel } from '@/types';
import { explainRecommendation, getRecommendationReason } from '@/lib/recommendation';
import ContentAnalysisPanel from '@/components/ContentAnalysisPanel';
import { startContentWorkflow } from '@/lib/workflow';

const TIME_RANGE_HOURS: Record<string, number | undefined> = {
  '24h': 24,
  '48h': 48,
  '7d': 168,
  '全部': undefined,
};

const RECOMMEND_FILTERS: Array<RecommendLevel | '全部'> = [
  '全部',
  '强烈建议写',
  '值得观察',
  '适合深挖',
  '适合蹭热点',
  '信号不足',
];

// ── Helpers ──

/** Parse a datetime string from backend (UTC, no 'Z' suffix) into a correct Date */
function parseUTC(s: string): Date {
  const normalized = s.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(s) ? s : s + 'Z';
  return new Date(normalized);
}

function formatTime(dateStr: string): string {
  try {
    const d = parseUTC(dateStr);
    if (Number.isNaN(d.getTime())) return '--:--';
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  } catch {
    return '--:--';
  }
}

function timeAgo(dateStr: string): string {
  try {
    const now = Date.now();
    const then = parseUTC(dateStr).getTime();
    if (Number.isNaN(then)) return '';
    const diffSec = Math.floor((now - then) / 1000);
    if (diffSec < 60) return '刚刚';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`;
    if (diffSec < 604800) return `${Math.floor(diffSec / 86400)} 天前`;
    return parseUTC(dateStr).toLocaleDateString('zh-CN');
  } catch {
    return '';
  }
}

function isToday(dateStr: string): boolean {
  try {
    const d = parseUTC(dateStr);
    if (Number.isNaN(d.getTime())) return false;
    const now = new Date();
    return (
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    );
  } catch {
    return false;
  }
}

function getContentTime(item: ContentItem): string {
  return item.published_at || item.crawled_at || item.created_at || '';
}

function normalizeTags(rawTags: unknown): string[] {
  if (Array.isArray(rawTags)) {
    return rawTags
      .map((tag) => String(tag).trim())
      .filter(Boolean);
  }
  if (typeof rawTags === 'string' && rawTags.trim()) {
    return rawTags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
  }
  return [];
}

function getItemTags(item: ContentItem): string[] {
  return Array.from(new Set([
    ...normalizeTags(item.tags),
    ...normalizeTags(item.analysis?.tags),
    ...normalizeTags(item.analyses?.[0]?.tags),
  ]));
}

function formatTimelineDate(dateStr: string): string {
  try {
    const d = parseUTC(dateStr);
    if (Number.isNaN(d.getTime())) return '未知时间';
    const today = new Date();
    const isSameDay = (
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate()
    );
    if (isSameDay) return '今天';
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  } catch {
    return '未知时间';
  }
}

function formatShanghaiToday(): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value || '';
  return `${get('year')} 年 ${get('month')} 月 ${get('day')} 日`;
}

// ── Page Component ──

export default function HomePage() {
  const router = useRouter();
  const { currentUser, toggleFavorite, refreshCounts } = useAppContext();
  const [items, setItems] = useState<ContentItem[]>([]);
  const [totalAvailable, setTotalAvailable] = useState(0);
  const [categoryOptions, setCategoryOptions] = useState<string[]>(['全部']);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState('全部');
  const [activeRecommendLevel, setActiveRecommendLevel] = useState<RecommendLevel | '全部'>('全部');
  const [activeTag, setActiveTag] = useState('全部');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTimeRange, setActiveTimeRange] = useState('48h');
  const [activeSourceType, setActiveSourceType] = useState('全部');
  const [selectedAnalysis, setSelectedAnalysis] = useState<ContentAnalysis | null>(null);
  const [workflowPendingId, setWorkflowPendingId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const res = await contentCategoriesApi.list();
        if (!cancelled) {
          const names = (res.categories || [])
            .map((category) => category.name)
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b, 'zh-CN'));
          setCategoryOptions(['全部', ...names]);
        }
      } catch (err) {
        console.warn('Load categories failed:', err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch data
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await contentsApi.list({
          page_size: 100,
          hours: TIME_RANGE_HOURS[activeTimeRange],
          source_type: activeSourceType === '全部' ? undefined : activeSourceType,
          category: activeCategory === '全部' ? undefined : activeCategory,
          keyword: searchQuery.trim() || undefined,
          include_trend_sources: false,
        });
        if (!cancelled) {
          setItems(res.items || []);
          setTotalAvailable(res.total ?? (res.items || []).length);
          setCategoryOptions((prev) => {
            const merged = new Set(prev);
            merged.add('全部');
            (res.items || []).forEach((item) => {
              if (item.category) merged.add(item.category);
            });
            return ['全部', ...Array.from(merged).filter((name) => name !== '全部').sort((a, b) => a.localeCompare(b, 'zh-CN'))];
          });
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '获取内容失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [activeTimeRange, activeSourceType, activeCategory, searchQuery]);

  const handleIgnore = useCallback(async (id: number) => {
    if (!currentUser) {
      router.push('/login');
      return;
    }
    try {
      await contentsApi.ignore(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
      refreshCounts?.();
    } catch (err) {
      console.error('Ignore failed:', err);
    }
  }, [currentUser, refreshCounts, router]);

  const tagOptions = useMemo(() => {
    const counts = new Map<string, number>();
    items.forEach((item) => {
      getItemTags(item).forEach((tag) => {
        counts.set(tag, (counts.get(tag) || 0) + 1);
      });
    });
    return [
      '全部',
      ...Array.from(counts.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
        .slice(0, 16)
        .map(([tag]) => tag),
    ];
  }, [items]);

  // Filtered + sorted list
  const filtered = useMemo(() => {
    const result = items.filter((item) => {
      if (activeCategory !== '全部' && item.category !== activeCategory) return false;
      if (activeRecommendLevel !== '全部' && explainRecommendation(item.analysis).level !== activeRecommendLevel) return false;
      if (activeTag !== '全部' && !getItemTags(item).includes(activeTag)) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase();
        if (!item.title.toLowerCase().includes(q)) return false;
      }
      return true;
    });
    // Sort by published_at descending
    result.sort((a, b) => {
      const ta = parseUTC(getContentTime(a)).getTime() || 0;
      const tb = parseUTC(getContentTime(b)).getTime() || 0;
      return tb - ta;
    });
    return result;
  }, [items, activeCategory, activeRecommendLevel, activeTag, searchQuery]);

  const timelineGroups = useMemo(() => {
    const groups = new Map<string, Array<{ item: ContentItem; level: RecommendLevel }>>();
    filtered.forEach((item) => {
      const key = formatTimelineDate(getContentTime(item));
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push({
        item,
        level: explainRecommendation(item.analysis).level,
      });
    });
    return Array.from(groups.entries()).map(([dateLabel, entries]) => ({ dateLabel, entries }));
  }, [filtered]);
  const visibleContentIds = useMemo(() => filtered.map((item) => item.id), [filtered]);
  const contentFavoriteState = useContentFavoriteStates(visibleContentIds);

  const handleStartWorkflow = useCallback(async (item: ContentItem, isFavorited: boolean) => {
    setWorkflowPendingId(item.id);
    setError(null);
    try {
      await startContentWorkflow({
        contentId: item.id,
        title: item.title,
        isFavorited,
        toggleFavorite,
        router,
      });
      contentFavoriteState.refresh();
      refreshCounts?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '推进选题失败');
    } finally {
      setWorkflowPendingId(null);
    }
  }, [contentFavoriteState, refreshCounts, router, toggleFavorite]);

  const levelSummary = useMemo(() => {
    const groups: Array<{ level: RecommendLevel; title: string; items: ContentItem[] }> = [
      { level: '强烈建议写', title: '主编推荐', items: [] },
      { level: '值得观察', title: '值得观察', items: [] },
      { level: '适合深挖', title: '适合深挖', items: [] },
      { level: '适合蹭热点', title: '热点观察', items: [] },
      { level: '不建议追', title: '低优先级', items: [] },
      { level: '信号不足', title: '待补信号', items: [] },
    ];
    const fallback = groups[5];
    filtered.forEach((item) => {
      const level = explainRecommendation(item.analysis).level;
      (groups.find((g) => g.level === level) || fallback).items.push(item);
    });
    return groups.filter((g) => g.items.length > 0);
  }, [filtered]);

  // Stats
  const totalCount = totalAvailable || items.length;
  const todayCount = useMemo(() => items.filter((i) => isToday(getContentTime(i))).length, [items]);
  const clientOnlyFilterActive = activeRecommendLevel !== '全部' || activeTag !== '全部';
  const displayedTotalCount = clientOnlyFilterActive ? filtered.length : totalCount;

  // Today's date
  const dateStr = formatShanghaiToday();

  return (
    <div className="fade-in h-full overflow-y-auto px-10 py-8">
      {/* Header */}
      <Header
        title="今日选题"
        date={dateStr}
        stats={[
          { label: '总内容', value: displayedTotalCount, color: '#FF6B35' },
          { label: '今日新增', value: todayCount, color: '#00C9A7' },
        ]}
      />

      {/* Search bar */}
      <div className="mb-4 max-w-[820px]">
        <input
          type="text"
          placeholder="搜索标题..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-[13px] text-gray-900 outline-none transition focus:border-primary"
        />
      </div>

      {/* Filter row: time range + source type */}
      <div className="mb-3 max-w-[820px]">
        <Toolbar className="gap-3">
          {/* Time range */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-gray-500">时间</span>
            {['24h', '48h', '7d', '全部'].map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => setActiveTimeRange(range)}
                className={cx(
                  'rounded-xs px-2.5 py-1 text-xs transition',
                  activeTimeRange === range
                    ? 'bg-primary-light font-semibold text-primary'
                    : 'bg-gray-50 font-normal text-gray-500 hover:bg-gray-100',
                )}
              >
                {range === '全部' ? '全部' : range === '24h' ? '24小时' : range === '48h' ? '48小时' : '近7天'}
              </button>
            ))}
          </div>
          {/* Divider */}
          <div className="h-5 w-px bg-gray-200" />
          {/* Source type */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-gray-500">来源</span>
            {['全部', 'RSS', 'RSSHub', '公众号', '网站', 'Reddit', 'Zhihu'].map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setActiveSourceType(type)}
                className={cx(
                  'rounded-xs px-2.5 py-1 text-xs transition',
                  activeSourceType === type
                    ? 'bg-primary-light font-semibold text-primary'
                    : 'bg-gray-50 font-normal text-gray-500 hover:bg-gray-100',
                )}
              >
                {type}
              </button>
            ))}
          </div>
        </Toolbar>
      </div>

      {/* Filters - Category */}
      <div className="mb-3 max-w-[820px]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs font-medium text-gray-500">分类</span>
          {categoryOptions.map((c) => (
            <CategoryChip
              key={c}
              name={c}
              active={activeCategory === c}
              onClick={() => {
                setActiveCategory(c);
                setActiveTag('全部');
              }}
            />
          ))}
        </div>
      </div>

      <div className="mb-3 max-w-[820px]">
        <Toolbar className="gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-gray-500">推荐</span>
            {RECOMMEND_FILTERS.map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setActiveRecommendLevel(level)}
                className={cx(
                  'rounded-xs px-2.5 py-1 text-xs transition',
                  activeRecommendLevel === level
                    ? 'bg-primary-light font-semibold text-primary'
                    : 'bg-gray-50 font-normal text-gray-500 hover:bg-gray-100',
                )}
              >
                {level === '全部' ? '全部' : level}
              </button>
            ))}
          </div>
        </Toolbar>
      </div>

      <div className="mb-7 max-w-[820px]">
        <Toolbar className="gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-gray-500">标签</span>
            {tagOptions.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => setActiveTag(tag)}
                className={cx(
                  'rounded-xs px-2.5 py-1 text-xs transition',
                  activeTag === tag
                    ? 'bg-teal-light font-semibold text-teal'
                    : 'bg-gray-50 font-normal text-gray-500 hover:bg-gray-100',
                )}
              >
                {tag === '全部' ? '全部' : `#${tag}`}
              </button>
            ))}
          </div>
        </Toolbar>
      </div>

      {/* Error state */}
      {error && (
        <div className="mb-5 max-w-[820px] rounded-lg border border-red bg-red-light px-5 py-4 text-sm text-red">
          加载失败：{error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="max-w-[820px] py-[60px] text-center">
          <Spinner />
          <div className="mt-3 text-[13px] text-gray-400">加载中...</div>
        </div>
      )}

      {/* Editorial content flow */}
      {!loading && !error && (
        <div className="grid items-start gap-6 pb-[60px] xl:grid-cols-[minmax(0,820px)_260px]">
          <div className="min-w-0">
            <ContentTimeline
              groups={timelineGroups}
              isFavorited={contentFavoriteState.isFavorited}
              onToggleFav={async (id) => {
                await toggleFavorite(id);
                contentFavoriteState.refresh();
              }}
              onIgnore={handleIgnore}
              onShowAnalysis={(a) => setSelectedAnalysis(a)}
              onStartWorkflow={handleStartWorkflow}
              workflowPendingId={workflowPendingId}
            />
            {filtered.length === 0 && (
              <div className="py-[60px] text-center text-sm text-gray-400">
                当前筛选条件下没有内容
              </div>
            )}
          </div>
          <TimelineSummary
            groups={levelSummary}
            total={filtered.length}
            availableTotal={clientOnlyFilterActive ? undefined : totalCount}
          />
        </div>
      )}

      {/* Analysis panel overlay */}
      {selectedAnalysis && (
        <>
          <div
            onClick={() => setSelectedAnalysis(null)}
            className="fixed inset-0 z-[999] bg-black/20"
          />
          <ContentAnalysisPanel
            analysis={selectedAnalysis}
            onClose={() => setSelectedAnalysis(null)}
          />
        </>
      )}
    </div>
  );
}

function ContentTimeline({
  groups,
  isFavorited,
  onToggleFav,
  onIgnore,
  onShowAnalysis,
  onStartWorkflow,
  workflowPendingId,
}: {
  groups: Array<{ dateLabel: string; entries: Array<{ item: ContentItem; level: RecommendLevel }> }>;
  isFavorited: (id: number) => boolean;
  onToggleFav: (id: number) => void | Promise<void>;
  onIgnore: (id: number) => void;
  onShowAnalysis: (analysis: ContentAnalysis) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void | Promise<void>;
  workflowPendingId: number | null;
}) {
  if (groups.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-[26px]">
      {groups.map((group) => (
        <section key={group.dateLabel}>
          <div className="mb-3 flex items-center gap-2.5 text-gray-500">
            <Clock3 size={15} className="text-primary" strokeWidth={2.2} />
            <h2 className="text-sm font-extrabold text-gray-900">
              {group.dateLabel}
            </h2>
            <span className="font-mono text-xs text-gray-400">{group.entries.length}</span>
          </div>
          <div className="relative flex flex-col gap-3.5">
            <div className="absolute bottom-[9px] left-[58px] top-[9px] w-px bg-gray-200" />
            {group.entries.map(({ item, level }) => (
              <div key={item.id} className="relative grid grid-cols-[50px_18px_minmax(0,1fr)] items-start gap-2.5">
                <div className="pt-0.5 text-right font-mono text-xs font-extrabold text-gray-700">
                  {formatTime(getContentTime(item))}
                </div>
                <span style={{
                  position: 'relative',
                  zIndex: 1,
                  width: 12,
                  height: 12,
                  marginTop: 4,
                  marginLeft: 3,
                  borderRadius: 999,
                  background: '#FFFFFF',
                  border: `3px solid ${levelColor(level)}`,
                  boxSizing: 'border-box',
                }} />
                <EditorialItem
                  item={item}
                  isFav={isFavorited(item.id)}
                  onToggleFav={onToggleFav}
                  onIgnore={onIgnore}
                  time={formatTime(getContentTime(item))}
                  timeLabel={timeAgo(getContentTime(item))}
                  level={level}
                  compact
                  onShowAnalysis={onShowAnalysis}
                  onStartWorkflow={onStartWorkflow}
                  workflowPending={workflowPendingId === item.id}
                />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function TimelineSummary({
  groups,
  total,
  availableTotal,
}: {
  groups: Array<{ level: RecommendLevel; title: string; items: ContentItem[] }>;
  total: number;
  availableTotal?: number;
}) {
  const totalLabel = availableTotal && availableTotal !== total ? `${total}/${availableTotal}` : String(total);

  return (
    <aside className="sticky top-6 hidden xl:block">
      <Panel className="p-[18px] shadow-sm">
        <div className="mb-3.5 flex items-center gap-2">
          <Clock3 size={15} className="text-primary" strokeWidth={2.2} />
          <span className="text-sm font-extrabold text-gray-900">内容时间流</span>
          <span className="ml-auto font-mono text-[11px] text-gray-400">{totalLabel}</span>
        </div>
        <div className="flex flex-col gap-2.5">
          {groups.map((group) => (
            <div key={group.level} className="flex items-center gap-2">
              <span style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: levelColor(group.level),
                flexShrink: 0,
              }} />
              <span className="flex-1 text-xs text-gray-600">{group.title}</span>
              <span className="font-mono text-xs font-extrabold text-gray-900">{group.items.length}</span>
            </div>
          ))}
          <div className="mt-1.5 border-t border-gray-100 pt-3 text-xs leading-7 text-gray-500">
            榜单型热搜已从今日内容流排除，可在「趋势雷达」查看。
          </div>
        </div>
      </Panel>
    </aside>
  );
}

function levelColor(level: RecommendLevel): string {
  if (level === '强烈建议写') return '#FF6B35';
  if (level === '适合深挖') return '#8B5CF6';
  if (level === '适合蹭热点') return '#D97706';
  if (level === '不建议追') return '#9CA3AF';
  if (level === '信号不足') return '#D1D5DB';
  return '#00C9A7';
}

// ── Spinner ──

function Spinner() {
  return (
    <div className="inline-block h-7 w-7 animate-spin rounded-full border-[3px] border-gray-200 border-t-primary" />
  );
}

// ── Editorial Item Component ──

function EditorialItem({
  item,
  isFav,
  onToggleFav,
  onIgnore,
  time,
  timeLabel,
  level,
  compact = false,
  onShowAnalysis,
  onStartWorkflow,
  workflowPending,
}: {
  item: ContentItem;
  isFav: boolean;
  onToggleFav: (id: number) => void;
  onIgnore: (id: number) => void;
  time: string;
  timeLabel: string;
  level?: RecommendLevel;
  compact?: boolean;
  onShowAnalysis: (analysis: ContentAnalysis) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  workflowPending: boolean;
}) {
  const handleCardClick = useCallback(() => {
    if (item.analysis) {
      onShowAnalysis(item.analysis);
    } else if (item.url) {
      window.open(item.url, '_blank', 'noopener,noreferrer');
    }
  }, [item.analysis, item.url, onShowAnalysis]);

  const recommendation = getRecommendationReason(item.analysis, item.summary);
  const itemTags = getItemTags(item);

  return (
      <Panel
        id={`topic-item-${item.id}`}
        onClick={handleCardClick}
        className={cx(
          'group flex-1 overflow-hidden shadow-sm transition hover:border-primary-border hover:shadow-lg',
          compact ? 'px-[18px] py-3.5' : 'px-[22px] py-[18px]',
          item.url ? 'cursor-pointer' : 'cursor-default',
        )}
      >
        {/* Card header */}
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-xs font-semibold text-gray-600">
              {item.source_name}
            </span>
            <span className="text-xs text-gray-300">/</span>
            <span className="shrink-0 text-xs text-gray-400">{timeLabel || time}</span>
            {level && <RecommendBadge level={level} />}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {item.category && (
              <span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-semibold text-gray-600">
                {item.category}
              </span>
            )}
          </div>
        </div>

        {/* Title */}
        <h3 className="mb-2 text-base font-semibold leading-[1.55] text-gray-900">
          {item.title}
        </h3>

        {/* Editorial reason */}
        {recommendation && (
          <div className="line-clamp-2 mb-3 border-l-[3px] border-primary py-1.5 pl-3 text-[13px] leading-7 text-gray-600">
            推荐理由：{recommendation}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {item.analysis && (
              <React.Fragment>
                <CurationScoreBadge score={item.analysis.adjusted_curation_score ?? item.analysis.curation_score} />
                <ScoreBadge label="创作" score={item.analysis.creator_score} tone="primary" />
                <ScoreBadge label="爆文" score={item.analysis.viral_score} tone="neutral" />
                <ScoreBadge label="质量" score={item.analysis.quality_score} tone="neutral" />
                <RecommendBadge level={explainRecommendation(item.analysis).level} />
                <DeepReadBadge enrichment={item.analysis.enrichment} />
              </React.Fragment>
            )}
            {itemTags.length > 0
              ? itemTags.slice(0, 5).map((tag) => (
                  <span key={tag} className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                    #{tag}
                  </span>
                ))
              : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {item.analysis && (
              <Button
                type="button"
                variant="secondary"
                className="min-h-0 px-2 py-1 text-xs opacity-0 group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation();
                  onShowAnalysis(item.analysis as ContentAnalysis);
                }}
              >
                <Eye size={13} strokeWidth={2} />
                分析
              </Button>
            )}
            <Button
              type="button"
              variant="primary"
              disabled={workflowPending}
              className="min-h-0 px-2 py-1 text-xs opacity-0 group-hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                onStartWorkflow(item, isFav);
              }}
              title="加入选题工作流"
            >
              <PenLine size={13} strokeWidth={2} />
              {workflowPending ? '推进中' : '推进'}
            </Button>
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1.5 rounded-xs border border-teal-border bg-teal-light px-2 py-1 text-xs font-bold text-teal no-underline transition hover:border-teal"
                title="查看原文"
              >
                <ExternalLink size={13} strokeWidth={2} />
                原文
              </a>
            )}
            {/* Feedback buttons */}
            <FeedbackButtons contentId={item.id} />
            {/* Favorite */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleFav(item.id);
              }}
              className={cx('inline-flex border-0 bg-transparent p-0.5 transition', isFav ? 'text-primary' : 'text-gray-300 hover:text-primary')}
              title={isFav ? '取消收藏' : '收藏'}
            >
              <Star size={16} strokeWidth={2} fill={isFav ? '#FF6B35' : 'none'} />
            </button>
            {/* Ignore */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onIgnore(item.id);
              }}
              className="inline-flex border-0 bg-transparent p-0.5 text-gray-300 transition hover:text-gray-500"
              title="不感兴趣"
            >
              <X size={15} strokeWidth={2} />
            </button>
          </div>
        </div>
      </Panel>
  );
}

// ── Score Badge ──

function ScoreBadge({ label, score, tone }: { label: string; score: number; tone: 'primary' | 'neutral' }) {
  const strong = score >= 75;
  const medium = score >= 50;
  const toneClass = tone === 'primary' && strong
    ? 'bg-primary-light text-primary'
    : medium
      ? 'bg-gray-100 text-gray-600'
      : 'bg-gray-100 text-gray-400';
  return (
    <span className={cx('rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold', toneClass)}>
      {label}{Math.round(score)}
    </span>
  );
}

// ── Recommend Badge ──

function RecommendBadge({ level }: { level: RecommendLevel }) {
  const toneMap: Record<RecommendLevel, 'primary' | 'teal' | 'purple' | 'amber' | 'neutral'> = {
    '强烈建议写': 'primary',
    '值得观察': 'teal',
    '适合深挖': 'purple',
    '适合蹭热点': 'amber',
    '不建议追': 'neutral',
    '信号不足': 'neutral',
  };
  return (
    <Badge tone={toneMap[level] || 'neutral'} className="rounded px-2 py-0.5 text-[10px]">
      {level}
    </Badge>
  );
}

// ── Curation Score Badge ──

function CurationScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null || score === 0) return null;
  const rounded = Math.round(score);
  const toneClass = rounded >= 85
    ? 'bg-teal-light text-teal'
    : rounded >= 70
      ? 'bg-primary-light text-primary'
      : rounded >= 55
        ? 'bg-amber-light text-amber'
        : 'bg-gray-100 text-gray-400';
  return (
    <span className={cx('rounded px-2 py-0.5 font-mono text-[11px] font-bold', toneClass)}>
      {rounded}
    </span>
  );
}

// ── Deep Read Badge (arXiv 论文精读标记) ──

function DeepReadBadge({ enrichment }: { enrichment?: Record<string, unknown> | null }) {
  // enrichment 由论文 prompt 产出: { worth_deep_read, deep_read_score, deep_read_reason }
  if (!enrichment) return null;
  const worth = enrichment.worth_deep_read as boolean | undefined;
  const reason = enrichment.deep_read_reason as string | undefined;
  if (!worth) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-purple-light px-1.5 py-0.5 text-[10px] font-bold text-purple"
      title={reason || 'AI 判定值得精读'}
    >
      <BookOpen size={11} strokeWidth={2.2} />
      精读
    </span>
  );
}

// ── Feedback Buttons ──

const FEEDBACK_OPTIONS: { type: FeedbackType; icon: LucideIcon; label: string; color: string }[] = [
  { type: 'great_pick', icon: Flame, label: '精选好文', color: '#16a34a' },
  { type: 'like', icon: ThumbsUp, label: '有价值', color: '#2563eb' },
  { type: 'dislike', icon: ThumbsDown, label: '不感兴趣', color: '#dc2626' },
  { type: 'not_relevant', icon: Ban, label: '不相关', color: '#9ca3af' },
  { type: 'outdated', icon: Clock3, label: '过时了', color: '#d97706' },
];

function FeedbackButtons({ contentId }: { contentId: number }) {
  const { currentUser } = useAppContext();
  const router = useRouter();
  const [activeFeedback, setActiveFeedback] = useState<FeedbackType | null>(null);
  const [showMore, setShowMore] = useState(false);

  const handleFeedback = async (type: FeedbackType) => {
    if (activeFeedback === type) return; // already submitted
    if (!currentUser) {
      router.push('/login');
      return;
    }
    try {
      await feedbackApi.submit(contentId, type);
      setActiveFeedback(type);
    } catch (err: unknown) {
      // 409 = duplicate, that's fine
      const msg = err instanceof Error ? err.message : String(err);
      if (!msg?.includes('409') && !msg?.includes('Conflict')) {
        console.error('Feedback failed:', err);
      }
    }
  };

  return (
    <div className="relative flex items-center gap-0.5">
      {/* Quick feedback: thumbs up/down */}
      {FEEDBACK_OPTIONS.slice(0, 2).map(({ type, icon: Icon, label, color }) => (
        <button
          key={type}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleFeedback(type);
          }}
          title={label}
          className={cx(
            'inline-flex rounded border-0 bg-transparent px-1 py-0.5 transition',
            activeFeedback === type ? 'cursor-default' : 'cursor-pointer',
            activeFeedback && activeFeedback !== type ? 'opacity-30' : 'opacity-100',
          )}
          style={{ color: activeFeedback === type ? color : '#9CA3AF', background: activeFeedback === type ? `${color}15` : 'transparent' }}
        >
          <Icon size={13} strokeWidth={2.2} />
        </button>
      ))}
      
      {/* More feedback options dropdown */}
      <div className="relative">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowMore(!showMore);
          }}
          className={cx('inline-flex cursor-pointer rounded border-0 px-1.5 py-0.5 text-gray-400 transition hover:text-gray-600', showMore ? 'bg-gray-100' : 'bg-transparent')}
          title="更多反馈"
        >
          <ChevronDown size={13} strokeWidth={2.2} />
        </button>
        {showMore && (
          <>
            <div
              onClick={(e) => e.stopPropagation()}
              className="absolute right-0 top-full z-[100] mt-1 min-w-[120px] rounded-sm border border-gray-200 bg-white p-1 shadow-lg"
            >
              {FEEDBACK_OPTIONS.map(({ type, icon: Icon, label, color }) => (
                <button
                  key={type}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleFeedback(type);
                    setShowMore(false);
                  }}
                  className={cx(
                    'flex w-full items-center gap-2 rounded border-0 px-2.5 py-1.5 text-left text-xs',
                    activeFeedback === type ? 'cursor-default font-semibold' : 'cursor-pointer font-normal hover:bg-gray-50',
                  )}
                  style={{ color: activeFeedback === type ? color : '#4B5563', background: activeFeedback === type ? `${color}10` : 'transparent' }}
                >
                  <Icon size={13} strokeWidth={2.2} />
                  <span>{label}</span>
                  {activeFeedback === type && <Check size={12} strokeWidth={2.4} className="ml-auto" />}
                </button>
              ))}
            </div>
            {/* Click outside to close */}
            <div
              onClick={() => setShowMore(false)}
              className="fixed inset-0 z-[99]"
            />
          </>
        )}
      </div>
    </div>
  );
}
