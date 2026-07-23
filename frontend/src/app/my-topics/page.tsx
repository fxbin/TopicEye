'use client';

import React, { useCallback, useMemo, useState } from 'react';
import {
  ArrowRight,
  BookmarkCheck,
  BookOpen,
  Compass,
  ExternalLink,
  Filter,
  Pin,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Star,
  Target,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Metric, Panel, Toolbar, cx } from '@/components/ui';
import { LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { motherTopicsApi, contentsApi, type MotherTopic, type ContentItem } from '@/lib/api';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import { parseUTC } from '@/lib/datetime';
import { useEffect, useRef } from 'react';

interface TopicScore {
  name: string;
  keyword_score: number;
  weight: number;
  freshness: number;
  final: number;
}

interface ScoredContent {
  content: ContentItem;
  scoring: {
    final_score: number;
    top_topic: string | null;
    topic_scores: TopicScore[];
  } | null;
}

type ScoreTone = 'primary' | 'teal' | 'amber' | 'neutral';

const toneClass: Record<ScoreTone, { text: string; bg: string; border: string; bar: string; label: string }> = {
  primary: {
    text: 'text-primary',
    bg: 'bg-primary-light',
    border: 'border-primary-border',
    bar: 'bg-primary',
    label: '主推',
  },
  amber: {
    text: 'text-amber',
    bg: 'bg-amber-light',
    border: 'border-amber-border',
    bar: 'bg-amber',
    label: '储备',
  },
  teal: {
    text: 'text-teal',
    bg: 'bg-teal-light',
    border: 'border-teal-border',
    bar: 'bg-teal',
    label: '观察',
  },
  neutral: {
    text: 'text-gray-500',
    bg: 'bg-gray-50',
    border: 'border-gray-200',
    bar: 'bg-gray-400',
    label: '低相关',
  },
};

function normalizeScore(raw: number): number {
  return Math.min(Math.round(raw * (100 / 1.1)), 100);
}

function getScoreTone(score: number): ScoreTone {
  if (score >= 80) return 'primary';
  if (score >= 65) return 'amber';
  if (score >= 45) return 'teal';
  return 'neutral';
}

function formatDate(value?: string | null) {
  if (!value) return '未知时间';
  // 后端 datetime 经 isoformat 序列化会带 +00:00 时区偏移，直接补 'Z' 会得到非法串；
  // 统一走 parseUTC（兼容裸串 / Z / +00:00 三种形态），避免解析失败被误判成「未知时间」。
  const date = parseUTC(value);
  if (Number.isNaN(date.getTime())) return '未知时间';
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function matchedScores(item: ScoredContent) {
  return (item.scoring?.topic_scores || [])
    .filter((score) => score.final > 0)
    .sort((a, b) => b.final - a.final);
}

function scoreForTopic(item: ScoredContent, topicName: string) {
  return item.scoring?.topic_scores.find((score) => score.name === topicName)?.final || 0;
}

function TopicNavItem({
  topic,
  active,
  count,
  bestScore,
  onClick,
}: {
  topic: MotherTopic;
  active: boolean;
  count: number;
  bestScore: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 rounded-sm border p-3 text-left transition',
        active ? 'border-primary-border bg-primary-light' : 'border-gray-200 bg-white hover:border-primary-border hover:bg-primary-light/60',
      )}
    >
      <span className="min-w-0">
        <span className={cx('block truncate text-[13px] font-black', active ? 'text-primary' : 'text-gray-900')}>
          {topic.name}
        </span>
        <span className="mt-1 block truncate text-[11px] font-bold text-gray-400">
          {count} 条匹配 / 最高 {bestScore}
        </span>
      </span>
      <span className={cx(
        'grid h-8 w-8 place-items-center rounded-xs font-mono text-xs font-black',
        active ? 'bg-primary text-white' : 'bg-gray-100 text-gray-600',
      )}>
        {count}
      </span>
    </button>
  );
}

