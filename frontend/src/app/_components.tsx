'use client';

/**
 * Home page 子组件（从 page.tsx 抽出的展示组件）。
 *
 * 7 个子组件：
 * - ContentTimeline        按日分组的内容时间流
 * - TimelineSummary        右侧时间流汇总
 * - Spinner                加载旋转图标
 * - EditorialItem          单篇推荐项（含反馈/收藏/推进/分析按钮）
 * - ScoreBadge             单维度分数徽章（创作/爆文/质量）
 * - RecommendBadge         推荐等级徽章
 * - CurationScoreBadge     精选分徽章
 * - DeepReadBadge          论文精读标记（arXiv）
 * - FeedbackButtons        反馈按钮组（quick + more）
 *
 * 静态配置 + 工具函数（TIME_RANGE_HOURS / RECOMMEND_FILTERS / getContentTime /
 * normalizeTags / getItemTags / formatShanghaiToday）来自 _app-utils.ts。
 */

import React, { useCallback, useState } from 'react';
import {
  Ban,
  BookOpen,
  ChevronDown,
  Clock3,
  ExternalLink,
  Eye,
  Flame,
  PenLine,
  Star,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { feedbackApi } from '@/lib/api';
import type { FeedbackType } from '@/lib/api';
import { timeAgo } from '@/lib/datetime';
import { getRecommendationReason, explainRecommendation } from '@/lib/recommendation';
import type {
  ContentAnalysis,
  ContentItem,
  RecommendLevel,
} from '@/types';
import { getContentTime, getItemTags } from './_app-utils';

/* ── Color mapping for recommend levels (timeline dots + summary) ── */

export function levelColor(level: RecommendLevel): string {
  if (level === '强烈建议写') return '#FF6B35';
  if (level === '适合深挖') return '#8B5CF6';
  if (level === '适合蹭热点') return '#D97706';
  if (level === '不建议追') return '#9CA3AF';
  if (level === '信号不足') return '#D1D5DB';
  return '#00C9A7';
}

export function Spinner() {
  return (
    <div className="inline-block h-7 w-7 animate-spin rounded-full border-[3px] border-gray-200 border-t-primary" />
  );
}

/* ── Timeline & Summary ── */

export function ContentTimeline({
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
            <span className="font-mono text-xs text-gray-500">{group.entries.length}</span>
          </div>
          <div className="relative flex flex-col gap-3.5">
            <div className="absolute bottom-[9px] left-[58px] top-[9px] w-px bg-gray-200" />
            {group.entries.map(({ item, level }) => (
              <div key={item.id} className="relative grid grid-cols-[50px_18px_minmax(0,1fr)] items-start gap-2.5">
                <div className="pt-0.5 text-right font-mono text-xs font-extrabold text-gray-700">
                  {timeAgo(getContentTime(item))}
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
                  time={timeAgo(getContentTime(item))}
                  timeLabel={''}
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

export function TimelineSummary({
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
          <span className="ml-auto font-mono text-[11px] text-gray-500">{totalLabel}</span>
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

/* ── Editorial Item ── */

export function EditorialItem({
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
  const { openReader } = useAppContext();
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
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-xs font-semibold text-gray-600">
            {item.source_name}
          </span>
          <span className="text-xs text-gray-300">/</span>
          <span className="shrink-0 text-xs text-gray-500">{timeLabel || time}</span>
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

      <h3 className="mb-2 text-base font-semibold leading-[1.55] text-gray-900">
        {item.title}
      </h3>

      {recommendation && (
        <div className="line-clamp-2 mb-3 border-l-[3px] border-primary py-1.5 pl-3 text-[13px] leading-7 text-gray-600">
          推荐理由：{recommendation}
        </div>
      )}

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
                <span key={tag} className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
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
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); openReader(item.id); }}
              className="inline-flex items-center gap-1.5 rounded-xs border border-primary-border bg-primary-light px-2 py-1 text-xs font-bold text-primary-text transition hover:border-primary-text"
              title="在系统内阅读提取后的正文"
            >
              <BookOpen size={13} strokeWidth={2} />
              阅读
            </button>
          )}
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1.5 rounded-xs border border-teal-border bg-teal-light px-2 py-1 text-xs font-bold text-teal-text no-underline transition hover:border-teal-text"
              title="查看原文"
            >
              <ExternalLink size={13} strokeWidth={2} />
              原文
            </a>
          )}
          <FeedbackButtons contentId={item.id} />
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

/* ── Score / Recommend / Curation / DeepRead Badges ── */

export function ScoreBadge({ label, score, tone }: { label: string; score: number; tone: 'primary' | 'neutral' }) {
  const strong = score >= 75;
  const medium = score >= 50;
  const toneClass = tone === 'primary' && strong
    ? 'bg-primary-light text-primary-text'
    : medium
      ? 'bg-gray-100 text-gray-600'
      : 'bg-gray-100 text-gray-500';
  return (
    <span className={cx('rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold', toneClass)}>
      {label}{Math.round(score)}
    </span>
  );
}

export function RecommendBadge({ level }: { level: RecommendLevel }) {
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

export function CurationScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null || score === 0) return null;
  const rounded = Math.round(score);
  const toneClass = rounded >= 85
    ? 'bg-teal-light text-teal-text'
    : rounded >= 70
      ? 'bg-primary-light text-primary-text'
      : rounded >= 55
        ? 'bg-amber-light text-amber'
        : 'bg-gray-100 text-gray-500';
  return (
    <span className={cx('rounded px-2 py-0.5 font-mono text-[11px] font-bold', toneClass)}>
      {rounded}
    </span>
  );
}

export function DeepReadBadge({ enrichment }: { enrichment?: Record<string, unknown> | null }) {
  if (!enrichment) return null;
  const deepRead = enrichment.deep_read as Record<string, unknown> | undefined;
  if (!deepRead) return null;
  const worth = deepRead.worth_deep_read as boolean | undefined;
  const reason = deepRead.deep_read_reason as string | undefined;
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

/* ── Feedback Buttons ── */

const FEEDBACK_OPTIONS: { type: FeedbackType; icon: LucideIcon; label: string; color: string }[] = [
  { type: 'great_pick', icon: Star, label: '精选好文', color: '#16a34a' },
  { type: 'like', icon: ThumbsUp, label: '有价值', color: '#2563eb' },
  { type: 'dislike', icon: ThumbsDown, label: '不感兴趣', color: '#dc2626' },
  { type: 'not_relevant', icon: Ban, label: '不相关', color: '#9ca3af' },
  { type: 'outdated', icon: Clock3, label: '过时了', color: '#d97706' },
];

export function FeedbackButtons({ contentId }: { contentId: number }) {
  const { currentUser } = useAppContext();
  const router = useRouter();
  const [activeFeedback, setActiveFeedback] = useState<FeedbackType | null>(null);
  const [showMore, setShowMore] = useState(false);

  const handleFeedback = async (type: FeedbackType) => {
    if (activeFeedback === type) return;
    if (!currentUser) {
      router.push('/login');
      return;
    }
    try {
      await feedbackApi.submit(contentId, type);
      setActiveFeedback(type);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (!msg?.includes('409') && !msg?.includes('Conflict')) {
        console.error('Feedback failed:', err);
      }
    }
  };

  return (
    <div className="relative flex items-center gap-0.5">
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
            'inline-flex items-center justify-center rounded border-0 bg-transparent min-h-[24px] min-w-[24px] p-1 transition',
            activeFeedback === type ? 'cursor-default' : 'cursor-pointer',
            activeFeedback && activeFeedback !== type ? 'opacity-30' : 'opacity-100',
          )}
          style={{ color: activeFeedback === type ? color : '#9CA3AF', background: activeFeedback === type ? `${color}15` : 'transparent' }}
        >
          <Icon size={13} strokeWidth={2.2} />
        </button>
      ))}
      <div className="relative">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowMore(!showMore);
          }}
          className={cx('inline-flex items-center justify-center cursor-pointer rounded border-0 min-h-[24px] min-w-[24px] p-1 text-gray-500 transition hover:text-gray-700', showMore ? 'bg-gray-100' : 'bg-transparent')}
          title="更多反馈"
        >
          <ChevronDown size={13} strokeWidth={2.2} />
        </button>
        {showMore && (
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
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
