'use client';

import React, { useMemo, useState } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  ExternalLink,
  Filter,
  Hash,
  Layers3,
  Loader2,
  Radio,
  Tags,
  Target,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Badge, Button, Metric, Panel, PanelTitle, cx } from '@/components/ui';
import { CHART_COLORS } from '@/lib/design-tokens';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { trendsApi, type TrendPoint, type TrendKeywordItem as KeywordItem } from '@/lib/api';

interface TopicSeries {
  key: string;
  name: string;
  pts: TrendPoint[];
  total: number;
  picks: number;
  latestCount: number;
  previousCount: number;
  delta: number;
  momentum: number;
  maxScore: number;
  topItems: { title: string; url: string; score: number }[];
}

// 色板统一引用 @/lib/design-tokens 的 CHART_COLORS（10 色无重复）。
// 历史本地常量 COLORS 已删除，改用 CHART_COLORS 别名保持调用方不变。
const COLORS = CHART_COLORS;

function Sparkline({
  data,
  color = '#FF6B35',
  width = 132,
  height = 42,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  if (data.length < 2) {
    return <span className="text-[11px] text-gray-300">-</span>;
  }

  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const points = data.map((value, index) => {
    const x = index * step;
    const y = height - 5 - ((value - min) / range) * (height - 12);
    return `${x},${y}`;
  });
  const area = `${points.join(' ')} ${width},${height} 0,${height}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block">
      <polygon points={area} fill={`${color}14`} />
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MiniBars({
  dates,
  counts,
  color,
  maxCount,
}: {
  dates: string[];
  counts: number[];
  color: string;
  maxCount: number;
}) {
  return (
    <div
      className="grid h-[58px] items-end gap-1.5"
      style={{ gridTemplateColumns: `repeat(${Math.max(dates.length, 1)}, minmax(0, 1fr))` }}
    >
      {dates.map((date, index) => {
        const count = counts[index] || 0;
        const height = count ? Math.max(8, (count / maxCount) * 50) : 3;
        return (
          <div key={date} className="flex h-[58px] min-w-0 flex-col justify-end">
            <div
              title={`${date}: ${count} 条`}
              className="rounded-t-xs rounded-b-[2px]"
              style={{
                height,
                background: count ? color : '#E5E7EB',
                opacity: count ? 0.82 : 0.45,
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

function MomentumBadge({ delta }: { delta: number }) {
  const rising = delta > 0;
  const flat = delta === 0;
  const Icon = flat ? Activity : rising ? ArrowUpRight : ArrowDownRight;

  return (
    <Badge tone={flat ? 'neutral' : rising ? 'primary' : 'teal'} className="gap-1 px-2 py-0.5">
      <Icon size={12} strokeWidth={2.4} />
      {flat ? '持平' : `${rising ? '+' : ''}${delta}`}
    </Badge>
  );
}

function TopicCard({
  topic,
  dates,
  maxCount,
  color,
  rank,
}: {
  topic: TopicSeries;
  dates: string[];
  maxCount: number;
  color: string;
  rank: number;
}) {
  const counts = dates.map((date) => topic.pts.find((point) => point.date === date)?.content_count || 0);

  return (
    <Panel className="overflow-hidden shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-start gap-3 px-4.5 py-4">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-sm font-mono text-xs font-black"
          style={{ background: `${color}14`, color }}
        >
          {rank}
        </div>
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <h2 className="m-0 text-base font-black leading-5 text-gray-900">{topic.name}</h2>
            <MomentumBadge delta={topic.delta} />
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-400">
            <span>{topic.total} 条内容</span>
            <span>{topic.picks} 条精选</span>
            <span>峰值 {Math.round(topic.maxScore)}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-[26px] font-black leading-none" style={{ color }}>
            {topic.latestCount}
          </div>
          <div className="mt-1 font-mono text-[10px] text-gray-400">LATEST</div>
        </div>
      </div>

      <div className="grid items-end gap-4 px-4.5 pb-4 pl-[72px] sm:grid-cols-[150px_minmax(0,1fr)]">
        <Sparkline data={counts} color={color} />
        <MiniBars dates={dates} counts={counts} color={color} maxCount={maxCount} />
      </div>

      {topic.topItems.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-gray-100 px-4.5 py-3 pl-[72px]">
          {topic.topItems.slice(0, 2).map((item, index) => (
            <a
              key={`${item.title}-${index}`}
              href={item.url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-xs leading-5 text-gray-600 no-underline hover:text-gray-900"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />
              <span className="min-w-0 flex-1 truncate">{item.title}</span>
              <span className="font-mono font-black" style={{ color }}>{Math.round(item.score)}</span>
              <ExternalLink size={12} className="shrink-0 text-gray-400" />
            </a>
          ))}
        </div>
      )}
    </Panel>
  );
}

function KeywordBoard({ keywords }: { keywords: KeywordItem[] }) {
  if (keywords.length === 0) {
    return <EmptyState icon={Filter} title="暂无关键词数据" desc="等待趋势快照生成后会出现关键词频率。" />;
  }

  const max = keywords[0]?.count || 1;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {keywords.slice(0, 48).map((keyword, index) => {
        const ratio = keyword.count / max;
        const color = COLORS[index % COLORS.length];
        return (
          <Panel key={keyword.keyword} className="p-3.5">
            <div className="mb-2.5 flex items-center justify-between gap-3">
              <span className="truncate text-sm font-black text-gray-900">{keyword.keyword}</span>
              <span className="font-mono text-xs font-black" style={{ color }}>{keyword.count}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.max(8, Math.round(ratio * 100))}%`, background: color }}
              />
            </div>
          </Panel>
        );
      })}
    </div>
  );
}