function ContentCard({
  item,
  isFavorite,
  onToggle,
  onRead,
}: {
  item: ScoredContent;
  isFavorite: boolean;
  onToggle: (id: number) => void | Promise<void>;
  onRead: (id: number) => void;
}) {
  const score = normalizeScore(item.scoring?.final_score || 0);
  const tone = toneClass[getScoreTone(score)];
  const matches = matchedScores(item);
  const topTopic = item.scoring?.top_topic;
  const summary = item.content.summary || item.content.raw_content || '';

  return (
    <Panel className="p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="grid grid-cols-[62px_minmax(0,1fr)] gap-3.5">
        <div className={cx('flex h-[62px] flex-col items-center justify-center rounded-sm border', tone.bg, tone.border)}>
          <div className={cx('font-mono text-2xl font-black leading-none', tone.text)}>{score}</div>
          <div className={cx('mt-1 text-[10px] font-black', tone.text)}>{tone.label}</div>
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-xs font-black text-gray-600">{item.content.source_name || '未知来源'}</span>
            <span className="text-xs text-gray-300">/</span>
            <span className="text-xs text-gray-400">{formatDate(item.content.published_at || item.content.crawled_at || item.content.created_at)}</span>
            {topTopic && <Badge tone="primary" className="px-2 py-0.5">{topTopic}</Badge>}
          </div>

          <h3 className="m-0 text-base font-black leading-6 text-gray-900">{item.content.title}</h3>

          {summary && (
            <p className="line-clamp-2 mt-2 text-[13px] leading-6 text-gray-500">
              {summary}
            </p>
          )}
        </div>
      </div>

      {matches.length > 0 && (
        <div className="mt-3.5 border-t border-gray-100 pt-3">
          <div className="grid gap-2">
            {matches.slice(0, 3).map((match) => {
              const value = normalizeScore(match.final);
              const matchTone = toneClass[getScoreTone(value)];
              return (
                <div key={match.name} className="grid grid-cols-[82px_minmax(0,1fr)_40px] items-center gap-2.5">
                  <div className={cx('truncate text-[11px] font-black', match.name === topTopic ? 'text-primary' : 'text-gray-500')}>
                    {match.name}
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                    <div className={cx('h-full rounded-full', matchTone.bar)} style={{ width: `${value}%` }} />
                  </div>
                  <div className="text-right font-mono text-[11px] font-black text-gray-700">{value}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="mt-3.5 flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {item.content.category && <Badge tone="neutral" className="px-2 py-0.5">{item.content.category}</Badge>}
          {(item.content.tags || []).slice(0, 3).map((tag) => (
            <span key={tag} className="text-[11px] text-gray-400">#{tag}</span>
          ))}
        </div>

        <Toolbar>
          {item.content.url && (
            <button
              type="button"
              onClick={() => onRead(item.content.id)}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-xs border border-primary-border bg-primary-light px-2.5 py-1.5 text-xs font-black text-primary"
            >
              <BookOpen size={13} /> 阅读
            </button>
          )}
          {item.content.url && (
            <a
              href={item.content.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-8 items-center gap-1.5 rounded-xs border border-teal-border bg-teal-light px-2.5 py-1.5 text-xs font-black text-teal no-underline"
            >
              原文 <ExternalLink size={13} />
            </a>
          )}
          <button
            type="button"
            onClick={() => onToggle(item.content.id)}
            title={isFavorite ? '取消收藏' : '收藏'}
            className={cx(
              'grid h-8 w-8 place-items-center rounded-xs border transition',
              isFavorite ? 'border-primary-border bg-primary-light text-primary' : 'border-gray-200 bg-white text-gray-400 hover:border-primary-border hover:text-primary',
            )}
          >
            <Star size={15} strokeWidth={2.1} fill={isFavorite ? 'currentColor' : 'none'} />
          </button>
        </Toolbar>
      </div>
    </Panel>
  );
}

type TopicsPayload = { topics: MotherTopic[]; scored: ScoredContent[] };

export default function MyTopicsPage() {
  const [selectedTopic, setSelectedTopic] = useState('');
  const [filterMinScore, setFilterMinScore] = useState(45);
  const { toggleFavorite, openReader } = useAppContext();

  const { data, loading, refetch } = useFetch<TopicsPayload>(async () => {
    const [topicList, contentPage] = await Promise.all([
      motherTopicsApi.list(true),
      contentsApi.list({ page: 1, page_size: 200, include_trend_sources: false }),
    ]);

    let scored: ScoredContent[];
    try {
      const { results } = await motherTopicsApi.scoreBatch(
        (contentPage.items || []).map((content) => ({
          title: content.title,
          summary: content.summary || '',
          hot_value: 0,
        }))
      );
      const resultMap = new Map(results.map((result) => [result.title, result]));
      scored = (contentPage.items || []).map((content) => ({
        content,
        scoring: resultMap.get(content.title) ?? null,
      }));
    } catch {
      scored = (contentPage.items || []).map((content) => ({ content, scoring: null }));
    }

    scored.sort((a, b) => (b.scoring?.final_score || 0) - (a.scoring?.final_score || 0));
    return { topics: topicList, scored };
  }, []);

  // 首次进入时懒触发 fork：如果用户还没有自己的母题，fork 一份系统模板
  const forkTriggeredRef = useRef(false);
  useEffect(() => {
    if (forkTriggeredRef.current) return;
    forkTriggeredRef.current = true;
    (async () => {
      try {
        const ts = await motherTopicsApi.list(true);
        const hasOwn = ts.some(t => t.owner_user_id !== null);
        if (!hasOwn) {
          await motherTopicsApi.forkDefaults();
          refetch();
        }
      } catch {
        // fork 失败不阻塞页面——用户仍能看到系统模板的打分结果
      }
    })();
  }, [refetch]);

  const topics = data?.topics ?? [];
  const allScored = data?.scored ?? [];

  const matchedItems = useMemo(() => (
    allScored.filter((item) => (item.scoring?.final_score || 0) > 0)
  ), [allScored]);

  const filtered = useMemo(() => matchedItems.filter((item) => {
    const topicScore = selectedTopic ? scoreForTopic(item, selectedTopic) : item.scoring?.final_score || 0;
    if (normalizeScore(topicScore) < filterMinScore) return false;
    if (!selectedTopic) return true;
    return topicScore > 0;
  }), [matchedItems, selectedTopic, filterMinScore]);

  const topicStats = useMemo(() => topics.map((topic) => {
    const related = matchedItems.filter((item) => scoreForTopic(item, topic.name) > 0);
    const best = related.reduce((max, item) => Math.max(max, normalizeScore(scoreForTopic(item, topic.name))), 0);
    return { topic, count: related.length, best };
  }), [topics, matchedItems]);

  const mainCount = matchedItems.filter((item) => normalizeScore(item.scoring?.final_score || 0) >= 80).length;
  const reserveCount = matchedItems.filter((item) => {
    const score = normalizeScore(item.scoring?.final_score || 0);
    return score >= 65 && score < 80;
  }).length;
  const avgScore = matchedItems.length
    ? Math.round(matchedItems.reduce((sum, item) => sum + normalizeScore(item.scoring?.final_score || 0), 0) / matchedItems.length)
    : 0;
  const selectedTopicMeta = topics.find((topic) => topic.name === selectedTopic);
  const visibleContentIds = useMemo(() => filtered.map((item) => item.content.id), [filtered]);
  const contentFavoriteState = useContentFavoriteStates(visibleContentIds);

  const handleToggleFavorite = useCallback(async (id: number) => {
    await toggleFavorite(id);
    contentFavoriteState.refresh();
  }, [contentFavoriteState, toggleFavorite]);

  return (
    <div className="h-full overflow-y-auto bg-[linear-gradient(180deg,#F8FAFC_0%,#F4F6F8_44%,#EEF2F5_100%)] px-4 pb-8 sm:px-6 lg:px-10">
      <header className="sticky top-0 z-10 -mx-4 border-b border-gray-200 bg-[#F8FAFC]/90 px-4 py-4 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div className="mx-auto flex max-w-[1220px] flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <Pin size={18} className="text-primary" strokeWidth={2.2} />
              <h1 className="m-0 text-xl font-black text-gray-900">我的母题</h1>
              <Badge tone="primary" className="font-mono text-[10px]">TOPIC DESK</Badge>
            </div>
            <p className="mt-1.5 text-xs leading-5 text-gray-500">
              用母题定位筛选内容，把内容池收敛成可持续写作的候选队列
            </p>
          </div>
          <a
            href="/my-topics/config"
            className="inline-flex min-h-9 items-center gap-1.5 rounded-sm bg-primary px-3 py-2 text-xs font-black text-white no-underline hover:bg-primary-hover"
          >
            <Settings2 size={14} /> 配置母题
          </a>
        </div>
      </header>

      <main className="mx-auto mt-5 grid max-w-[1220px] grid-cols-1 items-start gap-4 lg:grid-cols-[286px_minmax(0,1fr)]">
        <aside className="flex flex-col gap-3.5 lg:sticky lg:top-[92px]">
          <Panel className="p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-[13px] font-black text-gray-900">
                <Compass size={15} className="text-primary" /> 母题导航
              </div>
              <button
                type="button"
                onClick={() => setSelectedTopic('')}
                className={cx(
                  'rounded-full border px-2 py-1 text-[11px] font-black transition',
                  selectedTopic ? 'border-gray-200 bg-white text-gray-500 hover:border-primary-border hover:text-primary' : 'border-primary-border bg-primary-light text-primary',
                )}
              >
                全部
              </button>
            </div>

            <div className="grid gap-2">
              {topicStats.map(({ topic, count, best }) => (
                <TopicNavItem
                  key={topic.id}
                  topic={topic}
                  count={count}
                  bestScore={best}
                  active={selectedTopic === topic.name}
                  onClick={() => setSelectedTopic(topic.name)}
                />
              ))}
            </div>
          </Panel>

          <Panel className="p-4">
            <div className="mb-3 flex items-center gap-1.5 text-[13px] font-black text-gray-900">
              <SlidersHorizontal size={15} className="text-teal" /> 匹配阈值
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={filterMinScore}
              onChange={(event) => setFilterMinScore(Number(event.target.value))}
              className="w-full accent-primary"
            />
            <div className="mt-2 flex items-center justify-between">
              <span className="text-[11px] text-gray-400">最低得分</span>
              <span className="font-mono text-lg font-black text-primary">{filterMinScore}</span>
            </div>
          </Panel>

          {selectedTopicMeta && (
            <Panel className="border-primary-border bg-primary-light p-4">
              <div className="mb-2 text-[13px] font-black text-primary">{selectedTopicMeta.name}</div>
              <div className="text-xs leading-6 text-gray-600">
                {selectedTopicMeta.description || selectedTopicMeta.target_reader || '这个母题还没有配置描述。'}
              </div>
              {selectedTopicMeta.keywords.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selectedTopicMeta.keywords.slice(0, 8).map((keyword) => (
                    <Badge key={keyword} tone="primary" className="bg-white px-2 py-0.5">
                      {keyword}
                    </Badge>
                  ))}
                </div>
              )}
            </Panel>
          )}
        </aside>

        <section className="min-w-0">
          <div className="mb-3 grid grid-cols-2 gap-2.5 min-[1320px]:grid-cols-4">
            <Metric label="匹配内容" value={matchedItems.length} colorClass="text-gray-900" />
            <Metric label="主推候选" value={mainCount} colorClass="text-primary" />
            <Metric label="储备候选" value={reserveCount} colorClass="text-amber" />
            <Metric label="平均匹配" value={avgScore} colorClass="text-teal" />
          </div>

          <Panel className="mb-3 flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-black text-gray-900">
                <Target size={15} className="text-primary" />
                {selectedTopic || '全部母题'}候选
              </div>
              <div className="mt-1 text-xs text-gray-400">
                当前显示 {filtered.length} 条，按母题最终得分降序排列
              </div>
            </div>
            <Button type="button" onClick={() => void refetch()} disabled={loading} variant="secondary">
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> 重新打分
            </Button>
          </Panel>

          {loading ? (
            <LoadingState label="正在按母题打分…" minHeight="260px" />
          ) : filtered.length === 0 ? (
            <Panel className="grid min-h-[260px] place-items-center p-9 text-center">
              <div>
                <Filter size={28} className="mx-auto text-gray-300" strokeWidth={1.8} />
                <div className="mt-3 text-sm font-black text-gray-700">没有符合条件的母题候选</div>
                <div className="mt-1.5 text-xs text-gray-400">降低匹配阈值，或去配置页补充关键词。</div>
                <a
                  href="/my-topics/config"
                  className="mt-3.5 inline-flex items-center gap-1.5 text-xs font-black text-primary no-underline"
                >
                  调整母题配置 <ArrowRight size={13} />
                </a>
              </div>
            </Panel>
          ) : (
            <div className="grid gap-3">
              {filtered.map((item) => (
                <ContentCard
                  key={item.content.id}
                  item={item}
                  isFavorite={contentFavoriteState.isFavorited(item.content.id)}
                  onToggle={handleToggleFavorite}
                  onRead={openReader}
                />
              ))}
            </div>
          )}

          <Panel className="mt-3.5 flex flex-wrap items-center justify-between gap-3 border-teal-border bg-teal-light px-4 py-3.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <BookmarkCheck size={18} className="shrink-0 text-teal" strokeWidth={2.2} />
              <div className="min-w-0">
                <div className="text-[13px] font-black text-gray-900">母题配置会直接影响候选队列</div>
                <div className="mt-0.5 text-xs text-gray-500">关键词、权重和目标读者越清晰，匹配队列越稳定。</div>
              </div>
            </div>
            <a
              href="/my-topics/config"
              className="inline-flex min-h-9 items-center gap-1.5 rounded-sm border border-teal-border bg-white px-3 py-2 text-xs font-black text-teal no-underline"
            >
              去配置 <ArrowRight size={13} />
            </a>
          </Panel>
        </section>
      </main>
    </div>
  );
}
