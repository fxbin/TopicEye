'use client';

import React, { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  ChevronDown,
  Columns3,
  FileText,
  List,
} from 'lucide-react';
import { contentsApi } from '@/lib/api';
import { PICKS_VIEWS, picksViewHref, readPicksView, readSnapshotDays, type PicksView } from '@/lib/picks-view';
import TrendExplorer from '../trends/TrendExplorer';
import type { EvidenceMark } from '@/types';
import { useAppContext } from '@/components/ClientLayout';
import AnalysisPanel from '@/components/AnalysisPanel';
import { PendingReview } from './_pending-review';
import RadarSignature from '@/components/RadarSignature';
import { Button, cx } from '@/components/ui';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateView';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import { useFetch } from '@/hooks/useFetch';
import { getRecommendLevelLabel } from '@/lib/utils';
import { startContentWorkflow } from '@/lib/workflow';
import type { ContentAnalysis, ContentItem, TopicInfo } from '@/types';
import {
  RECOMMEND_LEVELS,
  DEFAULT_TIME_RANGE,
  normalizeTimeRange,
  getAnalysis,
  scoreOf,
} from './_today-picks-utils';
import {
  PICK_PAGE_SIZE,
  hasMorePicks,
  mergePickPage,
  mergePickTopics,
  nextPickOffset,
} from './_paging';
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
    <Suspense fallback={<div className="p-20 text-center text-sm text-gray-600">加载中...</div>}>
      <TodayPicksPage />
    </Suspense>
  );
}

function TodayPicksPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pageView = readPicksView(searchParams.get('view'));
  const snapshotDays = readSnapshotDays(searchParams.get('days'));
  const scrollRef = useRef<HTMLDivElement>(null);
  const viewScrolls = useRef<Record<string, number>>({});
  const restoringScroll = useRef<string | null>(null);
  const { toggleFavorite, currentUser, reportTodayPicksTotal, openReader } = useAppContext();

  const selectedCategory = searchParams.get('category') || '';
  const selectedContentType = searchParams.get('content_type') || '';
  const selectedLevel = searchParams.get('level') || '';
  const selectedTimeRange = normalizeTimeRange(searchParams.get('time_range'));
  const picksScope = JSON.stringify([selectedCategory, selectedContentType, selectedTimeRange]);
  const scrollKey = pageView === 'picks' ? `picks:${picksScope}:${selectedLevel}` : `${pageView}:${snapshotDays}`;
  useLayoutEffect(() => { restoringScroll.current = scrollKey; if (scrollRef.current) scrollRef.current.scrollTop = 0; }, [scrollKey]);
  const restoreScroll = useCallback(() => {
    if (restoringScroll.current !== scrollKey) return;
    requestAnimationFrame(() => {
      if (restoringScroll.current !== scrollKey || !scrollRef.current) return;
      scrollRef.current.scrollTop = viewScrolls.current[scrollKey] ?? 0;
      restoringScroll.current = null;
    });
  }, [scrollKey]);
  const [selectedAnalysis, setSelectedAnalysis] = useState<(ContentAnalysis & { _content_id?: number }) | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [groupByTopic, setGroupByTopic] = useState(true);
  const [expandedTopics, setExpandedTopics] = useState<Set<number>>(new Set());
  const [materialLimits, setMaterialLimits] = useState<Record<number, number>>({});
  const rememberMaterialLimit = useCallback((limit: number) => setMaterialLimits(current => ({ ...current, [snapshotDays]: limit })), [snapshotDays]);
  const [workflowPendingId, setWorkflowPendingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const updateURL = useCallback((cat: string, ct: string, level: string, tr: string) => {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of [['category', cat], ['content_type', ct], ['level', level], ['time_range', tr === DEFAULT_TIME_RANGE ? '' : tr]]) { if (value) params.set(key, value); else params.delete(key); }
    const qs = params.toString();
    router.replace(`/today-picks${qs ? '?' + qs : ''}`, { scroll: false });
  }, [router, searchParams]);

  const setCategory = (cat: string) => {
    updateURL(cat, selectedContentType, selectedLevel, selectedTimeRange);
  };
  const setContentType = (ct: string) => {
    updateURL(selectedCategory, ct, selectedLevel, selectedTimeRange);
  };
  const setLevel = (level: string) => {
    const next = selectedLevel === level ? '' : level;
    updateURL(selectedCategory, selectedContentType, next, selectedTimeRange);
  };
  const setTimeRange = (tr: string) => {
    updateURL(selectedCategory, selectedContentType, selectedLevel, tr);
  };
  const changePageView = (next: PicksView) => {
    if (next === pageView) return;
    viewScrolls.current[scrollKey] = scrollRef.current?.scrollTop ?? 0;
    setSelectedAnalysis(null);
    router.push(picksViewHref(next, new URLSearchParams(searchParams.toString())), { scroll: false });
  };
  const changeSnapshotDays = (days: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('days', String(days));
    router.replace(picksViewHref(pageView, params), { scroll: false });
  };

  const clearFilters = () => {
    updateURL('', '', '', DEFAULT_TIME_RANGE);
  };

  // 数据获取：首屏取第一页，后续按 offset 追加（#218）。
  //
  // 后端 today-picks 的 offset 返回的是同一条稳定序列的下一段，因此追加只做
  // 按 id 去重合并，已加载条目不会被后续页改写位置。首屏用 useFetch（含竞态
  // 保护），后续页用 loadMore 单独发起，失败时保留已加载内容可重试。
  const buildParams = useCallback((offset: number) => {
    const params: {
      category?: string;
      content_type?: string;
      time_range?: string;
      limit?: number;
      offset?: number;
    } = {};
    if (selectedCategory) params.category = selectedCategory;
    if (selectedContentType) params.content_type = selectedContentType;
    params.time_range = selectedTimeRange;
    params.limit = PICK_PAGE_SIZE;
    params.offset = offset;
    return params;
  }, [selectedCategory, selectedContentType, selectedTimeRange]);

  const fetchPicks = useCallback(async () => ({ ...await contentsApi.todayPicks(buildParams(0)), scope: picksScope }), [buildParams, picksScope]);

  const { data: fetchedPicks, loading, error, refetch } = useFetch(fetchPicks, [selectedCategory, selectedContentType, selectedTimeRange]);
  const data = fetchedPicks?.scope === picksScope ? fetchedPicks : null;
  const picksBusy = loading || (!data && !error);

  // 已加载的条目（首屏 + 后续页）。筛选变化时随首屏重置。
  const [loadedFrom, setLoadedFrom] = useState<typeof data>(null);
  const [loadedItems, setLoadedItems] = useState<ContentItem[]>([]);
  // 已加载条目涉及的话题。后端每页只返回本页涉及的话题，追加页的新话题
  // 必须合并进来，否则话题视图下这些条目会因为没有对应分组而丢失。
  const [loadedTopics, setLoadedTopics] = useState<TopicInfo[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [serverHasMore, setServerHasMore] = useState<boolean | undefined>(undefined);
  const loadMorePending = useRef(false);
  // 筛选/窗口变化时递增：让在途的后续页请求作废，避免旧筛选的结果混进来
  const requestSeq = useRef(0);

  // 首屏结果落到已加载列表；筛选变化时整体替换
  useEffect(() => {
    requestSeq.current += 1;
    loadMorePending.current = false;
    setLoadingMore(false);
    setLoadMoreError(null);
    setLoadedFrom(data);
    setLoadedItems(data?.items || []);
    setLoadedTopics(data?.topics || []);
    setServerHasMore(data?.has_more);
  }, [data]);

  const projectionReady = data !== null && loadedFrom === data;
  const picksLoading = picksBusy || (!!data && !projectionReady);
  useLayoutEffect(() => { if (pageView === 'picks' && !picksLoading && projectionReady) restoreScroll(); }, [pageView, picksLoading, projectionReady, restoreScroll]);
  const items = useMemo(() => projectionReady ? loadedItems : [], [projectionReady, loadedItems]);
  const total = data?.total || 0;
  const topics = useMemo(() => projectionReady ? loadedTopics : [], [projectionReady, loadedTopics]);
  const eventMemberCount = data?.event_members_hidden || 0;
  const canLoadMore = hasMorePicks(items.length, total, serverHasMore);

  // 加载下一批：offset 用实际已加载条数，窗口内新增内容导致的位移能被补回
  const loadMore = useCallback(async () => {
    if (loadMorePending.current || !canLoadMore) return;
    loadMorePending.current = true;
    setLoadingMore(true);
    setLoadMoreError(null);
    const seq = requestSeq.current;
    try {
      const res = await contentsApi.todayPicks(buildParams(nextPickOffset(items.length)));
      if (seq !== requestSeq.current) return;
      setLoadedItems((prev) => mergePickPage(prev, res.items || []));
      setLoadedTopics((prev) => mergePickTopics(prev, res.topics || []));
      setServerHasMore(res.has_more);
    } catch (err) {
      if (seq === requestSeq.current) {
        setLoadMoreError(err instanceof Error ? err.message : '加载更多失败，请重试');
      }
    } finally {
      if (seq === requestSeq.current) {
        loadMorePending.current = false;
        setLoadingMore(false);
      }
    }
  }, [buildParams, canLoadMore, items.length]);

  // 滚动到底自动加载下一批。
  //
  // 用 IntersectionObserver 而不是 window scroll 事件：本页滚动发生在
  // ClientLayout 的内部滚动容器里（min-h-0 flex-1 overflow-auto），scroll
  // 事件不会冒泡到 window，监听 window 收不到事件。
  const loadMoreAnchorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const anchor = loadMoreAnchorRef.current;
    if (!anchor || pageView !== 'picks') return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      // 提前 400px 触发，滚到接近底部时内容已就位，不出现空窗
      { rootMargin: '0px 0px 400px 0px' },
    );
    observer.observe(anchor);
    return () => observer.disconnect();
  }, [loadMore, pageView]);

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
    selectedContentType,
    selectedLevel,
    selectedTimeRange !== DEFAULT_TIME_RANGE ? selectedTimeRange : '',
  ].filter(Boolean).length;
  const isDefaultWindow = selectedTimeRange === DEFAULT_TIME_RANGE;
  const hasNonTimeFilters = Boolean(selectedCategory || selectedContentType || selectedLevel);
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
    const wasFav = contentFavoriteState.isFavorited(id);
    await toggleFavorite(id);
    contentFavoriteState.refresh();
    contentsApi.trackEvidenceInteraction(id, wasFav ? 'unfavorite' : 'favorite');
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

  const handleRead = useCallback((id: number) => {
    contentsApi.trackEvidenceInteraction(id, 'click');
    openReader(id);
  }, [openReader]);

  const toggleTopic = (id: number) => {
    setExpandedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div ref={scrollRef} onScroll={event => { if (restoringScroll.current === null) viewScrolls.current[scrollKey] = event.currentTarget.scrollTop; }} className="workspace-scroll">
      <div className="sticky top-0 z-10 -mx-4 sm:-mx-6 lg:-mx-10 border-b border-gray-200 bg-[#F8FAFC]/90 px-4 sm:px-6 lg:px-10 pb-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3">
              <RadarSignature size={20} />
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="page-title text-gray-900">当日精选</h1>
              </div>
            </div>
            <p className="mt-1 hidden text-sm leading-6 text-gray-600 sm:block">
              {pageView === 'picks' ? '从算法候选中筛出可写选题，按话题、质量和来源做二次判断' : '补充查看公共收录的材料与标签分布，观察窗口独立于精选筛选'}
            </p>
          </div>
          {pageView === 'picks' && <Button
            type="button"
            variant={groupByTopic ? 'primary' : 'secondary'}
            onClick={() => setGroupByTopic(!groupByTopic)}
          >
            {groupByTopic ? <Columns3 size={15} /> : <List size={15} />}
            {groupByTopic ? '精选分组' : '精选列表'}
          </Button>}
        </div>
        <div role="tablist" aria-label="当日精选视图" className="mx-auto mt-3 grid max-w-[1200px] grid-cols-3 gap-1 sm:flex sm:gap-5">
          {PICKS_VIEWS.map((view, index) => <button key={view.value} type="button" role="tab" id={`picks-${view.value}-tab`} aria-controls={`picks-${view.value}-panel`} aria-selected={pageView === view.value} tabIndex={pageView === view.value ? 0 : -1} onClick={() => changePageView(view.value)} onKeyDown={event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? PICKS_VIEWS.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + PICKS_VIEWS.length) % PICKS_VIEWS.length;
            changePageView(PICKS_VIEWS[next].value);
            document.getElementById(`picks-${PICKS_VIEWS[next].value}-tab`)?.focus();
          }} className={cx('min-h-11 border-b-2 px-2 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-primary sm:px-1', pageView === view.value ? 'border-primary text-primary-text' : 'border-transparent text-gray-600 hover:text-gray-900')}>{view.label}</button>)}
        </div>
      </div>

      <section role="tabpanel" id="picks-picks-panel" aria-labelledby="picks-picks-tab" hidden={pageView !== 'picks'} tabIndex={0}>
      <div className="mx-auto mt-6 grid max-w-[1200px] grid-cols-[minmax(0,1fr)_260px] items-start gap-4.5 max-lg:grid-cols-1">
        <main className="min-w-0">
          {projectionReady && <OverviewStrip
            total={selectedLevel ? filteredItems.length : total}
            loadedCount={filteredItems.length}
            sourceCount={sourceCount}
            topicCount={sortedTopics.length}
            avgScore={avgScore}
            eventMemberCount={eventMemberCount}
          />}

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
              onRead={handleRead}
              workflowPending={workflowPendingId === leadItem.id}
              evidenceMark={evidenceMarks[String(leadItem.id)]}
            />
          )}

          {error && <ErrorState error={error} onRetry={() => void refetch()} />}
          {picksLoading ? (
            <LoadingState label="正在读取算法筛选结果…" />
          ) : error && !data ? null : filteredItems.length === 0 ? (
            <EmptyState
              icon={FileText}
              title={activeFilterCount > 0 ? '筛选后没有匹配内容' : '当前窗口暂无精选内容'}
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
              onRead={handleRead}
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
                  onRead={handleRead}
                  workflowPending={workflowPendingId === item.id}
                  evidenceMark={evidenceMarks[String(item.id)]}
                />
              ))}
            </div>
          )}
          {!picksLoading && data?.pending_review && !selectedLevel && <PendingReview {...data.pending_review} onRead={handleRead} />}
          {/* 滚动加载锚点：进入视口即自动接下一批 */}
          <div ref={loadMoreAnchorRef} aria-hidden="true" className="h-px w-full" />
          {!picksLoading && canLoadMore && (
            <div className="pb-10 text-center">
              <Button
                type="button"
                variant="secondary"
                onClick={() => void loadMore()}
                disabled={loadingMore}
              >
                {loadingMore ? '正在加载…' : `加载更多（还有 ${Math.max(0, total - items.length)} 条）`}
              </Button>
              <div className="mt-2 text-[11px] text-gray-600">
                {loadMoreError
                  ? loadMoreError
                  : '向下滚动会自动加载更多，也可以点击按钮继续展开。'}
              </div>
            </div>
          )}
          {!picksLoading && !canLoadMore && items.length > 0 && (
            <div className="pb-10 text-center text-[11px] text-gray-600">
              已加载全部 {items.length} 条精选内容
            </div>
          )}
        </main>

        <aside className="sticky top-[152px] flex flex-col gap-3.5 max-lg:static max-lg:row-start-1">
          <button type="button" aria-expanded={filtersOpen} aria-controls="picks-filters" onClick={() => setFiltersOpen(value => !value)} className="flex min-h-11 items-center justify-between rounded-sm border border-gray-200 bg-white px-4 text-sm font-medium text-gray-700 lg:hidden">
            筛选选题{activeFilterCount > 0 ? `（${activeFilterCount}）` : ''}<ChevronDown size={16} className={filtersOpen ? 'rotate-180 transition' : 'transition'} />
          </button>
          <div id="picks-filters" className={cx(filtersOpen ? 'contents' : 'hidden', 'lg:contents')}>
          <FilterPanel
            selectedCategory={selectedCategory}
            selectedContentType={selectedContentType}
            selectedLevel={selectedLevel}
            selectedTimeRange={selectedTimeRange}
            activeFilterCount={activeFilterCount}
            onCategory={setCategory}
            onContentType={setContentType}
            onLevel={setLevel}
            onTimeRange={setTimeRange}
            onClear={clearFilters}
          />
          {projectionReady && <QualityPanel levelStats={levelStats} total={filteredItems.length} />}
          </div>
        </aside>
      </div>

      </section>
      {(['topics', 'keywords'] as const).map(view => <section key={view} role="tabpanel" id={`picks-${view}-panel`} aria-labelledby={`picks-${view}-tab`} hidden={pageView !== view} tabIndex={0} className="mx-auto mt-2 max-w-[1200px]">
        {pageView === view && <TrendExplorer key={`${view}:${snapshotDays}`} view={view} days={snapshotDays} onDaysChange={changeSnapshotDays} onReady={restoreScroll} initialLimit={materialLimits[snapshotDays] ?? 15} onLimitChange={rememberMaterialLimit} />}
      </section>)}
      {pageView === 'picks' && selectedAnalysis && <AnalysisPanel analysis={selectedAnalysis} onClose={() => setSelectedAnalysis(null)} />}
    </div>
  );
}
