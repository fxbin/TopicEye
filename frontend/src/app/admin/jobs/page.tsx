'use client';

import { StatTile } from '@/components/StatTile';
import React, { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ListChecks,
  RefreshCw,
  Timer,
  XCircle,
} from 'lucide-react';

import { Badge, Button, Surface, cx, type Tone } from '@/components/ui';
import { AdminPageHeader, AdminPageShell } from '@/components/admin-ui';
import { AdminBlockSkeleton, AdminTableSkeleton, AdminEmptyState } from '@/components/admin';
import { ErrorState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { statsJobsApi, type JobStatsByJobKey, type JobStatsResponse } from '@/lib/api';
import { timeAgoShort as formatRelativeTime } from '@/lib/datetime';

const DAY_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 1, label: '今日' },
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
];

const JOB_STATUS_TONE: Record<string, Tone> = {
  SUCCESS: 'teal',
  FAILED: 'red',
  TIMEOUT: 'amber',
  SKIPPED: 'neutral',
  RUNNING: 'primary',
};

// 状态条颜色走 token CSS 变量（与 JOB_STATUS_TONE Badge 同语义通道：
// 成功 teal / 失败 red / 超时 amber / 跳过中性 / 运行中 primary），
// 不再手写 hex——#130 残余装饰债清理。
const STATUS_BAR_COLOR: Record<string, string> = {
  SUCCESS: 'var(--color-teal)',
  FAILED: 'var(--color-red)',
  TIMEOUT: 'var(--color-amber)',
  SKIPPED: 'var(--color-ink-300)',
  RUNNING: 'var(--color-primary)',
};

