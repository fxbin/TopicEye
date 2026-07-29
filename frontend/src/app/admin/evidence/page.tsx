'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  BarChart3,
  CheckCircle2,
  Globe,
  Link2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Panel, cx } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner } from '@/components/admin-ui';
import { LoadingState } from '@/components/StateView';
import { evidenceApi } from '@/lib/api';
import type { EvidenceStats, EvidenceEffectStats } from '@/lib/api';

const PERIOD_OPTIONS = [7, 14, 30];

const LEVEL_LABELS: Record<string, string> = {
  none: '无标记',
  cross_source: '跨源呼应',
  strong_cross_source: '强跨源',
};

const KIND_LABELS: Record<string, string> = {
  unknown: '未知',
  primary: '原始发布',
  official: '官方',
  publisher: '媒体',
  aggregator: '聚合',
  social: '社交',
};

const INTERACTION_LABELS: Record<string, string> = {
  click: '点击阅读',
  favorite: '收藏',
  unfavorite: '取消收藏',
  adopt: '采纳',
  feedback_positive: '正面反馈',
  feedback_negative: '负面反馈',
};

function StatTile({
  label,
  value,
  sub,
  icon,
  tone = 'neutral',
}: {
  label: string;
  value: number | string;
  sub?: string;
  icon: React.ReactNode;
  tone?: 'primary' | 'teal' | 'amber' | 'neutral';
}) {
  const classes = {
    primary: 'border-primary-border bg-primary-light text-primary',
    teal: 'border-teal-border bg-teal-light text-teal',
    amber: 'border-amber-border bg-amber-light text-amber',
    neutral: 'border-gray-200 bg-gray-50 text-gray-700',
  }[tone];
  return (
    <div className={cx('rounded-sm border p-3', classes)}>
      <div className="mb-2 flex items-center gap-2 text-[11px] font-black">
        {icon}
        {label}
      </div>
      <div className="font-mono text-2xl font-black leading-none">{value}</div>
      {sub && <div className="mt-1 text-[10px] opacity-70">{sub}</div>}
    </div>
  );
}

