'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Columns3,
  FileText,
  List,
} from 'lucide-react';
import { contentsApi } from '@/lib/api';
import type { EvidenceMark } from '@/types';
import { useAppContext } from '@/components/ClientLayout';
import AnalysisPanel from '@/components/AnalysisPanel';
import RadarSignature from '@/components/RadarSignature';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import { useFetch } from '@/hooks/useFetch';
import { getRecommendLevelLabel } from '@/lib/utils';
import { startContentWorkflow } from '@/lib/workflow';
import type { ContentAnalysis, ContentItem, TopicInfo } from '@/types';
import {
  RECOMMEND_LEVELS,
  DEFAULT_TIME_RANGE,
  INITIAL_PICK_LIMIT,
  PICK_LOAD_STEP,
  normalizeTimeRange,
  getAnalysis,
  scoreOf,
} from './_today-picks-utils';
import {
  OverviewStrip,
  LeadPick,
  FilterPanel,
  QualityPanel,
  TopicBoard,
  PickCard,
} from './_components';
export default function TodayPicksPageWrapper() {
  return (
    <Suspense fallback={<div className="p-20 text-center text-sm text-gray-400">加载中...</div>}>
      <TodayPicksPage />
    </Suspense>
  );
}

function TodayPicksPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { toggleFavorite, currentUser, reportTodayPicksTotal, openReader } = useAppContext();

  const [selectedCategory, setSelectedCategory] = useState(searchParams.get('category') || '');
  const [selectedLevel, setSelectedLevel] = useState(searchParams.get('level') || '');
  const [selectedTimeRange, setSelectedTimeRange] = useState(normalizeTimeRange(searchParams.get('time_range')));
  const [loadLimit, setLoadLimit] = useState(INITIAL_PICK_LIMIT);
  const [selectedAnalysis, setSelectedAnalysis] = useState<(ContentAnalysis & { _content_id?: number }) | null>(null);
  const [groupByTopic, setGroupByTopic] = useState(true);
  const [expandedTopics, setExpandedTopics] = useState<Set<number>>(new Set());
  const [workflowPendingId, setWorkflowPendingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const updateURL = useCallback((cat: string, level: string, tr: string) => {
    const params = new URLSearchParams();
    if (cat) params.set('category', cat);
    if (level) params.set('level', level);
    if (tr && tr !== DEFAULT_TIME_RANGE) params.set('time_range', tr);
    const qs = params.toString();
    router.replace(`/today-picks${qs ? '?' + qs : ''}`, { scroll: false });
  }, [router]);

  const setCategory = (cat: string) => {
    setSelectedCategory(cat);
    setLoadLimit(INITIAL_PICK_LIMIT);
    updateURL(cat, selectedLevel, selectedTimeRange);
  };
  const setLevel = (level: string) => {
    const next = selectedLevel === level ? '' : level;
    setSelectedLevel(next);
    updateURL(selectedCategory, next, selectedTimeRange);
  };
  const setTimeRange = (tr: string) => {
    setSelectedTimeRange(tr);
    setLoadLimit(INITIAL_PICK_LIMIT);
    updateURL(selectedCategory, selectedLevel, tr);
  };
  const clearFilters = () => {
    setSelectedCategory('');
    setSelectedLevel('');
    setSelectedTimeRange(DEFAULT_TIME_RANGE);
    setLoadLimit(INITIAL_PICK_LIMIT);
    updateURL('', '', DEFAULT_TIME_RANGE);
  };

  // 数据获取：从手写 useEffect+fetch 迁移到 useFetch（含竞态保护、enabled、refetch）。
  const fetchPicks = useCallback(() => {
    const params: { category?: string; time_range?: string; limit?: number } = {};
    if (selectedCategory) params.category = selectedCategory;
    params.time_range = selectedTimeRange;
    params.limit = selectedTimeRange === '7d' ? Math.max(loadLimit, 80) : loadLimit;
    return contentsApi.todayPicks(params);
  }, [loadLimit, selectedCategory, selectedTimeRange]);

  const { data, loading } = useFetch(fetchPicks, [loadLimit, selectedCategory, selectedTimeRange]);

  // 从 data 派生各状态
  const items = data?.items || [];
  const total = data?.total || 0;
  const topics = data?.topics || [];
  const dupCount = data?.duplicates_hidden || 0;

  // 批量获取证据标记（避免每张卡片单独 API 调用 N+1）
  const [evidenceMarks, setEvidenceMarks] = useState<Record<string, EvidenceMark>>({});
  useEffect(() => {
    if (items.length === 0) return;
    let cancelled = false;
    contentsApi.getEvidenceBatch(items.map((i) => i.id)).then((res) => {
      if (!cancelled) setEvidenceMarks(res.marks || {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [items]);

  // 副作用：上报当日精选总数到全局 context（原在 fetchPicks 内同步调用）。
  useEffect(() => { reportTodayPicksTotal(total); }, [reportTodayPicksTotal, total]);

  const filteredItems = useMemo(() => {
    if (!selectedLevel) return items;
    return items.filter((item) => {
      const analysis = getAnalysis(item);
      return analysis ? getRecommendLevelLabel(analysis) === selectedLevel : false;
    });
  }, [items, selectedLevel]);

  const topicMap = useMemo(() => {
    const map = new Map<number | null, ContentItem[]>();
    for (const item of filteredItems) {
      const tid = item.topic_id || null;
      if (!map.has(tid)) map.set(tid, []);
      map.get(tid)!.push(item);
    }
    return map;
  }, [filteredItems]);

  const sortedTopics = useMemo(() => (
    topics
      .filter((topic) => topicMap.has(topic.id) && (topicMap.get(topic.id)?.length || 0) > 0)
      .sort((a, b) => b.best_score - a.best_score)
  ), [topics, topicMap]);

  const standaloneItems = topicMap.get(null) || [];
  const activeFilterCount = [
    selectedCategory,
    selectedLevel,
    selectedTimeRange !== DEFAULT_TIME_RANGE ? selectedTimeRange : '',
  ].filter(Boolean).length;
  const isDefaultWindow = selectedTimeRange === DEFAULT_TIME_RANGE;
  const hasNonTimeFilters = Boolean(selectedCategory || selectedLevel);
  const sortedItems = useMemo(() => [...filteredItems].sort((a, b) => scoreOf(b) - scoreOf(a)), [filteredItems]);
  const visibleContentIds = useMemo(() => filteredItems.map((item) => item.id), [filteredItems]);
  const contentFavoriteState = useContentFavoriteStates(visibleContentIds);
  const leadItem = sortedItems[0] || null;
  const sourceCount = new Set(filteredItems.map((item) => item.source_name).filter(Boolean)).size;
  const avgScore = filteredItems.length
    ? Math.round(filteredItems.reduce((sum, item) => sum + scoreOf(item), 0) / filteredItems.length)
    : 0;
  const levelStats = useMemo(() => {
    return RECOMMEND_LEVELS.map((level) => ({
      level,
      count: filteredItems.filter((item) => {
        const analysis = getAnalysis(item);
        return analysis ? getRecommendLevelLabel(analysis) === level : false;
      }).length,
    }));
  }, [filteredItems]);

  const handleFav = async (id: number) => {
    if (!currentUser) {
      setActionError('收藏需要登录，点击右上角登录或使用 Google / GitHub 快速登录');
      return;
    }
    await toggleFavorite(id);
    contentFavoriteState.refresh();
  };
  const handleStartWorkflow = useCallback(async (item: ContentItem, isFavorited: boolean) => {
    if (!currentUser) {
      setActionError('推进选题需要登录，点击右上角登录或使用 Google / GitHub 快速登录');
      return;
    }
    setWorkflowPendingId(item.id);
    setActionError(null);
    try {
      await startContentWorkflow({
        contentId: item.id,
        title: item.title,
        isFavorited,
        toggleFavorite,
        router,
      });
      contentFavoriteState.refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '推进选题失败');
    } finally {
      setWorkflowPendingId(null);
    }
  }, [contentFavoriteState, currentUser, router, toggleFavorite]);
  const toggleTopic = (id: number) => {
    setExpandedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="fade-in min-h-full overflow-y-auto bg-gradient-to-b from-[#F8FAFC] via-[#F4F6F8] to-[#EEF2F5] px-10 pb-12">
      <div className="sticky top-0 z-10 -mx-10 border-b border-gray-200 bg-[#F8FAFC]/90 px-10 py-4.5 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1180px] items-center gap-4.5">
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <RadarSignature size={40} />
              <div className="flex items-center gap-2.5">
                <h1 className="display-title text-xl text-gray-900">当日精选</h1>
                <Badge tone="primary" className="font-mono text-[10px]">
                  CURATION DESK
                </Badge>
              </div>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              从算法候选中筛出可写选题，按话题、质量和来源做二次判断
            </p>
          </div>
          <Button
            type="button"
            variant={groupByTopic ? 'primary' : 'secondary'}
            onClick={() => setGroupByTopic(!groupByTopic)}
          >
            {groupByTopic ? <Columns3 size={15} /> : <List size={15} />}
            {groupByTopic ? '话题视图' : '列表视图'}
          </Button>
        </div>
      </div>

      <div className="mx-auto mt-6 grid max-w-[1180px] grid-cols-[minmax(0,1fr)_260px] items-start gap-4.5 max-lg:grid-cols-1">
        <main className="min-w-0">
          <OverviewStrip
            total={selectedLevel ? filteredItems.length : total}
            loadedCount={filteredItems.length}
            sourceCount={sourceCount}
            topicCount={sortedTopics.length}
            avgScore={avgScore}
            dupCount={dupCount}
          />

          {actionError && (
            <div className="mb-4 rounded-sm border border-red/20 bg-red-light px-4 py-3 text-sm text-red">
              {actionError}
            </div>
          )}

          {leadItem && (
            <LeadPick
              item={leadItem}
              isFav={contentFavoriteState.isFavorited(leadItem.id)}
              onFav={handleFav}
              onOpen={setSelectedAnalysis}
              onStartWorkflow={handleStartWorkflow}
              onRead={openReader}
              workflowPending={workflowPendingId === leadItem.id}
              evidenceMark={evidenceMarks[String(leadItem.id)]}
            />
          )}

          {loading ? (
            <LoadingState label="正在读取算法筛选结果…" />
          ) : filteredItems.length === 0 ? (
            <EmptyState
              icon={FileText}
              title={activeFilterCount > 0 ? '筛选后没有匹配内容' : '近 48 小时暂无精选内容'}
              desc={isDefaultWindow && !hasNonTimeFilters ? '当前窗口没有可写样本，可以先查看近 7 天历史样本，或等待信源同步和分析完成。' : '可以放宽等级、分类或时间范围。'}
              actions={[
                ...(isDefaultWindow ? [{ label: '查看 7 天历史样本', onClick: () => setTimeRange('7d'), variant: 'primary' as const }] : []),
                ...(activeFilterCount > 0 ? [{ label: '清除筛选', onClick: clearFilters, variant: 'secondary' as const }] : []),
              ]}
            />
          ) : groupByTopic ? (
            <TopicBoard
              topics={sortedTopics}
              topicMap={topicMap}
              standaloneItems={standaloneItems}
              expandedTopics={expandedTopics}
              onToggleTopic={toggleTopic}
              isFavorited={contentFavoriteState.isFavorited}
              onFav={handleFav}
              onOpen={setSelectedAnalysis}
              onStartWorkflow={handleStartWorkflow}
              onRead={openReader}
              workflowPendingId={workflowPendingId}
              evidenceMarks={evidenceMarks}
            />
          ) : (
            <div className="flex flex-col gap-2.5 pb-10">
              {sortedItems.map((item, idx) => (
                <PickCard
                  key={item.id}
                  item={item}
                  rank={idx + 1}
                  isFav={contentFavoriteState.isFavorited(item.id)}
                  onFav={handleFav}
                  onOpen={setSelectedAnalysis}
                  onStartWorkflow={handleStartWorkflow}
                  onRead={openReader}
                  workflowPending={workflowPendingId === item.id}
                  evidenceMark={evidenceMarks[String(item.id)]}
                />
              ))}
            </div>
          )}
          {!loading && items.length < total && (
            <div className="pb-10 text-center">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setLoadLimit((current) => current + PICK_LOAD_STEP)}
              >
                加载更多（还有 {total - items.length} 条）
              </Button>
              <div className="mt-2 text-[11px] text-gray-400">首屏优先呈现高分选题，按需继续展开。</div>
            </div>
          )}
        </main>

        <aside className="sticky top-[88px] flex flex-col gap-3.5 max-lg:static max-lg:row-start-1">
          <FilterPanel
            selectedCategory={selectedCategory}
            selectedLevel={selectedLevel}
            selectedTimeRange={selectedTimeRange}
            activeFilterCount={activeFilterCount}
            onCategory={setCategory}
            onLevel={setLevel}
            onTimeRange={setTimeRange}
            onClear={clearFilters}
          />
          <QualityPanel levelStats={levelStats} total={filteredItems.length} />
        </aside>
      </div>

      {selectedAnalysis && <AnalysisPanel analysis={selectedAnalysis} onClose={() => setSelectedAnalysis(null)} />}
    </div>
  );
}

