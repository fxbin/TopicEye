/**
 * Today picks page 展示组件集合（无业务逻辑，纯 props 驱动）。
 *
 * 从 app/today-picks/page.tsx 抽出：
 * - OverviewStrip      统计条（页面特化布局，4 格 Panel）
 * - LeadPick           今日主推卡片
 * - FilterPanel        筛选台（时间范围 + 等级 + 分类）
 * - QualityPanel       质量分布条形图
 * - TopicBoard         话题分组看板
 * - PickCard           选题卡片（含评分展开）
 * - PickActions        卡片操作按钮组
 * - TopicToggle        话题展开/收起按钮
 * - SectionHeading     分区标题
 *
 * page.tsx 通过 import 使用这些组件，保持主体只含数据获取与状态编排。
 */

'use client';

import React, { useState } from 'react';
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Filter,
  Flame,
  Layers3,
  PenLine,
  Search,
  SlidersHorizontal,
  Star,
  Target,
  Clock3,
} from 'lucide-react';
import { Badge, Button, Panel, PanelTitle, Segmented, FilterLabel, cx } from '@/components/ui';
import SourceBadge from '@/components/SourceBadge';
import ScoreBreakdownChart from '@/components/ScoreBreakdownChart';
import EvidenceTag from '@/components/EvidenceTag';
import {
  CATEGORIES,
  RECOMMEND_LEVELS,
  LEVEL_CONFIG,
  TIME_RANGES,
  getAnalysis,
  scoreOf,
  tagsOf,
} from './_today-picks-utils';
import { getTagColor, timeAgo } from '@/lib/utils';
import { getRecommendationReason } from '@/lib/recommendation';
import type { ContentAnalysis, ContentItem, EvidenceMark, TopicInfo } from '@/types';

// ─── OverviewStrip ───────────────────────────────────────────────────

