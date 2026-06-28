'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  BarChart3,
  ChevronDown,
  ChevronUp,
  Clock3,
  Columns3,
  ExternalLink,
  FileText,
  Filter,
  Flame,
  Layers3,
  List,
  PenLine,
  Search,
  SlidersHorizontal,
  Star,
  Target,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import { useAppContext } from '@/components/ClientLayout';
import AnalysisPanel from '@/components/AnalysisPanel';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import { getRecommendLevelLabel, getTagColor, timeAgo } from '@/lib/utils';
import { getRecommendationReason } from '@/lib/recommendation';
import { startContentWorkflow } from '@/lib/workflow';
import type { ContentAnalysis, ContentItem, TopicInfo } from '@/types';

const CATEGORIES = ['全部', 'AI', '职场', '商业', '教育', '自媒体', '科技', '生活', '产品'] as const;
const RECOMMEND_LEVELS = ['强烈建议写', '值得观察', '适合深挖', '适合蹭热点', '不建议追', '信号不足'] as const;
const LEVEL_CONFIG: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  强烈建议写: { bg: 'bg-primary-light', text: 'text-primary', border: 'border-primary-border', dot: 'bg-primary' },
  值得观察: { bg: 'bg-teal-light', text: 'text-teal', border: 'border-teal-border', dot: 'bg-teal' },
  适合深挖: { bg: 'bg-purple-light', text: 'text-purple', border: 'border-purple-border', dot: 'bg-purple' },
  适合蹭热点: { bg: 'bg-amber-light', text: 'text-amber', border: 'border-amber-border', dot: 'bg-amber' },
  不建议追: { bg: 'bg-gray-100', text: 'text-gray-500', border: 'border-gray-300', dot: 'bg-gray-400' },
  信号不足: { bg: 'bg-gray-50', text: 'text-gray-400', border: 'border-gray-200', dot: 'bg-gray-300' },
};

const TIME_RANGES = [
  { value: '24h', label: '24h' },
  { value: '48h', label: '48h' },
  { value: '7d', label: '7d' },
] as const;
const DEFAULT_TIME_RANGE = '48h';

function normalizeTimeRange(value: string | null) {
  return TIME_RANGES.some((range) => range.value === value) ? value! : DEFAULT_TIME_RANGE;
}

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
  const { toggleFavorite } = useAppContext();

  const [selectedCategory, setSelectedCategory] = useState(searchParams.get('category') || '');
  const [selectedLevel, setSelectedLevel] = useState(searchParams.get('level') || '');
  const [selectedTimeRange, setSelectedTimeRange] = useState(normalizeTimeRange(searchParams.get('time_range')));
  const [items, setItems] = useState<ContentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [dupCount, setDupCount] = useState(0);
  const [loading, setLoading] = useState(true);
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
    updateURL(cat, selectedLevel, selectedTimeRange);
  };
  const setLevel = (level: string) => {
    const next = selectedLevel === level ? '' : level;
    setSelectedLevel(next);
    updateURL(selectedCategory, next, selectedTimeRange);
  };
  const setTimeRange = (tr: string) => {
    setSelectedTimeRange(tr);
    updateURL(selectedCategory, selectedLevel, tr);
  };
  const clearFilters = () => {
    setSelectedCategory('');
    setSelectedLevel('');
    setSelectedTimeRange(DEFAULT_TIME_RANGE);
    updateURL('', '', DEFAULT_TIME_RANGE);
  };

  const fetchPicks = useCallback(async () => {
    try {
      setLoading(true);
      const params: { category?: string; time_range?: string; limit?: number } = {};
      if (selectedCategory) params.category = selectedCategory;
      params.time_range = selectedTimeRange;
      if (selectedTimeRange === '7d') params.limit = 80;
      const res = await contentsApi.todayPicks(params);
      setItems(res.items || []);
      setTotal(res.total || 0);
      setTopics(res.topics || []);
      setDupCount(res.duplicates_hidden || 0);
    } catch (err) {
      console.error('Failed to fetch today picks:', err);
    } finally {
      setLoading(false);
    }
  }, [selectedCategory, selectedTimeRange]);

  useEffect(() => { void fetchPicks(); }, [fetchPicks]);

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
    await toggleFavorite(id);
    contentFavoriteState.refresh();
  };
  const handleStartWorkflow = useCallback(async (item: ContentItem, isFavorited: boolean) => {
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
  }, [contentFavoriteState, router, toggleFavorite]);
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
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-black text-gray-900">当日精选</h1>
              <Badge tone="primary" className="font-mono text-[10px]">
                CURATION DESK
              </Badge>
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
              workflowPending={workflowPendingId === leadItem.id}
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
              workflowPendingId={workflowPendingId}
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
                  workflowPending={workflowPendingId === item.id}
                />
              ))}
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

