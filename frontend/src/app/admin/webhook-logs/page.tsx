'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  RefreshCw,
  Send,
  XCircle,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Panel, cx } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner } from '@/components/admin-ui';
import { LoadingState } from '@/components/StateView';
import { dailyReportApi } from '@/lib/api';
import type { WebhookDeliveryLogItem } from '@/lib/api/_domains';

const PAGE_SIZE = 30;

const EVENT_TYPE_LABELS: Record<string, string> = {
  source_failure: '信源故障',
  trending: '热点推送',
  daily_report: '日报推送',
  test: '测试推送',
};

const SEVERITY_LABELS: Record<string, string> = {
  warning: '警告',
  critical: '严重',
  info: '通知',
};

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export default function WebhookLogsPage() {
  const { currentUser, authLoading } = useAppContext();
  const [logs, setLogs] = useState<WebhookDeliveryLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [eventType, setEventType] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await dailyReportApi.listWebhookLogs({
        event_type: eventType,
        limit: PAGE_SIZE,
        offset,
      });
      setLogs(res.items);
      setTotal(res.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [eventType, offset]);

  useEffect(() => {
    if (!authLoading && currentUser?.role === 'admin') {
      void fetchData();
    }
  }, [fetchData, authLoading, currentUser]);

  // Reset offset when filter changes
  const handleFilterChange = (value: string | undefined) => {
    setEventType(value);
    setOffset(0);
  };

  if (authLoading) return <LoadingState label="加载中..." />;
  if (currentUser?.role !== 'admin') {
    return (
      <AdminPageShell>
        <AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner>
      </AdminPageShell>
    );
  }

  const successCount = logs.filter((l) => l.success).length;
  const failCount = logs.length - successCount;
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <AdminPageShell maxWidth={1200}>
      <AdminPageHeader
        title="Webhook 推送日志"
        icon={Send}
        description="记录每次 Webhook 推送尝试的状态、耗时与错误详情"
        actions={
          <button
            onClick={() => void fetchData()}
            disabled={loading}
            className="flex items-center gap-1 rounded-sm border border-gray-200 bg-white px-2.5 py-1 text-[12px] font-bold text-gray-600 transition hover:border-gray-300 disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        }
      />

      {error && (
        <div className="mb-4">
          <AdminNoticeBanner tone="red">{error}</AdminNoticeBanner>
        </div>
      )}

      {/* Summary + Filter */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {loading ? (
            <span className="text-[12px] text-gray-400">加载中...</span>
          ) : (
            <>
              <Badge tone="neutral">共 {total} 条</Badge>
              {successCount > 0 && (
                <Badge tone="teal">
                  <CheckCircle2 size={10} className="mr-0.5" />
                  成功 {successCount}
                </Badge>
              )}
              {failCount > 0 && (
                <Badge tone="red">
                  <XCircle size={10} className="mr-0.5" />
                  失败 {failCount}
                </Badge>
              )}
            </>
          )}
        </div>

        {/* Event type filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-bold text-gray-500">事件类型</span>
          <button
            onClick={() => handleFilterChange(undefined)}
            className={cx(
              'rounded-sm border px-2 py-0.5 text-[11px] font-bold transition',
              !eventType
                ? 'border-primary bg-primary text-white'
                : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
            )}
          >
            全部
          </button>
          {Object.entries(EVENT_TYPE_LABELS).map(([key, label]) => (
            <button
              key={key}
              onClick={() => handleFilterChange(key)}
              className={cx(
                'rounded-sm border px-2 py-0.5 text-[11px] font-bold transition',
                eventType === key
                  ? 'border-primary bg-primary text-white'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Log table */}
      {loading && logs.length === 0 ? (
        <LoadingState label="加载推送日志..." />
      ) : logs.length === 0 ? (
        <Panel className="p-8 text-center">
          <Send size={32} className="mx-auto mb-3 text-gray-300" />
          <p className="text-[13px] text-gray-400">暂无 Webhook 推送日志</p>
        </Panel>
      ) : (
        <Panel className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12px]">
              <thead className="border-b border-gray-200 bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-3 py-2.5 font-bold">状态</th>
                  <th className="px-3 py-2.5 font-bold">事件</th>
                  <th className="px-3 py-2.5 font-bold">标题</th>
                  <th className="px-3 py-2.5 font-bold">HTTP</th>
                  <th className="px-3 py-2.5 font-bold">耗时</th>
                  <th className="px-3 py-2.5 font-bold">时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {logs.map((log) => {
                  const expanded = expandedId === log.id;
                  const hasDetail = !!(log.error_message || log.response_preview);
                  return (
                    <React.Fragment key={log.id}>
                      <tr
                        className={cx(
                          'transition hover:bg-gray-50',
                          hasDetail && 'cursor-pointer',
                          !log.success && 'bg-red-50/30',
                        )}
                        onClick={() => hasDetail && setExpandedId(expanded ? null : log.id)}
                      >
                        <td className="px-3 py-2.5">
                          {log.success ? (
                            <CheckCircle2 size={14} className="text-teal-500" />
                          ) : (
                            <XCircle size={14} className="text-red-500" />
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5">
                          <span className="font-medium text-gray-700">
                            {EVENT_TYPE_LABELS[log.event_type] || log.event_type}
                          </span>
                          {log.severity && log.severity !== 'warning' && (
                            <span
                              className={cx(
                                'ml-1 rounded px-1 text-[9px] font-bold',
                                log.severity === 'critical'
                                  ? 'bg-red-100 text-red-600'
                                  : 'bg-blue-100 text-blue-600',
                              )}
                            >
                              {SEVERITY_LABELS[log.severity] || log.severity}
                            </span>
                          )}
                        </td>
                        <td className="max-w-[320px] truncate px-3 py-2.5 text-gray-600" title={log.title}>
                          {log.title}
                        </td>
                        <td className="px-3 py-2.5">
                          {log.status_code ? (
                            <span
                              className={cx(
                                'font-mono font-bold',
                                log.status_code >= 200 && log.status_code < 300
                                  ? 'text-teal-600'
                                  : log.status_code >= 400
                                    ? 'text-red-600'
                                    : 'text-gray-500',
                              )}
                            >
                              {log.status_code}
                            </span>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5">
                          <span className="flex items-center gap-0.5 font-mono text-gray-500">
                            <Clock size={10} />
                            {formatDuration(log.duration_ms)}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-gray-400">
                          {formatTime(log.created_at)}
                        </td>
                      </tr>
                      {expanded && hasDetail && (
                        <tr className="bg-gray-50/50">
                          <td colSpan={6} className="px-3 py-3">
                            <div className="space-y-2">
                              {log.error_message && (
                                <div>
                                  <div className="mb-0.5 flex items-center gap-1 text-[10px] font-bold text-red-500">
                                    <AlertCircle size={10} />
                                    错误信息
                                  </div>
                                  <pre className="overflow-x-auto rounded-sm bg-red-50 p-2 text-[11px] text-red-700">
                                    {log.error_message}
                                  </pre>
                                </div>
                              )}
                              {log.response_preview && (
                                <div>
                                  <div className="mb-0.5 text-[10px] font-bold text-gray-500">
                                    响应预览
                                  </div>
                                  <pre className="overflow-x-auto rounded-sm bg-gray-100 p-2 text-[11px] text-gray-600">
                                    {log.response_preview}
                                  </pre>
                                </div>
                              )}
                              <div className="text-[10px] text-gray-400">
                                Webhook URL: {log.webhook_url_preview}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-gray-200 px-3 py-2.5">
              <span className="text-[11px] text-gray-400">
                第 {currentPage}/{totalPages} 页 · 共 {total} 条
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={!hasPrev}
                  className="flex items-center gap-0.5 rounded-sm border border-gray-200 px-2 py-1 text-[11px] font-bold text-gray-600 transition hover:border-gray-300 disabled:opacity-40"
                >
                  <ChevronLeft size={12} />
                  上一页
                </button>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={!hasNext}
                  className="flex items-center gap-0.5 rounded-sm border border-gray-200 px-2 py-1 text-[11px] font-bold text-gray-600 transition hover:border-gray-300 disabled:opacity-40"
                >
                  下一页
                  <ChevronRight size={12} />
                </button>
              </div>
            </div>
          )}
        </Panel>
      )}
    </AdminPageShell>
  );
}
