'use client';

import React, { useState, useEffect, useCallback } from 'react';
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

import { Badge, Button, Panel, cx } from '@/components/ui';
import { statsJobsApi, type JobStatsByJobKey, type JobStatsResponse } from '@/lib/api';
import { timeAgoShort as formatRelativeTime } from '@/lib/datetime';

const DAY_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 1, label: '今日' },
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
];

type BadgeTone = 'neutral' | 'primary' | 'teal' | 'amber' | 'purple' | 'red';

const STATUS_TONE: Record<string, BadgeTone> = {
  SUCCESS: 'teal',
  FAILED: 'red',
  TIMEOUT: 'amber',
  SKIPPED: 'neutral',
  RUNNING: 'primary',
};

const STATUS_BAR_COLOR: Record<string, string> = {
  SUCCESS: '#10b981',
  FAILED: '#ef4444',
  TIMEOUT: '#f59e0b',
  SKIPPED: '#94a3b8',
  RUNNING: '#3b82f6',
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

function successTone(rate: number): BadgeTone {
  if (rate >= 0.95) return 'teal';
  if (rate >= 0.8) return 'amber';
  return 'red';
}

function lastStatusTone(status: string | null | undefined): BadgeTone {
  if (!status) return 'neutral';
  return STATUS_TONE[status] || 'neutral';
}

export default function JobStatsPage() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<JobStatsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedJobKey, setSelectedJobKey] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const payload = await statsJobsApi.get(days, selectedJobKey ?? undefined);
      setData(payload);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [days, selectedJobKey]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totals = data?.totals;
  const byStatusMax = data
    ? Math.max(...data.by_status.map((row) => row.count), 1)
    : 1;

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-gray-900">
            <Activity className="h-6 w-6 text-orange" />
            抓取/调度任务监控
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            来自 <code className="rounded bg-gray-100 px-1">job_execution_logs</code> 表的运行数据。
            覆盖所有用 <code className="rounded bg-gray-100 px-1">@track_job</code> 装饰的全局任务。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-sm border border-gray-200">
            {DAY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setDays(opt.value)}
                className={cx(
                  'min-h-8 px-3 py-1 text-[13px] transition',
                  days === opt.value
                    ? 'bg-orange text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-50',
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <Button
            type="button"
            variant="secondary"
            onClick={fetchData}
            disabled={loading}
            className="min-h-8 px-3.5 py-1.5 text-[13px]"
          >
            <RefreshCw className={cx('mr-1 inline h-3.5 w-3.5', loading && 'animate-spin')} />
            刷新
          </Button>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded-sm border border-red-light bg-red-light px-4 py-2.5 text-[13px] text-red">
          {error}
        </div>
      )}

      {/* ── KPI 卡片 ── */}
      <section className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiCard
          icon={<ListChecks className="h-5 w-5 text-blue-600" />}
          label="总运行数"
          value={totals ? totals.total_runs.toLocaleString() : '-'}
          hint={data ? `${data.period.days} 天内` : ''}
        />
        <KpiCard
          icon={<CheckCircle2 className="h-5 w-5 text-emerald-600" />}
          label="成功率"
          value={totals ? `${(totals.success_rate * 100).toFixed(1)}%` : '-'}
          hint={totals ? `${totals.success_count} 成功 / ${totals.failed_count + totals.timeout_count} 失败` : ''}
          tone={successTone(totals?.success_rate ?? 1)}
        />
        <KpiCard
          icon={<Timer className="h-5 w-5 text-amber-600" />}
          label="平均耗时"
          value={formatDuration(totals?.avg_duration_ms)}
          hint={totals ? `最长 ${formatDuration(totals.max_duration_ms)}` : ''}
        />
        <KpiCard
          icon={<AlertTriangle className="h-5 w-5 text-red-600" />}
          label="最近失败"
          value={data ? data.recent_failures.length.toString() : '-'}
          hint={totals ? `${totals.failed_count + totals.timeout_count} 次` : '近 10 条'}
        />
      </section>

      {/* ── 状态分布 ── */}
      <Panel className="mb-6">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
          <Activity className="h-4 w-4 text-gray-500" />
          状态分布
        </h2>
        {data && data.by_status.length > 0 ? (
          <div className="space-y-2">
            {data.by_status.map((row) => (
              <div key={row.status} className="flex items-center gap-3">
                <span className="w-20 text-[12px] text-gray-600">
                  <Badge tone={STATUS_TONE[row.status] || 'neutral'}>{row.status}</Badge>
                </span>
                <div className="h-5 flex-1 overflow-hidden rounded-sm bg-gray-100">
                  <div
                    className="h-full transition-all"
                    style={{
                      width: `${(row.count / byStatusMax) * 100}%`,
                      backgroundColor: STATUS_BAR_COLOR[row.status] || '#94a3b8',
                    }}
                  />
                </div>
                <span className="w-20 text-right font-mono text-[12px] text-gray-700">
                  {row.count.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-[13px] text-gray-500">暂无数据</p>
        )}
      </Panel>

      {/* ── Per-job_key 表格 ── */}
      <Panel className="mb-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <ListChecks className="h-4 w-4 text-gray-500" />
            各任务运行情况
          </h2>
          {selectedJobKey && (
            <button
              type="button"
              onClick={() => setSelectedJobKey(null)}
              className="text-[12px] text-orange hover:underline"
            >
              清除筛选
            </button>
          )}
        </div>
        {data && data.by_job_key.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-gray-200 text-left text-[12px] uppercase tracking-wide text-gray-500">
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
        ) : (
          <p className="py-6 text-center text-[13px] text-gray-500">暂无数据</p>
        )}
      </Panel>

      {/* ── 最近失败 ── */}
      <Panel>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
          <XCircle className="h-4 w-4 text-red-500" />
          最近失败 / 超时
          <span className="text-[12px] font-normal text-gray-500">
            (最多 10 条)
          </span>
        </h2>
        {data && data.recent_failures.length > 0 ? (
          <ul className="space-y-2">
            {data.recent_failures.map((row, idx) => (
              <li
                key={`${row.job_key}-${row.started_at}-${idx}`}
                className="rounded-sm border border-red-light bg-red-light/30 px-3 py-2"
              >
                <div className="mb-1 flex items-center justify-between text-[12px]">
                  <span className="font-mono text-gray-700">{row.job_key}</span>
                  <span className="flex items-center gap-2 text-gray-500">
                    <Badge tone={STATUS_TONE[row.status] || 'neutral'}>{row.status}</Badge>
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
          <p className="py-6 text-center text-[13px] text-gray-500">
            {data ? '🎉 该时间窗口内无失败记录' : ''}
          </p>
        )}
      </Panel>
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: BadgeTone;
}) {
  return (
    <div className="rounded-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
      <div className="mb-1 flex items-center gap-2 text-[12px] text-gray-500">
        {icon}
        {label}
      </div>
      <div className="font-mono text-2xl font-semibold text-gray-900">
        {value}
      </div>
      {hint && (
        <Badge tone={tone} className="mt-1.5">
          {hint}
        </Badge>
      )}
    </div>
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
      onClick={onClick}
      className={cx(
        'cursor-pointer border-b border-gray-100 transition hover:bg-gray-50',
        isSelected && 'bg-orange/5',
      )}
    >
      <td className="px-2 py-2 font-mono text-[12px] text-gray-700">
        {row.job_key}
      </td>
      <td className="px-2 py-2 text-right font-mono text-[12px] text-gray-700">
        {row.runs}
      </td>
      <td className="px-2 py-2">
        <Badge tone={successTone(row.success_rate)}>
          {(row.success_rate * 100).toFixed(1)}%
        </Badge>
      </td>
      <td className="px-2 py-2 text-right font-mono text-[12px] text-gray-700">
        {formatDuration(row.avg_duration_ms)}
      </td>
      <td className="px-2 py-2">
        <Badge tone={lastStatusTone(row.last_status)}>
          {row.last_status || '-'}
        </Badge>
      </td>
      <td className="px-2 py-2 text-[12px] text-gray-500">
        {formatRelativeTime(row.last_run_at)}
      </td>
    </tr>
  );
}