function OverviewStrip({
  total,
  loadedCount,
  sourceCount,
  topicCount,
  avgScore,
  dupCount,
}: {
  total: number;
  loadedCount: number;
  sourceCount: number;
  topicCount: number;
  avgScore: number;
  dupCount: number;
}) {
  const stats = [
    { label: '精选内容', value: total, hint: loadedCount < total ? `已加载 ${loadedCount}` : '去重后', icon: Target, color: 'text-primary' },
    { label: '平均分', value: avgScore || '-', hint: '算法校准', icon: BarChart3, color: 'text-teal' },
    { label: '话题组', value: topicCount, hint: '聚类结果', icon: Layers3, color: 'text-purple' },
    { label: '来源', value: sourceCount, hint: dupCount ? `隐藏重复 ${dupCount}` : '有效信源', icon: Search, color: 'text-amber' },
  ];

  return (
    <section className="mb-4 grid grid-cols-4 gap-2.5 max-md:grid-cols-2">
      {stats.map((stat) => {
        const Icon = stat.icon;
        return (
          <Panel key={stat.label} className="min-w-0 p-3.5">
            <div className="mb-2.5 flex items-center gap-2">
              <Icon size={15} className={stat.color} strokeWidth={2.2} />
              <span className="text-xs font-bold text-gray-500">{stat.label}</span>
            </div>
            <div className="font-mono text-[28px] font-black leading-none text-gray-900">
              {stat.value}
            </div>
            <div className="mt-1 text-[11px] text-gray-400">{stat.hint}</div>
          </Panel>
        );
      })}
    </section>
  );
}