function RateBar({
  label,
  marked,
  unmarked,
  max,
}: {
  label: string;
  marked: number;
  unmarked: number;
  max: number;
}) {
  const markedPct = max > 0 ? (marked / max) * 100 : 0;
  const unmarkedPct = max > 0 ? (unmarked / max) * 100 : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[12px]">
        <span className="text-gray-600">{label}</span>
        <span className="font-mono text-gray-400">
          {marked.toFixed(2)}% vs {unmarked.toFixed(2)}%
        </span>
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-12 text-[10px] text-primary">带标记</span>
          <div className="h-4 flex-1 overflow-hidden rounded-sm bg-gray-100">
            <div
              className="flex h-full items-center justify-end rounded-sm bg-primary px-1.5 text-[9px] font-bold text-white"
              style={{ width: `${Math.max(6, markedPct)}%` }}
            >
              {marked > 0 ? `${marked.toFixed(1)}%` : ''}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-12 text-[10px] text-gray-400">无标记</span>
          <div className="h-4 flex-1 overflow-hidden rounded-sm bg-gray-100">
            <div
              className="flex h-full items-center justify-end rounded-sm bg-gray-300 px-1.5 text-[9px] font-bold text-white"
              style={{ width: `${Math.max(6, unmarkedPct)}%` }}
            >
              {unmarked > 0 ? `${unmarked.toFixed(1)}%` : ''}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function EvidenceDashboardPage() {
  const { currentUser, authLoading } = useAppContext();
  const [stats, setStats] = useState<EvidenceStats | null>(null);
  const [effectStats, setEffectStats] = useState<EvidenceEffectStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, e] = await Promise.all([
        evidenceApi.getStats(),
        evidenceApi.getEffectStats(days),
      ]);
      setStats(s);
      setEffectStats(e);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    if (!authLoading && currentUser?.role === 'admin') {
      void fetchData();
    }
  }, [fetchData, authLoading, currentUser]);

  if (authLoading) return <LoadingState label="加载中..." />;
  if (currentUser?.role !== 'admin') {
    return (
      <AdminPageShell>
        <AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner>
      </AdminPageShell>
    );
  }

  const marked = effectStats?.marked;
  const unmarked = effectStats?.unmarked;
  const comparison = effectStats?.comparison || {};
  const maxRate = Math.max(
    marked?.interaction_rate || 0,
    unmarked?.interaction_rate || 0,
    0.01,
  );

  // Per-type rates for bar chart
  const allTypes = new Set([
    ...(marked ? Object.keys(marked.interactions_by_type) : []),
    ...(unmarked ? Object.keys(unmarked.interactions_by_type) : []),
  ]);
  const typeRows = [...allTypes].sort();

  return (
    <AdminPageShell maxWidth={1200}>
      <AdminPageHeader
        title="可信线索看板"
        icon={ShieldCheck}
        description="跨源证据标记统计与效果验证（交互率对比）"
        actions={
          <div className="flex items-center gap-2">
            {PERIOD_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={cx(
                  'rounded-sm border px-2.5 py-1 text-[12px] font-bold transition',
                  days === d
                    ? 'border-primary bg-primary text-white'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
                )}
              >
                {d}天
              </button>
            ))}
            <button
              onClick={() => void fetchData()}
              disabled={loading}
              className="flex items-center gap-1 rounded-sm border border-gray-200 bg-white px-2.5 py-1 text-[12px] font-bold text-gray-600 transition hover:border-gray-300 disabled:opacity-50"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>
        }
      />

      {error && (
        <div className="mb-4">
          <AdminNoticeBanner tone="red">{error}</AdminNoticeBanner>
        </div>
      )}

      {loading ? (
        <LoadingState label="加载统计数据..." />
      ) : (
        <div className="space-y-5">
          {/* ── Summary tiles ── */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile
              icon={<Sparkles size={14} />}
              label="证据标记总数"
              value={stats?.marks.total ?? 0}
              sub={stats ? `跨 ${stats.profiles.profiled_sources} 个已画像信源` : ''}
              tone="primary"
            />
            <StatTile
              icon={<Link2 size={14} />}
              label="证据链接数"
              value={stats?.links.total ?? 0}
              tone="teal"
            />
            <StatTile
              icon={<CheckCircle2 size={14} />}
              label="原始发布标记"
              value={stats?.marks.has_primary_source ?? 0}
              tone="amber"
            />
            <StatTile
              icon={<Globe size={14} />}
              label="官方一手链接"
              value={stats?.marks.has_official_source ?? 0}
              tone="neutral"
            />
          </div>

          {/* ── Two-column: marks breakdown + effect comparison ── */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Marks by level */}
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <BarChart3 size={14} className="text-primary" />
                <span className="text-[13px] font-bold text-gray-900">标记分布</span>
              </div>
              {stats && Object.keys(stats.marks.by_level).length > 0 ? (
                <div className="space-y-2">
                  {Object.entries(stats.marks.by_level)
                    .sort(([, a], [, b]) => b - a)
                    .map(([level, count]) => {
                      const pct = stats.marks.total > 0 ? (count / stats.marks.total) * 100 : 0;
                      return (
                        <div key={level} className="flex items-center gap-2">
                          <span className="w-20 text-[12px] text-gray-600">
                            {LEVEL_LABELS[level] || level}
                          </span>
                          <div className="h-5 flex-1 overflow-hidden rounded-sm bg-gray-100">
                            <div
                              className="flex h-full items-center justify-end rounded-sm bg-primary px-2 text-[10px] font-bold text-white"
                              style={{ width: `${Math.max(8, pct)}%` }}
                            >
                              {count}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                </div>
              ) : (
                <div className="py-4 text-center text-[12px] text-gray-400">暂无标记数据</div>
              )}

              {/* Publisher kind breakdown */}
              {stats && Object.keys(stats.profiles.by_kind).length > 0 && (
                <>
                  <div className="mb-2 mt-4 flex items-center gap-1.5">
                    <span className="text-[12px] font-bold text-gray-700">信源画像分布</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(stats.profiles.by_kind).map(([kind, count]) => (
                      <Badge key={kind} tone="neutral" className="text-[10px]">
                        {KIND_LABELS[kind] || kind}: {count}
                      </Badge>
                    ))}
                  </div>
                </>
              )}
            </Panel>

            {/* Effect comparison summary */}
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <TrendingUp size={14} className="text-primary" />
                <span className="text-[13px] font-bold text-gray-900">交互率对比（{days}天）</span>
              </div>
              {marked && unmarked ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-sm border border-primary-border bg-primary-light p-3">
                      <div className="text-[10px] font-bold text-primary">带证据标记</div>
                      <div className="mt-1 font-mono text-xl font-black text-primary">
                        {(marked.interaction_rate * 100).toFixed(2)}%
                      </div>
                      <div className="text-[10px] text-gray-400">
                        {marked.total_content} 条内容 · {marked.total_interactions} 次交互
                      </div>
                    </div>
                    <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                      <div className="text-[10px] font-bold text-gray-500">无证据标记</div>
                      <div className="mt-1 font-mono text-xl font-black text-gray-600">
                        {(unmarked.interaction_rate * 100).toFixed(2)}%
                      </div>
                      <div className="text-[10px] text-gray-400">
                        {unmarked.total_content} 条内容 · {unmarked.total_interactions} 次交互
                      </div>
                    </div>
                  </div>

                  {/* Overall lift */}
                  {marked.interaction_rate > 0 && unmarked.interaction_rate > 0 && (
                    <div className="rounded-sm bg-gray-50 p-2 text-center">
                      <span className="text-[11px] text-gray-500">整体交互率提升</span>
                      <span className="ml-2 font-mono text-sm font-black text-primary">
                        {(((marked.interaction_rate - unmarked.interaction_rate) / unmarked.interaction_rate) * 100).toFixed(1)}%
                      </span>
                    </div>
                  )}

                  {/* Per-type rate bars */}
                  {typeRows.length > 0 && (
                    <div className="space-y-2 pt-1">
                      {typeRows.map((t) => {
                        const markedRate = marked.interactions_by_type[t]
                          ? (marked.interactions_by_type[t] / marked.total_content) * 100
                          : 0;
                        const unmarkedRate = unmarked.interactions_by_type[t]
                          ? (unmarked.interactions_by_type[t] / unmarked.total_content) * 100
                          : 0;
                        const lift = comparison[t];
                        return (
                          <div key={t}>
                            <RateBar
                              label={INTERACTION_LABELS[t] || t}
                              marked={markedRate}
                              unmarked={unmarkedRate}
                              max={Math.max(markedRate, unmarkedRate, 1)}
                            />
                            {lift !== null && lift !== undefined && (
                              <div className="mt-0.5 text-right text-[10px] text-gray-400">
                                提升: {lift > 0 ? '+' : ''}{(lift * 100).toFixed(1)}%
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-4 text-center text-[12px] text-gray-400">暂无效果统计数据</div>
              )}
            </Panel>
          </div>

          {/* ── Profile coverage ── */}
          {stats && (
            <Panel className="p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <ShieldCheck size={14} className="text-primary" />
                <span className="text-[13px] font-bold text-gray-900">信源画像覆盖</span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-sm border border-gray-200 bg-gray-50 p-3 text-center">
                  <div className="font-mono text-lg font-black text-gray-800">
                    {stats.profiles.total_system_sources}
                  </div>
                  <div className="text-[10px] text-gray-400">系统信源</div>
                </div>
                <div className="rounded-sm border border-teal-border bg-teal-light p-3 text-center">
                  <div className="font-mono text-lg font-black text-teal">
                    {stats.profiles.profiled_sources}
                  </div>
                  <div className="text-[10px] text-gray-400">已画像</div>
                </div>
                <div className="rounded-sm border border-amber-border bg-amber-light p-3 text-center">
                  <div className="font-mono text-lg font-black text-amber">
                    {stats.profiles.unprofiled_sources}
                  </div>
                  <div className="text-[10px] text-gray-400">未画像</div>
                </div>
              </div>
            </Panel>
          )}
        </div>
      )}
    </AdminPageShell>
  );
}
