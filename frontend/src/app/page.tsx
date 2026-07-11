'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  BookOpen,
  Check,
  Clock3,
  ExternalLink,
  PenLine,
  Star,
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
import {
  ContentTimeline,
  EditorialItem,
  Spinner,
  TimelineSummary,
  levelColor,
} from './_components';
import {
  RECOMMEND_FILTERS,
  TIME_RANGE_HOURS,
  formatShanghaiToday,
  getContentTime,
  getItemTags,
  normalizeTags,
} from './_app-utils';
import { explainRecommendation, getRecommendationReason } from '@/lib/recommendation';
import ContentAnalysisPanel from '@/components/ContentAnalysisPanel';
import { startContentWorkflow } from '@/lib/workflow';
import {
  parseUTC,
  formatClock as formatTime,
  timeAgo,
  isToday,
  formatTimelineDate,
} from '@/lib/datetime';


export default function HomePage() {
  const router = useRouter();
  const { currentUser, toggleFavorite, refreshCounts, reportContentTotal } = useAppContext();
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
          reportContentTotal(res.total ?? 0);
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