export function OverviewStrip({
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

// ─── LeadPick ────────────────────────────────────────────────────────

export function LeadPick({
  item,
  isFav,
  onFav,
  onOpen,
  onStartWorkflow,
  onRead,
  workflowPending,
  evidenceMark,
}: {
  item: ContentItem;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  onRead: (id: number) => void;
  workflowPending: boolean;
  evidenceMark?: EvidenceMark | null;
}) {
  const analysis = getAnalysis(item);
  const score = scoreOf(item);
  const tags = tagsOf(analysis);
  const recommendation = getRecommendationReason(analysis, item.summary);

  const handleCardClick = () => {
    if (analysis) {
      onOpen({ ...analysis, _content_id: item.id });
    } else if (item.url) {
      onRead(item.id);
    }
  };

  return (
    <Panel
      onClick={handleCardClick}
      className="relative mb-4 cursor-pointer overflow-hidden p-6 shadow-[0_16px_38px_rgba(15,23,42,0.06)] transition hover:shadow-[0_20px_44px_rgba(15,23,42,0.09)] before:absolute before:bottom-0 before:left-0 before:top-0 before:w-1 before:bg-gradient-to-b before:from-primary before:to-teal"
    >
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
            onRead={onRead}
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

// ─── FilterPanel ─────────────────────────────────────────────────────

export function FilterPanel({
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
  const [categoriesExpanded, setCategoriesExpanded] = useState(false);

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
                    active ? `${cfg.bg} ${cfg.color} ${cfg.border} font-black` : 'border-gray-200 bg-white font-semibold text-gray-600 hover:border-gray-300',
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
            {(categoriesExpanded
              ? (CATEGORIES as readonly string[])
              : (CATEGORIES as readonly string[]).slice(0, 5)
            ).map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => onCategory(cat === '全部' ? '' : cat)}
                className={cx(
                  'rounded-full border px-2.5 py-1 text-xs transition',
                  selectedCategory === cat || (!selectedCategory && cat === '全部')
                    ? 'border-primary-border bg-primary-light font-black text-primary-text'
                    : 'border-gray-200 bg-white font-semibold text-gray-600 hover:border-gray-300',
                )}
              >
                {cat}
              </button>
            ))}
            {(CATEGORIES as readonly string[]).length > 5 && (
              <button
                type="button"
                onClick={() => setCategoriesExpanded((v) => !v)}
                className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-semibold text-gray-500 transition hover:border-primary-border hover:text-primary-text"
              >
                {categoriesExpanded ? '收起' : `更多 ${(CATEGORIES as readonly string[]).length - 5}`}
                {categoriesExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>
            )}
          </div>
        </div>
        {activeFilterCount > 0 && (
          <div>
            <Button variant="ghost" onClick={onClear} className="min-h-0 px-3 py-1.5 text-xs font-bold text-gray-500 hover:text-primary">
              清除筛选（{activeFilterCount}）
            </Button>
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── QualityPanel ────────────────────────────────────────────────────

export function QualityPanel({
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

// ─── TopicBoard ───────────────────────────────────────────────────────

export function TopicBoard({
  topics,
  topicMap,
  standaloneItems,
  expandedTopics,
  onToggleTopic,
  isFavorited,
  onFav,
  onOpen,
  onStartWorkflow,
  onRead,
  workflowPendingId,
  evidenceMarks,
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
  onRead: (id: number) => void;
  workflowPendingId: number | null;
  evidenceMarks: Record<string, EvidenceMark>;
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
                  onRead={onRead}
                  workflowPending={workflowPendingId === item.id}
                  evidenceMark={evidenceMarks[String(item.id)]}
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
                  onRead={onRead}
                  workflowPending={workflowPendingId === item.id}
                  evidenceMark={evidenceMarks[String(item.id)]}
                />
              ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ─── PickCard ─────────────────────────────────────────────────────────

export function PickCard({
  item,
  rank,
  isFav,
  onFav,
  onOpen,
  onStartWorkflow,
  onRead,
  workflowPending,
  evidenceMark,
  flush = false,
}: {
  item: ContentItem;
  rank: number;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  onRead: (id: number) => void;
  workflowPending: boolean;
  evidenceMark?: EvidenceMark | null;
  flush?: boolean;
}) {
  const analysis = getAnalysis(item);
  const score = scoreOf(item);
  const tags = tagsOf(analysis);
  const recommendation = analysis?.recommendation || analysis?.recommended_reason || item.summary || '';
  const scoreClass = score >= 80 ? 'text-primary' : score >= 70 ? 'text-amber' : 'text-teal';
  const [showBreakdown, setShowBreakdown] = useState(false);
  const breakdown = analysis?.score_breakdown;

  const handleCardClick = () => {
    if (analysis) {
      onOpen({ ...analysis, _content_id: item.id });
    } else if (item.url) {
      onRead(item.id);
    }
  };

  return (
    <article
      onClick={handleCardClick}
      className={cx(
        'grid grid-cols-[42px_minmax(0,1fr)_52px] items-start gap-3 px-4.5 py-3.5 transition hover:border-primary-border',
        'cursor-pointer',
        flush ? 'border-b border-gray-100 bg-transparent hover:bg-[#FBFCFE]' : 'rounded-lg border border-gray-200 bg-white',
      )}
    >
      <div className={cx('flex h-8 w-8 items-center justify-center rounded-sm font-mono text-xs font-black', rank <= 3 ? 'bg-primary-light text-primary-text' : 'bg-gray-100 text-gray-600')}>
        {rank}
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <SourceBadge name={item.source_name} type={item.source_type} compact />
          <span className="text-[11px] text-gray-300">/</span>
          <span className="text-[11px] text-gray-400">{timeAgo(item.published_at || item.crawled_at)}</span>
          {item.category && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">{item.category}</span>}
          {tags.slice(0, 3).map((tag) => (
            <span key={tag} className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ color: getTagColor(tag), background: `${getTagColor(tag)}12` }}>
              {tag}
            </span>
          ))}
          <EvidenceTag mark={evidenceMark} />
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
          onRead={onRead}
          workflowPending={workflowPending}
        />
        {showBreakdown && breakdown && (
          <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50/50 p-3" onClick={(e) => e.stopPropagation()}>
            <ScoreBreakdownChart breakdown={breakdown} />
          </div>
        )}
      </div>
      <div className="text-right">
        <div className={cx('font-mono text-[22px] font-black leading-none', scoreClass)}>
          {Math.round(score)}
        </div>
        <div className="mt-1 text-[10px] text-gray-400">分</div>
        {breakdown && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setShowBreakdown((v) => !v); }}
            className="mt-2 inline-flex items-center gap-0.5 rounded-xs border border-gray-200 bg-white px-1.5 py-0.5 text-[10px] font-bold text-gray-500 transition hover:border-primary-border hover:text-primary"
            title={showBreakdown ? '收起评分解释' : '展开评分解释'}
          >
            <BarChart3 size={11} />
            {showBreakdown ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
      </div>
    </article>
  );
}

// ─── PickActions ──────────────────────────────────────────────────────

export function PickActions({
  item,
  analysis,
  isFav,
  onFav,
  onOpen,
  onStartWorkflow,
  onRead,
  workflowPending,
  dark = false,
}: {
  item: ContentItem;
  analysis?: ContentAnalysis | null;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (a: ContentAnalysis & { _content_id?: number }) => void;
  onStartWorkflow: (item: ContentItem, isFavorited: boolean) => void;
  onRead: (id: number) => void;
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
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRead(item.id); }}
          className={cx('inline-flex items-center gap-1.5 rounded-xs border px-2.5 py-1.5 text-[11px] font-bold no-underline transition', actionClass)}
        >
          <BookOpen size={13} /> 阅读
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
          dark ? 'border-white/15 bg-white/10 text-white hover:bg-white/15' : 'border-primary-solid bg-primary-solid text-white hover:opacity-90',
        )}
      >
        <PenLine size={13} />
        {workflowPending ? '推进中' : '推进'}
      </button>
    </div>
  );
}

// ─── TopicToggle ──────────────────────────────────────────────────────

export function TopicToggle({
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

// ─── SectionHeading ───────────────────────────────────────────────────

export function SectionHeading({ title, count }: { title: string; count: number }) {
  return (
    <div className="mb-2.5 mt-1 flex items-center gap-2">
      <h2 className="text-sm font-black text-gray-800">{title}</h2>
      <span className="font-mono text-[11px] text-gray-400">{count}</span>
    </div>
  );
}