function formatDuration(ms: number | null | undefined): string {
  if (ms == null || ms <= 0) return '-';
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1)}min`;
  return `${(minutes / 60).toFixed(1)}h`;
}

function successTone(rate: number): Tone {
  if (rate >= 0.95) return 'teal';
  if (rate >= 0.8) return 'amber';
  return 'red';
}

function lastStatusTone(status: string | null | undefined): Tone {
  if (!status) return 'neutral';
  return JOB_STATUS_TONE[status] || 'neutral';
}

export default function JobStatsPage() {
  const [days, setDays] = useState(7);
  const [selectedJobKey, setSelectedJobKey] = useState<string | null>(null);

  const { data, loading, error, refetch } = useFetch<JobStatsResponse>(
    () => statsJobsApi.get(days, selectedJobKey ?? undefined),
    [days, selectedJobKey],
    { initialLoading: true },
  );

  const totals = data?.totals;
  const initialLoading = loading && !data;
  const byStatusMax = data
    ? Math.max(...data.by_status.map((row) => row.count), 1)
    : 1;

  return (
    <AdminPageShell>
      <AdminPageHeader
        title="任务监控"
        icon={Activity}
        description="查看任务运行趋势、成功率与最近异常。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex overflow-hidden rounded-xs border border-ink-200">
              {DAY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDays(opt.value)}
                  aria-pressed={days === opt.value}
                  className={cx(
                    'min-h-8 whitespace-nowrap px-3 py-1 text-[13px] transition',
                    days === opt.value
                      ? 'bg-primary-solid text-white'
                      : 'bg-white text-ink-700 hover:bg-ink-100',
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void refetch()}
              disabled={loading}
              className="min-h-8 px-3.5 py-1.5 text-[13px]"
            >
              <RefreshCw className={cx('mr-1 inline h-3.5 w-3.5', loading && 'animate-spin')} />
              刷新
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
        </div>
      )}

      {/* ── KPI 卡片 ── */}
      <section className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 lg:grid-cols-4">
        <StatTile
          icon={ListChecks}
          label="总运行数"
          value={totals ? totals.total_runs.toLocaleString() : '-'}
          hint={data ? `${data.period.days} 天内` : ''}
        />
        <StatTile
          icon={CheckCircle2}
          label="成功率"
          value={totals ? `${(totals.success_rate * 100).toFixed(1)}%` : '-'}
          hint={totals ? `${totals.success_count} 成功 / ${totals.failed_count + totals.timeout_count} 失败` : ''}
          tone={successTone(totals?.success_rate ?? 1)}
        />
        <StatTile
          icon={Timer}
          label="平均耗时"
          value={formatDuration(totals?.avg_duration_ms)}
          hint={totals ? `最长 ${formatDuration(totals.max_duration_ms)}` : ''}
        />
        <StatTile
          icon={AlertTriangle}
          label="最近失败"
          value={data ? data.recent_failures.length.toString() : '-'}
          hint={totals ? `${totals.failed_count + totals.timeout_count} 次` : '近 10 条'}
        />
      </section>

      {/* ── 状态分布 ── */}
      <Surface title="状态分布" icon={Activity}>
        {initialLoading ? <AdminBlockSkeleton lines={4} /> : data && data.by_status.length > 0 ? (
          <div className="space-y-2">
            {data.by_status.map((row) => (
              <div key={row.status} className="grid grid-cols-[5.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 sm:gap-3">
                <span className="text-[12px] text-ink-700">
                  <Badge tone={JOB_STATUS_TONE[row.status] || 'neutral'}>{row.status}</Badge>
                </span>
                <div className="h-5 min-w-0 overflow-hidden rounded-sm bg-ink-100">
                  <div
                    className="h-full transition-all"
                    style={{
                      width: `${(row.count / byStatusMax) * 100}%`,
                      backgroundColor: STATUS_BAR_COLOR[row.status] || 'var(--color-ink-300)',
                    }}
                  />
                </div>
                <span className="text-right tabular-nums font-mono text-[12px] text-ink-700">
                  {row.count.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        ) : data ? (
          <AdminEmptyState compact icon={ListChecks} title="该窗口内没有运行记录" description="换个时间窗口试试，或点右上角刷新" />
        ) : null}
      </Surface>

      {/* ── Per-job_key 表格 ── */}
      <Surface
        title="各任务运行情况"
        icon={ListChecks}
        actions={selectedJobKey && (
          <button type="button" onClick={() => setSelectedJobKey(null)} className="text-[12px] text-primary-text hover:underline">
            清除筛选
          </button>
        )}
      >
        {initialLoading ? <AdminTableSkeleton columns={6} /> : data && data.by_job_key.length > 0 ? (
          <div>
            <p className="mb-2 text-xs text-ink-500 sm:hidden">左右滑动查看完整任务数据</p>
            <div className="overflow-x-auto" role="region" aria-label="各任务运行情况表格" tabIndex={0}>
              <table className="w-full min-w-[640px] text-[13px] tabular-nums">
                <thead>
                  <tr className="border-b border-ink-200 text-left text-[12px] uppercase tracking-wide text-ink-500">
                    <th className="px-2 py-2">任务</th>
                    <th className="px-2 py-2 text-right">运行</th>
                    <th className="px-2 py-2">成功率</th>
                    <th className="px-2 py-2 text-right">平均耗时</th>
                    <th className="px-2 py-2">最近状态</th>
                    <th className="px-2 py-2">最近运行</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_job_key.map((row) => (
                    <JobKeyRow
                      key={row.job_key}
                      row={row}
                      isSelected={selectedJobKey === row.job_key}
                      onClick={() =>
                        setSelectedJobKey(
                          selectedJobKey === row.job_key ? null : row.job_key,
                        )
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : data ? (
          <AdminEmptyState compact icon={ListChecks} title="没有匹配的任务" description="调整时间窗口，或清除 job 筛选后重试" />
        ) : null}
      </Surface>

      {/* ── 最近失败 ── */}
      <Surface title="最近失败 / 超时" icon={XCircle} hint="最多 10 条">
        {initialLoading ? <AdminBlockSkeleton /> : data && data.recent_failures.length > 0 ? (
          <ul className="space-y-2">
            {data.recent_failures.map((row, idx) => (
              <li
                key={`${row.job_key}-${row.started_at}-${idx}`}
                className="rounded-sm border border-red-light bg-red-light/30 px-3 py-2"
              >
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-[12px]">
                  <span className="min-w-0 break-all font-mono text-ink-700">{row.job_key}</span>
                  <span className="flex flex-wrap items-center gap-2 text-ink-500">
                    <Badge tone={JOB_STATUS_TONE[row.status] || 'neutral'}>{row.status}</Badge>
                    <Clock className="h-3 w-3" />
                    {formatRelativeTime(row.started_at)}
                    <span>· {formatDuration(row.duration_ms)}</span>
                  </span>
                </div>
                {row.error_message && (
                  <pre className="overflow-x-auto whitespace-pre-wrap break-words text-[12px] text-red">
                    {row.error_message}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-6 text-center text-[13px] text-ink-500">
            {data ? '🎉 该时间窗口内无失败记录' : ''}
          </p>
        )}
      </Surface>
    </AdminPageShell>
  );
}


function JobKeyRow({
  row,
  isSelected,
  onClick,
}: {
  row: JobStatsByJobKey;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <tr
      className={cx(
        'border-b border-ink-100 transition hover:bg-ink-100',
        isSelected && 'bg-primary/5',
      )}
    >
      <td className="px-2 py-2 font-mono text-[12px] text-ink-700">
        <button type="button" onClick={onClick} aria-pressed={isSelected} aria-label={`${isSelected ? '清除' : '筛选'}任务 ${row.job_key}`} className="min-h-9 text-left underline decoration-ink-300 underline-offset-4 hover:text-primary-text">{row.job_key}</button>
      </td>
      <td className="px-2 py-2 text-right font-mono text-[12px] text-ink-700">
        {row.runs}
      </td>
      <td className="px-2 py-2">
        <Badge tone={successTone(row.success_rate)}>
          {(row.success_rate * 100).toFixed(1)}%
        </Badge>
      </td>
      <td className="px-2 py-2 text-right font-mono text-[12px] text-ink-700">
        {formatDuration(row.avg_duration_ms)}
      </td>
      <td className="px-2 py-2">
        <Badge tone={lastStatusTone(row.last_status)}>
          {row.last_status || '-'}
        </Badge>
      </td>
      <td className="px-2 py-2 text-[12px] text-ink-500">
        {formatRelativeTime(row.last_run_at)}
      </td>
    </tr>
  );
}