function LeadPick({
  item,
  isFav,
  onFav,
  onOpen,
  onStartWorkflow,
  workflowPending,
}: {
  item: ContentItem;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  workflowPending: boolean;
}) {
  const analysis = getAnalysis(item);
  const score = scoreOf(item);
  const tags = tagsOf(analysis);
  const recommendation = getRecommendationReason(analysis, item.summary);

  return (
    <Panel className="relative mb-4 overflow-hidden p-6 shadow-[0_16px_38px_rgba(15,23,42,0.06)] before:absolute before:bottom-0 before:left-0 before:top-0 before:w-1 before:bg-gradient-to-b before:from-primary before:to-teal">
      <div className="relative grid grid-cols-[minmax(0,1fr)_110px] gap-5 max-md:grid-cols-1">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge tone="primary" className="gap-1.5">
              <Flame size={13} /> 今日主推
            </Badge>
            <span className="text-[11px] text-gray-500">{item.source_name}</span>
            {tags.slice(0, 3).map((tag) => (
              <span key={tag} className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-bold text-gray-600">
                {tag}
              </span>
            ))}
          </div>
          <h2 className={cx('text-[23px] font-black leading-[1.38] text-gray-900', recommendation && 'mb-2.5')}>
            {item.title}
          </h2>
          {recommendation && (
            <p className="max-w-[680px] text-[13px] leading-7 text-gray-600">
              {recommendation}
            </p>
          )}
          <PickActions
            item={item}
            analysis={analysis}
            isFav={isFav}
            onFav={onFav}
            onOpen={onOpen}
            onStartWorkflow={onStartWorkflow}
            workflowPending={workflowPending}
          />
        </div>
        <div className="flex items-center justify-center rounded-sm border border-primary-border bg-primary-light p-4 max-md:justify-start">
          <div className="text-center max-md:text-left">
            <div className="mb-1 text-[11px] text-gray-500">SCORE</div>
            <div className="font-mono text-[40px] font-black leading-none text-primary">{Math.round(score)}</div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function FilterPanel({
  selectedCategory,
  selectedLevel,
  selectedTimeRange,
  activeFilterCount,
  onCategory,
  onLevel,
  onTimeRange,
  onClear,
}: {
  selectedCategory: string;
  selectedLevel: string;
  selectedTimeRange: string;
  activeFilterCount: number;
  onCategory: (cat: string) => void;
  onLevel: (level: string) => void;
  onTimeRange: (range: string) => void;
  onClear: () => void;
}) {
  return (
    <Panel className="p-4">
      <PanelTitle icon={SlidersHorizontal} title="筛选台" />
      <div className="flex flex-col gap-3.5">
        <div>
          <FilterLabel icon={Clock3}>时间范围</FilterLabel>
          <Segmented values={TIME_RANGES} active={selectedTimeRange} onChange={onTimeRange} />
        </div>
        <div>
          <FilterLabel icon={Target}>推荐等级</FilterLabel>
          <div className="flex flex-col gap-1.5">
            {RECOMMEND_LEVELS.map((level) => {
              const cfg = LEVEL_CONFIG[level];
              const active = selectedLevel === level;
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => onLevel(level)}
                  className={cx(
                    'flex w-full items-center gap-2 rounded-sm border px-2.5 py-2 text-left text-xs transition',
                    active ? `${cfg.bg} ${cfg.text} ${cfg.border} font-black` : 'border-gray-200 bg-white font-semibold text-gray-600 hover:border-gray-300',
                  )}
                >
                  <span className={cx('h-2 w-2 rounded-full', cfg.dot)} />
                  {level}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <FilterLabel icon={Filter}>分类</FilterLabel>
          <div className="flex flex-wrap gap-1.5">
            {(CATEGORIES as readonly string[]).map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => onCategory(cat === '全部' ? '' : cat)}
                className={cx(
                  'rounded-full border px-2.5 py-1 text-xs transition',
                  selectedCategory === cat || (!selectedCategory && cat === '全部')
                    ? 'border-primary-border bg-primary-light font-black text-primary'
                    : 'border-gray-200 bg-white font-semibold text-gray-600 hover:border-gray-300',
                )}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
        {activeFilterCount > 0 && (
          <Button type="button" variant="secondary" onClick={onClear}>
            清除筛选 ({activeFilterCount})
          </Button>
        )}
      </div>
    </Panel>
  );
}

function QualityPanel({
  levelStats,
  total,
}: {
  levelStats: Array<{ level: string; count: number }>;
  total: number;
}) {
  return (
    <Panel className="p-4">
      <PanelTitle icon={BarChart3} title="质量分布" />
      <div className="flex flex-col gap-2.5">
        {levelStats.map(({ level, count }) => {
          const cfg = LEVEL_CONFIG[level];
          const width = total > 0 ? Math.max(6, Math.round((count / total) * 100)) : 0;
          return (
            <div key={level}>
              <div className="mb-1 flex justify-between text-xs text-gray-600">
                <span>{level}</span>
                <span className="font-mono font-black">{count}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                <div className={cx('h-full rounded-full', cfg.dot)} style={{ width: `${width}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function TopicBoard({
  topics,
  topicMap,
  standaloneItems,
  expandedTopics,
  onToggleTopic,
  isFavorited,
  onFav,
  onOpen,
  onStartWorkflow,
  workflowPendingId,
}: {
  topics: TopicInfo[];
  topicMap: Map<number | null, ContentItem[]>;
  standaloneItems: ContentItem[];
  expandedTopics: Set<number>;
  onToggleTopic: (id: number) => void;
  isFavorited: (id: number) => boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  workflowPendingId: number | null;
}) {
  return (
    <div className="flex flex-col gap-3.5 pb-10">
      {topics.map((topic) => {
        const topicItems = topicMap.get(topic.id) || [];
        if (topicItems.length === 0) return null;
        const sortedItems = [...topicItems].sort((a, b) => scoreOf(b) - scoreOf(a));
        const isExpanded = expandedTopics.has(topic.id) || sortedItems.length <= 3;
        const shownItems = isExpanded ? sortedItems : sortedItems.slice(0, 3);
        const hiddenCount = sortedItems.length - 3;
        return (
          <Panel key={topic.id} className="overflow-hidden">
            <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2.5 border-b border-gray-100 bg-[#FBFCFE] px-4.5 py-3.5">
              <div className="min-w-0">
                <div className="text-[15px] font-black leading-snug text-gray-900">{topic.name}</div>
                {topic.summary && <div className="mt-1 truncate text-xs text-gray-500">{topic.summary}</div>}
              </div>
              <Badge tone="primary">
                {topicItems.length} 条
              </Badge>
              <span className="font-mono text-[11px] font-black text-gray-800">
                TOP {Math.round(topic.best_score)}
              </span>
            </div>
            <div className="flex flex-col">
              {shownItems.map((item, idx) => (
                <PickCard
                  key={item.id}
                  item={item}
                  rank={idx + 1}
                  isFav={isFavorited(item.id)}
                  onFav={onFav}
                  onOpen={onOpen}
                  onStartWorkflow={onStartWorkflow}
                  workflowPending={workflowPendingId === item.id}
                  flush
                />
              ))}
            </div>
            {!isExpanded && hiddenCount > 0 && (
              <TopicToggle onClick={() => onToggleTopic(topic.id)} label={`展开剩余 ${hiddenCount} 条`} icon={ChevronDown} />
            )}
            {isExpanded && sortedItems.length > 3 && (
              <TopicToggle onClick={() => onToggleTopic(topic.id)} label="收起" icon={ChevronUp} muted />
            )}
          </Panel>
        );
      })}
      {standaloneItems.length > 0 && (
        <section>
          {topics.length > 0 && <SectionHeading title="其他精选" count={standaloneItems.length} />}
          <div className="flex flex-col gap-2.5">
            {[...standaloneItems].sort((a, b) => scoreOf(b) - scoreOf(a)).map((item, idx) => (
              <PickCard
                key={item.id}
                item={item}
                rank={idx + 1}
                isFav={isFavorited(item.id)}
                onFav={onFav}
                onOpen={onOpen}
                onStartWorkflow={onStartWorkflow}
                workflowPending={workflowPendingId === item.id}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function PickCard({
  item,
  rank,
  isFav,
  onFav,
  onOpen,
  onStartWorkflow,
  workflowPending,
  flush = false,
}: {
  item: ContentItem;
  rank: number;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  workflowPending: boolean;
  flush?: boolean;
}) {
  const analysis = getAnalysis(item);
  const score = scoreOf(item);
  const tags = tagsOf(analysis);
  const recommendation = analysis?.recommendation || analysis?.recommended_reason || item.summary || '';
  const scoreClass = score >= 80 ? 'text-primary' : score >= 70 ? 'text-amber' : 'text-teal';

  return (
    <article
      onClick={() => analysis && onOpen({ ...analysis, _content_id: item.id })}
      className={cx(
        'grid grid-cols-[42px_minmax(0,1fr)_52px] items-start gap-3 px-4.5 py-3.5 transition hover:border-primary-border',
        analysis ? 'cursor-pointer' : 'cursor-default',
        flush ? 'border-b border-gray-100 bg-transparent hover:bg-[#FBFCFE]' : 'rounded-lg border border-gray-200 bg-white',
      )}
    >
      <div className={cx('flex h-8 w-8 items-center justify-center rounded-sm font-mono text-xs font-black', rank <= 3 ? 'bg-primary-light text-primary' : 'bg-gray-100 text-gray-500')}>
        {rank}
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <span className="text-xs font-bold text-gray-500">{item.source_name}</span>
          <span className="text-[11px] text-gray-300">/</span>
          <span className="text-[11px] text-gray-400">{timeAgo(item.published_at || item.crawled_at)}</span>
          {item.category && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">{item.category}</span>}
          {tags.slice(0, 3).map((tag) => (
            <span key={tag} className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ color: getTagColor(tag), background: `${getTagColor(tag)}12` }}>
              {tag}
            </span>
          ))}
        </div>
        <h3 className={cx('text-[15px] font-black leading-[1.45] text-gray-900', recommendation && 'mb-2')}>
          {item.title}
        </h3>
        {recommendation && (
          <p className="mb-2.5 text-xs leading-6 text-gray-500">
            {recommendation}
          </p>
        )}
        <PickActions
          item={item}
          analysis={analysis}
          isFav={isFav}
          onFav={onFav}
          onOpen={onOpen}
          onStartWorkflow={onStartWorkflow}
          workflowPending={workflowPending}
        />
      </div>
      <div className="text-right">
        <div className={cx('font-mono text-[22px] font-black leading-none', scoreClass)}>
          {Math.round(score)}
        </div>
        <div className="mt-1 text-[10px] text-gray-400">分</div>
      </div>
    </article>
  );
}

function PickActions({
  item,
  analysis,
  isFav,
  onFav,
  onOpen,
  onStartWorkflow,
  workflowPending,
  dark = false,
}: {
  item: ContentItem;
  analysis?: ContentAnalysis | null;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  workflowPending: boolean;
  dark?: boolean;
}) {
  const actionClass = dark
    ? 'border-white/15 bg-white/10 text-gray-200 hover:bg-white/15'
    : 'border-gray-200 bg-white text-gray-600 hover:border-primary-border hover:text-primary';
  const linkClass = dark
    ? 'border-white/15 bg-white/10 text-gray-200 hover:bg-white/15'
    : 'border-teal-border bg-teal-light text-teal hover:border-teal-border';

  return (
    <div className={cx('flex flex-wrap items-center gap-2', dark && 'mt-4')}>
      {analysis && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpen({ ...analysis, _content_id: item.id });
          }}
          className={cx('inline-flex items-center gap-1.5 rounded-xs border px-2.5 py-1.5 text-[11px] font-bold transition', actionClass)}
        >
          <Target size={13} /> 分析
        </button>
      )}
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className={cx('inline-flex items-center gap-1.5 rounded-xs border px-2.5 py-1.5 text-[11px] font-bold no-underline transition', linkClass)}
        >
          原文 <ExternalLink size={13} />
        </a>
      )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onFav(item.id);
        }}
        className={cx(
          'inline-flex items-center gap-1.5 rounded-xs border px-2.5 py-1.5 text-[11px] font-bold transition',
          dark ? 'border-white/15 bg-white/10 hover:bg-white/15' : 'border-gray-200 bg-white hover:border-amber-border',
          isFav ? 'text-amber' : dark ? 'text-gray-300' : 'text-gray-400',
        )}
      >
        <Star size={13} fill={isFav ? '#F59E0B' : 'none'} /> 收藏
      </button>
      <button
        type="button"
        disabled={workflowPending}
        onClick={(e) => {
          e.stopPropagation();
          onStartWorkflow(item, isFav);
        }}
        className={cx(
          'inline-flex items-center gap-1.5 rounded-xs border px-2.5 py-1.5 text-[11px] font-bold transition disabled:cursor-wait disabled:opacity-60',
          dark ? 'border-white/15 bg-white/10 text-white hover:bg-white/15' : 'border-primary bg-primary text-white hover:bg-primary-hover',
        )}
      >
        <PenLine size={13} />
        {workflowPending ? '推进中' : '推进'}
      </button>
    </div>
  );
}

function Segmented({
  values,
  active,
  onChange,
}: {
  values: readonly { value: string; label: string }[];
  active: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-1 rounded-sm bg-gray-100 p-1" style={{ gridTemplateColumns: `repeat(${values.length}, 1fr)` }}>
      {values.map((item) => {
        const selected = active === item.value;
        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            className={cx(
              'rounded-xs border border-transparent py-1.5 text-[11px] transition',
              selected ? 'bg-white font-black text-primary shadow-sm' : 'bg-transparent font-bold text-gray-500 hover:text-gray-800',
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

function PanelTitle({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return (
    <div className="mb-3.5 flex items-center gap-2">
      <Icon size={15} className="text-primary" strokeWidth={2.2} />
      <span className="text-sm font-black text-gray-900">{title}</span>
    </div>
  );
}

function FilterLabel({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-[11px] font-black text-gray-500">
      <Icon size={12} strokeWidth={2.2} />
      {children}
    </div>
  );
}

function TopicToggle({
  onClick,
  label,
  icon: Icon,
  muted = false,
}: {
  onClick: () => void;
  label: string;
  icon: typeof ChevronDown;
  muted?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx('w-full bg-[#FBFCFE] p-2.5 text-xs font-black transition hover:bg-primary-light', muted ? 'text-gray-400' : 'text-primary')}
    >
      <span className="inline-flex items-center gap-1.5">
        {label}
        <Icon size={13} strokeWidth={2} />
      </span>
    </button>
  );
}

function SectionHeading({ title, count }: { title: string; count: number }) {
  return (
    <div className="mb-2.5 mt-1 flex items-center gap-2">
      <h2 className="text-sm font-black text-gray-800">{title}</h2>
      <span className="font-mono text-[11px] text-gray-400">{count}</span>
    </div>
  );
}

function getAnalysis(item: ContentItem): ContentAnalysis | undefined {
  return item.analysis || item.analyses?.[0];
}

function scoreOf(item: ContentItem): number {
  const analysis = getAnalysis(item);
  return analysis?.adjusted_curation_score || analysis?.curation_score || 0;
}

function tagsOf(analysis?: ContentAnalysis | null): string[] {
  const rawTags = analysis?.tags as string | string[] | null | undefined;
  if (Array.isArray(rawTags)) return rawTags;
  if (typeof rawTags === 'string' && rawTags) return rawTags.split(',').map((tag) => tag.trim()).filter(Boolean);
  return [];
}
