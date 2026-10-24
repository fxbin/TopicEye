'use client';

/**
 * Prompt 管理（只读注册表 + 调用统计）。
 *
 * 视觉口径（#125 v2 换壳，与 sources / feedback 定稿一致）：文字层级 ink 三档
 * （900 标题 / 700 正文 / 500 次要），分隔与浅底 border-ink-200 / bg-ink-100，
 * 语义色（amber / primary）一律走项目 token，数字用 font-mono / tabular-nums。
 */

import React, { useState } from 'react';
import {
  Clock,
  Coins,
  FileCode2,
  Hash,
  Loader2,
  RefreshCw,
  ScrollText,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner, AdminModal } from '@/components/admin-ui';
import { LoadingState, EmptyState, ErrorState } from '@/components/StateView';
import { adminPromptsApi } from '@/lib/api';
import { useFetch } from '@/hooks/useFetch';
import { formatDateTime } from '@/lib/datetime';

const SCENE_FILTERS = ['', 'analysis', 'classification', 'creation_explore', 'creation_focus', 'creation_converge'];

const SCENE_LABELS: Record<string, string> = {
  analysis: '内容分析',
  classification: '内容分类',
  creation_explore: '创作探索',
  creation_focus: '创作聚焦',
  creation_converge: '创作收敛',
};

