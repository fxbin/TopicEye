'use client';

/**
 * 评分反馈看板（推荐质量评估、反馈分布与个性化向量统计）。
 *
 * 视觉口径（#125 v2 换壳，与 sources / feedback 定稿一致）：文字层级 ink 三档
 * （900 标题 / 700 正文 / 500 次要），分隔与浅底 border-ink-200 / bg-ink-100，
 * 正负反馈用 teal / amber 语义 token，数字用 font-mono / tabular-nums。
 */

import React, { useState } from 'react';
import {
  BarChart3,
  Heart,
  EyeOff,
  MessageCircle,
  RefreshCw,
  Sparkles,
  TrendingUp,
  Users,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Panel, cx } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner } from '@/components/admin-ui';
import { LoadingState, EmptyState } from '@/components/StateView';
import { scoringDashboardApi } from '@/lib/api';
import { useFetch } from '@/hooks/useFetch';

const PERIOD_OPTIONS = [7, 14, 30];

const FEEDBACK_LABELS: Record<string, string> = {
  like: '👍 喜欢',
  great_pick: '🔥 神仙选题',
  dislike: '👎 不喜欢',
  skip: '⏭ 跳过',
  not_relevant: '🚫 不相关',
  outdated: '📅 过时',
};

export default function ScoringDashboardPage() {
  const { currentUser, authLoading } = useAppContext();
  const [days, setDays] = useState(7);

  const { data, loading, error, refetch: fetchData } = useFetch(
    () => scoringDashboardApi.get(days),
    [days],
    { enabled: !authLoading && currentUser?.role === 'admin' },
  );

  if (authLoading) return <LoadingState label="加载中..." />;
  if (currentUser?.role !== 'admin') {
    return (
      <AdminPageShell>
        <AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner>
      </AdminPageShell>
    );
  }

  const summary = data?.summary;
  const maxDailyFeedback = Math.max(...(data?.daily_feedback.map((d) => d.count) || [1]), 1);
  const maxDailyFav = Math.max(...(data?.daily_favorites.map((d) => d.count) || [1]), 1);

  return (
    <AdminPageShell maxWidth={1200}>
      <AdminPageHeader
        title="评分反馈看板"
        icon={BarChart3}
        description="推荐质量评估、用户反馈分布与个性化向量统计"
        actions={
          <div className="flex items-center gap-2">
            {PERIOD_OPTIONS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                aria-pressed={days === d}
                className={cx(
                  'rounded-full px-3 py-1 text-[12px] font-semibold transition',
                  days === d ? 'bg-primary text-white' : 'bg-ink-100 text-ink-500 hover:bg-ink-200',
                )}
              >
                {d}天
              </button>
            ))}
            <button
              type="button"
              onClick={fetchData}
              disabled={loading}
              className="ml-1 grid h-8 w-8 place-items-center rounded-full bg-ink-100 text-ink-500 transition hover:bg-ink-200"
              aria-label="刷新"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        }
      />

      {error && <AdminNoticeBanner tone="red">{error}<button type="button" onClick={() => void fetchData()} className="ml-3 underline">重试</button></AdminNoticeBanner>}

      {loading ? (
        <LoadingState label="加载看板数据..." />
      ) : error ? null : !data || !summary ? (
        <EmptyState icon={BarChart3} title="暂无数据" />
      ) : (
        <div className="space-y-5">
          {/* ── Summary cards ── */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryCard
              icon={TrendingUp}
              label="已分析内容"
              value={summary.analyzed_count}
              tone="neutral"
            />
            <SummaryCard
              icon={Heart}
              label="收藏数"
              value={summary.favorites_count}
              sub={`${summary.favorite_rate}% 收藏率`}
              tone="teal"
            />
            <SummaryCard
              icon={EyeOff}
              label="忽略数"
              value={summary.ignores_count}
              sub={`${summary.ignore_rate}% 忽略率`}
              tone="amber"
            />
            <SummaryCard
              icon={MessageCircle}
              label="反馈数"
              value={summary.total_feedback}
              sub={`${summary.feedback_rate}% 反馈率`}
              tone="primary"
            />
          </div>

          {/* ── Two-column: feedback distribution + personalization ── */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Feedback distribution */}
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <MessageCircle size={14} className="text-primary" />
                <span className="text-[13px] font-bold text-ink-900">反馈类型分布</span>
              </div>
              {Object.keys(data.feedback_distribution).length === 0 ? (
                <div className="py-4 text-center text-[12px] text-ink-500">暂无反馈数据</div>
              ) : (
                <div className="space-y-2">
                  {Object.entries(data.feedback_distribution)
                    .sort(([, a], [, b]) => b - a)
                    .map(([type, count]) => {
                      const pct = summary.total_feedback > 0 ? (count / summary.total_feedback) * 100 : 0;
                      const isPositive = type === 'like' || type === 'great_pick';
                      return (
                        <div key={type} className="flex items-center gap-2">
                          <span className="w-20 text-[12px] text-ink-700">
                            {FEEDBACK_LABELS[type] || type}
                          </span>
                          <div className="h-5 flex-1 overflow-hidden rounded-sm bg-ink-100">
                            <div
                              className={cx(
                                'flex h-full items-center justify-end rounded-sm px-2 text-[10px] font-bold tabular-nums text-white',
                                isPositive ? 'bg-teal' : 'bg-amber',
                              )}
                              style={{ width: `${Math.max(8, pct)}%` }}
                            >
                              {count}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                </div>
              )}
            </Panel>

            {/* Personalization stats */}
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <Sparkles size={14} className="text-primary" />
                <span className="text-[13px] font-bold text-ink-900">个性化向量统计</span>
              </div>
              <div className="mb-3 flex items-center gap-4">
                <div className="flex items-center gap-1.5">
                  <Users size={14} className="text-ink-500" />
                  <span className="text-[12px] text-ink-500">
                    <span className="font-mono font-bold text-ink-900">{summary.users_with_vectors}</span> 用户有向量
                  </span>
                </div>
              </div>
              {data.top_tags.length === 0 ? (
                <div className="py-4 text-center text-[12px] text-ink-500">暂无兴趣向量数据</div>
              ) : (
                <div className="space-y-1">
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
                    热门标签 Top 10
                  </div>
                  {data.top_tags.slice(0, 10).map((tag) => (
                    <div key={tag.tag} className="flex items-center gap-2">
                      <Badge
                        tone={tag.avg_weight > 0 ? 'teal' : 'amber'}
                        className="rounded px-2 py-0.5 text-[11px]"
                      >
                        {tag.tag}
                      </Badge>
                      <span className="font-mono text-[11px] text-ink-500">
                        avg {tag.avg_weight > 0 ? '+' : ''}{tag.avg_weight}
                      </span>
                      <span className="text-[10px] tabular-nums text-ink-500">
                        ({tag.user_count}人)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          {/* ── Daily trends ── */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Daily feedback trend */}
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <MessageCircle size={14} className="text-primary" />
                <span className="text-[13px] font-bold text-ink-900">每日反馈趋势</span>
              </div>
              {data.daily_feedback.length === 0 ? (
                <div className="py-4 text-center text-[12px] text-ink-500">暂无数据</div>
              ) : (
                <div className="flex h-24 items-end gap-1">
                  {data.daily_feedback.map((d) => {
                    const heightPct = (d.count / maxDailyFeedback) * 100;
                    return (
                      <div
                        key={d.date}
                        className="group relative flex-1"
                        title={`${d.date}: ${d.count} 条反馈`}
                      >
                        <div
                          className="w-full rounded-t-sm bg-primary/30 transition group-hover:bg-primary/50"
                          style={{ height: `${Math.max(2, heightPct)}%` }}
                        />
                        <div className="absolute -top-5 left-1/2 -translate-x-1/2 text-[10px] font-bold tabular-nums text-ink-700 opacity-0 transition group-hover:opacity-100">
                          {d.count}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>

            {/* Daily favorites trend */}
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <Heart size={14} className="text-teal" />
                <span className="text-[13px] font-bold text-ink-900">每日收藏趋势</span>
              </div>
              {data.daily_favorites.length === 0 ? (
                <div className="py-4 text-center text-[12px] text-ink-500">暂无数据</div>
              ) : (
                <div className="flex h-24 items-end gap-1">
                  {data.daily_favorites.map((d) => {
                    const heightPct = (d.count / maxDailyFav) * 100;
                    return (
                      <div
                        key={d.date}
                        className="group relative flex-1"
                        title={`${d.date}: ${d.count} 次收藏`}
                      >
                        <div
                          className="w-full rounded-t-sm bg-teal/30 transition group-hover:bg-teal/50"
                          style={{ height: `${Math.max(2, heightPct)}%` }}
                        />
                        <div className="absolute -top-5 left-1/2 -translate-x-1/2 text-[10px] font-bold tabular-nums text-ink-700 opacity-0 transition group-hover:opacity-100">
                          {d.count}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
          </div>
        </div>
      )}
    </AdminPageShell>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: React.ComponentType<{ size?: number; className?: string; strokeWidth?: number }>;
  label: string;
  value: number;
  sub?: string;
  tone: 'teal' | 'amber' | 'primary' | 'neutral';
}) {
  const toneClass = {
    teal: 'text-teal bg-teal-light/30',
    amber: 'text-amber bg-amber-light/30',
    primary: 'text-primary bg-primary-light/30',
    neutral: 'text-ink-500 bg-ink-100',
  }[tone];

  return (
    <Panel className="p-3">
      <div className="mb-1 flex items-center gap-1.5">
        <div className={cx('grid h-6 w-6 place-items-center rounded-sm', toneClass)}>
          <Icon size={13} strokeWidth={2.2} />
        </div>
        <span className="text-[11px] font-semibold text-ink-500">{label}</span>
      </div>
      <div className="font-mono text-xl font-black text-ink-900">{value}</div>
      {sub && <div className="text-[10px] text-ink-500">{sub}</div>}
    </Panel>
  );
}