function ControlPanel({
  days,
  setDays,
  activeTab,
  setActiveTab,
}: {
  days: number;
  setDays: (days: number) => void;
  activeTab: 'topics' | 'keywords';
  setActiveTab: (tab: 'topics' | 'keywords') => void;
}) {
  return (
    <Panel className="p-4">
      <PanelTitle icon={CalendarDays} title="观察窗口" />
      <div className="mb-3.5 grid grid-cols-4 gap-1 rounded-sm bg-gray-100 p-1">
        {[3, 7, 14, 30].map((value) => {
          const active = days === value;
          return (
            <button
              key={value}
              type="button"
              onClick={() => setDays(value)}
              className={cx(
                'rounded-xs px-1 py-1.5 text-[11px] font-black transition',
                active ? 'bg-white text-primary shadow-[0_1px_3px_rgba(15,23,42,0.08)]' : 'text-gray-500 hover:text-gray-800',
              )}
            >
              {value}天
            </button>
          );
        })}
      </div>

      <div className="flex flex-col gap-2">
        {[
          { key: 'topics' as const, label: '话题曲线', icon: BarChart3 },
          { key: 'keywords' as const, label: '关键词频率', icon: Tags },
        ].map((item) => {
          const Icon = item.icon;
          const active = activeTab === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setActiveTab(item.key)}
              className={cx(
                'flex items-center gap-2 rounded-sm border px-2.5 py-2 text-xs font-black transition',
                active ? 'border-primary-border bg-primary-light text-primary' : 'border-gray-200 bg-white text-gray-600 hover:border-primary-border hover:text-primary',
              )}
            >
              <Icon size={14} />
              {item.label}
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

function KeywordPanel({ keywords }: { keywords: KeywordItem[] }) {
  return (
    <Panel className="p-4">
      <PanelTitle icon={Hash} title="高频热词" />
      <div className="flex flex-wrap gap-1.5">
        {keywords.slice(0, 18).map((keyword, index) => {
          const color = COLORS[index % COLORS.length];
          return (
            <span
              key={keyword.keyword}
              className="rounded-full border px-2 py-1 text-[11px] font-black"
              style={{ color, background: `${color}10`, borderColor: `${color}22` }}
            >
              {keyword.keyword}
            </span>
          );
        })}
        {keywords.length === 0 && <span className="text-xs text-gray-400">暂无热词</span>}
      </div>
    </Panel>
  );
}

function SignalPanel({ topics }: { topics: TopicSeries[] }) {
  const rising = topics.filter((topic) => topic.delta > 0).length;
  const cooling = topics.filter((topic) => topic.delta < 0).length;
  const stable = topics.length - rising - cooling;
  const rows = [
    { label: '升温', value: rising, dotClass: 'bg-primary' },
    { label: '降温', value: cooling, dotClass: 'bg-teal' },
    { label: '稳定', value: stable, dotClass: 'bg-gray-500' },
  ];

  return (
    <Panel className="p-4">
      <PanelTitle icon={Radio} title="信号面板" />
      <div className="flex flex-col gap-2.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2.5">
            <span className={cx('h-2 w-2 rounded-full', row.dotClass)} />
            <span className="flex-1 text-xs text-gray-600">{row.label}</span>
            <span className="font-mono text-[13px] font-black text-gray-900">{row.value}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function buildTopicSeries(trends: TrendPoint[]): TopicSeries[] {
  const byTopic = new Map<string, { name: string; pts: TrendPoint[]; total: number; picks: number }>();
  for (const point of trends) {
    const key = `${point.topic_id}:${point.topic_name}`;
    if (!byTopic.has(key)) {
      byTopic.set(key, { name: point.topic_name, pts: [], total: 0, picks: 0 });
    }
    const entry = byTopic.get(key)!;
    entry.pts.push(point);
    entry.total += point.content_count;
    entry.picks += point.pick_count;
  }

  return Array.from(byTopic.entries()).map(([key, entry]) => {
    const pts = [...entry.pts].sort((a, b) => a.date.localeCompare(b.date));
    const latest = pts[pts.length - 1];
    const previous = pts[pts.length - 2];
    const latestCount = latest?.content_count || 0;
    const previousCount = previous?.content_count || 0;
    const maxScore = Math.max(...pts.map((point) => point.max_score || 0), 0);
    const topItems = pts
      .flatMap((point) => point.top_items || [])
      .sort((a, b) => b.score - a.score);
    return {
      key,
      name: entry.name,
      pts,
      total: entry.total,
      picks: entry.picks,
      latestCount,
      previousCount,
      delta: latestCount - previousCount,
      momentum: latestCount + Math.max(0, latestCount - previousCount) * 2 + entry.picks,
      maxScore,
      topItems,
    };
  }).sort((a, b) => b.momentum - a.momentum);
}

export default function TrendsPage() {
  const [days, setDays] = useState(7);
  const [activeTab, setActiveTab] = useState<'topics' | 'keywords'>('topics');

  type TrendsPayload = { trends: TrendPoint[]; keywords: KeywordItem[] };
  const { data, loading, error, refetch } = useFetch<TrendsPayload>(
    async () => {
      const [topicData, keywordData] = await Promise.all([
        trendsApi.topics(days),
        trendsApi.keywords({ days, limit: 60 }),
      ]);
      return {
        trends: topicData.trends || [],
        keywords: keywordData.keywords || [],
      };
    },
    [days],
  );

  const trends = data?.trends ?? [];
  const keywords = data?.keywords ?? [];

  const topicSeries = useMemo(() => buildTopicSeries(trends), [trends]);
  const sortedTopics = topicSeries.slice(0, 15);
  const dates = useMemo(() => Array.from(new Set(trends.map((trend) => trend.date))).sort(), [trends]);
  const maxCount = Math.max(...sortedTopics.flatMap((topic) => topic.pts.map((point) => point.content_count)), 1);
  const totalTopics = topicSeries.length;
  const totalPicks = trends.reduce((sum, trend) => sum + trend.pick_count, 0);
  const totalContent = trends.reduce((sum, trend) => sum + trend.content_count, 0);
  const topMomentum = sortedTopics[0]?.momentum || 0;

  return (
    <div className="fade-in h-full overflow-y-auto bg-[linear-gradient(180deg,#F8FAFC_0%,#F4F6F8_42%,#EEF2F5_100%)] px-4 pb-8 sm:px-6 lg:px-10">
      <header className="sticky top-0 z-10 -mx-4 border-b border-gray-200 bg-[#F8FAFC]/90 px-4 py-4 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="m-0 text-xl font-black text-gray-900">趋势追踪</h1>
              <Badge tone="teal" className="font-mono text-[10px]">TREND LAB</Badge>
            </div>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              追踪话题热度、精选转化和关键词信号
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <CalendarDays size={14} />
            近 <b className="font-mono text-teal">{days}</b> 天
          </div>
        </div>
      </header>

      <div className="mx-auto mt-5 grid max-w-[1180px] grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_250px]">
        {error && (
          <div className="col-span-full">
            <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
          </div>
        )}
        <main className="min-w-0">
          <section className="mb-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="话题数" value={totalTopics} colorClass="text-primary" icon={<Layers3 size={15} className="text-primary" />} />
            <Metric label="精选内容" value={totalPicks} colorClass="text-amber" icon={<Target size={15} className="text-amber" />} />
            <Metric label="内容总量" value={totalContent} colorClass="text-teal" icon={<Activity size={15} className="text-teal" />} />
            <Metric label="最强动量" value={topMomentum} colorClass="text-purple" icon={<Radio size={15} className="text-purple" />} />
          </section>

          {loading ? (
            <LoadingState label="加载中…" minHeight="320px" />
          ) : activeTab === 'topics' ? (
            sortedTopics.length === 0 ? (
              <EmptyState icon={Filter} title="暂无趋势数据" desc="趋势快照生成后会在这里展示话题曲线。" />
            ) : (
              <div className="flex flex-col gap-3">
                {sortedTopics.map((topic, index) => (
                  <TopicCard
                    key={topic.key}
                    topic={topic}
                    dates={dates}
                    maxCount={maxCount}
                    color={COLORS[index % COLORS.length]}
                    rank={index + 1}
                  />
                ))}
              </div>
            )
          ) : (
            <KeywordBoard keywords={keywords} />
          )}
        </main>

        <aside className="flex flex-col gap-3.5 xl:sticky xl:top-[88px]">
          <ControlPanel days={days} setDays={setDays} activeTab={activeTab} setActiveTab={setActiveTab} />
          <SignalPanel topics={sortedTopics} />
          <KeywordPanel keywords={keywords} />
          <Button type="button" variant="secondary" onClick={() => void refetch()} disabled={loading} className="w-full">
            <Loader2 size={13} className={loading ? 'animate-spin' : 'hidden'} />
            刷新趋势
          </Button>
        </aside>
      </div>
    </div>
  );
}