export default function PromptsAdminPage() {
  const { currentUser, authLoading } = useAppContext();
  const [sceneFilter, setSceneFilter] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data: registry, loading, error, refetch: fetchPrompts } = useFetch(
    () => adminPromptsApi.list(sceneFilter || undefined),
    [sceneFilter],
    { enabled: !authLoading && currentUser?.role === 'admin' },
  );
  const items = registry?.items ?? [];
  const { data: detailResponse, loading: detailLoading, error: detailError, refetch: fetchDetail } = useFetch(
    async () => ({ id: selectedId, detail: await adminPromptsApi.detail(selectedId!) }),
    [selectedId],
    { enabled: selectedId !== null, initialLoading: false },
  );
  const detail = detailResponse?.id === selectedId ? detailResponse.detail : null;

  if (authLoading) return <LoadingState label="加载中..." />;
  if (currentUser?.role !== 'admin') {
    return (
      <AdminPageShell>
        <AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner>
      </AdminPageShell>
    );
  }

  return (
    <AdminPageShell maxWidth={1200}>
      <AdminPageHeader
        title="Prompt 管理"
        icon={ScrollText}
        description="查看所有 LLM 提示词模板、源码位置和调用统计（只读）"
        actions={
          <Button variant="secondary" onClick={fetchPrompts} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            刷新
          </Button>
        }
      />

      {/* Scene filter */}
      <div className="flex flex-wrap items-center gap-2">
        {SCENE_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSceneFilter(s)}
            aria-pressed={sceneFilter === s}
            className={cx(
              'rounded-full px-3 py-1 text-[12px] font-semibold transition',
              sceneFilter === s
                ? 'bg-primary text-white'
                : 'bg-ink-100 text-ink-500 hover:bg-ink-200',
            )}
          >
            {s ? SCENE_LABELS[s] || s : '全部'}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingState label="加载 Prompt 列表..." />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void fetchPrompts()} panel />
      ) : items.length === 0 ? (
        <EmptyState icon={ScrollText} title="暂无 Prompt 记录" desc="启动时自动同步" />
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Panel
              key={item.id}
              className="p-0 transition hover:border-primary/30 hover:shadow-sm focus-within:ring-2 focus-within:ring-primary-border"
            >
              <button type="button" onClick={() => setSelectedId(item.id)} aria-label={`查看 ${item.name} 的 Prompt 详情`} className="block w-full rounded-sm p-4 text-left focus-visible:outline-none">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-mono text-sm font-bold text-ink-900">{item.name}</span>
                    <Badge tone="neutral" className="rounded px-1.5 py-0.5 text-[10px]">{item.scene}</Badge>
                  </div>
                  <div className="text-[12px] text-ink-500">{item.description}</div>
                  <div className="mt-1 flex items-center gap-3 text-[11px] text-ink-500">
                    <span className="flex items-center gap-0.5">
                      <FileCode2 size={11} />
                      {item.source_file.split(':').pop()}
                    </span>
                    {item.updated_at && (
                      <span className="flex items-center gap-0.5">
                        <Clock size={11} />
                        {formatDateTime(item.updated_at)}
                      </span>
                    )}
                  </div>
                </div>
                {/* 7-day stats */}
                <div className="shrink-0 text-right">
                  {item.stats_7d.call_count_7d > 0 ? (
                    <>
                      <div className="font-mono text-lg font-black text-primary">
                        {item.stats_7d.call_count_7d}
                      </div>
                      <div className="text-[10px] text-ink-500">7天调用</div>
                      {item.stats_7d.total_cost_7d > 0 && (
                        <div className="mt-0.5 flex items-center justify-end gap-0.5 font-mono text-[10px] text-ink-500">
                          <Coins size={10} />
                          ${item.stats_7d.total_cost_7d.toFixed(2)}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-[11px] text-ink-300">无调用</div>
                  )}
                </div>
              </div>
              </button>
            </Panel>
          ))}
        </div>
      )}

      {/* Detail Modal */}
      {selectedId !== null && (
        <AdminModal
          title="Prompt 详情"
          onClose={() => {
            setSelectedId(null);
          }}
          maxWidth={800}
        >
          {detailLoading || (!detail && !detailError) ? (
            <div className="py-8 text-center">
              <Loader2 size={20} className="mx-auto mb-2 animate-spin text-ink-500" />
              <span className="text-[13px] text-ink-500">加载中...</span>
            </div>
          ) : detail ? (
            <div className="space-y-4">
              {/* Metadata */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-bold text-ink-900">{detail.name}</span>
                <Badge tone="primary" className="rounded px-2 py-0.5 text-[10px]">{detail.scene}</Badge>
                <span className="flex items-center gap-0.5 font-mono text-[11px] text-ink-500">
                  <Hash size={10} />
                  {detail.version_hash.slice(0, 12)}
                </span>
              </div>
              <p className="text-[12px] text-ink-500">{detail.description}</p>
              <div className="flex items-center gap-1 text-[11px] text-ink-500">
                <FileCode2 size={11} />
                <code className="rounded bg-ink-100 px-1.5 py-0.5">{detail.source_file}</code>
              </div>

              {/* 30-day stats */}
              <div className="grid grid-cols-2 gap-3 rounded-sm bg-ink-100 p-3 sm:grid-cols-4">
                <StatBox label="30天调用" value={String(detail.stats_30d.call_count)} />
                <StatBox label="总费用" value={`$${detail.stats_30d.total_cost.toFixed(2)}`} />
                <StatBox label="输入Token" value={detail.stats_30d.total_input_tokens.toLocaleString()} />
                <StatBox label="平均耗时" value={`${detail.stats_30d.avg_duration_ms}ms`} />
              </div>

              {/* Daily trend */}
              {detail.daily_trend.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-500">调用趋势</div>
                  <div className="flex h-8 items-end gap-0.5">
                    {detail.daily_trend.map((d) => {
                      const maxCalls = Math.max(...detail.daily_trend.map((x) => x.calls), 1);
                      const heightPct = (d.calls / maxCalls) * 100;
                      return (
                        <div
                          key={d.date}
                          className="flex-1 rounded-t-sm bg-primary/30 transition hover:bg-primary/50"
                          style={{ height: `${Math.max(2, heightPct)}%` }}
                          title={`${d.date}: ${d.calls} 次, $${d.cost.toFixed(4)}`}
                        />
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Full content */}
              <div>
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-500">Prompt 全文</div>
                <pre className="max-h-[300px] overflow-auto rounded-sm bg-ink-900 p-3 text-[12px] leading-relaxed text-ink-100">
                  {detail.full_content}
                </pre>
              </div>
            </div>
          ) : (
            <div role="alert" className="py-8 text-center text-[13px] text-ink-700">{detailError || '加载失败'}<button type="button" className="ml-3 underline" onClick={() => void fetchDetail()}>重试详情</button></div>
          )}
        </AdminModal>
      )}
    </AdminPageShell>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <div className="font-mono text-base font-black text-ink-900">{value}</div>
      <div className="text-[10px] text-ink-500">{label}</div>
    </div>
  );
}
