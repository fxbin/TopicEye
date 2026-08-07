'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Loader2,
  ShieldCheck,
  X,
} from 'lucide-react';
import EvidenceTag from '@/components/EvidenceTag';
import SourceBadge from '@/components/SourceBadge';
import { useAppContext } from '@/components/ClientLayout';
import { cx } from '@/components/ui';
import { trendsApi } from '@/lib/api';
import type {
  TrendEvidenceFilter,
  TrendEvidenceItem,
  TrendEvidenceRequest,
  TrendEvidenceResponse,
} from '@/types/trends';
import { useDialogFocus } from '@/components/useDialogFocus';

const PAGE_SIZE = 20;

const FILTERS: Array<{ key: TrendEvidenceFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'selected', label: '已入选' },
  { key: 'evidenced', label: '有来源证据' },
];

function requestKey(request: TrendEvidenceRequest | null) {
  if (!request) return '';
  return request.kind === 'topic'
    ? `topic:${request.topicId}:${request.date}`
    : `keyword:${request.keyword}:${request.days}`;
}

function formatItemTime(item: TrendEvidenceItem) {
  const value = item.time_basis === 'published_at' ? item.published_at : item.crawled_at;
  if (!value) return '时间未知';
  const date = value.replace('T', ' ').slice(0, 16);
  return `${item.time_basis === 'published_at' ? '发布时间' : '抓取时间'} · ${date}`;
}

function formatScore(score: number | null) {
  return typeof score === 'number' ? Math.round(score) : null;
}

function SnapshotNotice({ data }: { data: TrendEvidenceResponse }) {
  const isComplete = data.summary.provenance_status === 'complete';
  const dateRange = [data.scope.start_date, data.scope.end_date].filter(Boolean).join(' 至 ');
  const calculation = data.calculation.version
    ? `计算版本 ${data.calculation.version}`
    : '历史快照未记录计算版本';

  return (
    <div
      className={cx(
        'rounded-sm border px-3 py-2.5 text-[11px] leading-5',
        isComplete
          ? 'border-emerald-100 bg-emerald-50/70 text-emerald-800'
          : 'border-amber-200 bg-amber-50 text-amber-800',
      )}
    >
      <div className="flex items-center gap-1.5 font-bold">
        {isComplete ? <ShieldCheck size={14} /> : <AlertTriangle size={14} />}
        {isComplete ? '完整可溯源快照' : '历史快照：成员记录不完整'}
      </div>
      <div className="mt-0.5">
        {dateRange && <span>{dateRange} · </span>}
        {calculation}
        {data.calculation.event_members_excluded && <span> · 已排除已合并事件成员</span>}
      </div>
      {!isComplete && data.message && <div className="mt-1">{data.message}</div>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-sm border border-gray-100 bg-white px-2.5 py-2">
      <div className="font-mono text-base font-black leading-none text-gray-900">{value}</div>
      <div className="mt-1 text-[10px] font-bold text-gray-400">{label}</div>
    </div>
  );
}

function DailyCounts({ data }: { data: TrendEvidenceResponse }) {
  const max = Math.max(...data.daily_counts.map((item) => item.count), 1);
  if (data.daily_counts.length === 0) return null;

  return (
    <div className="flex items-end gap-1" aria-label="每日内容数量">
      {data.daily_counts.map((item) => (
        <div key={item.date} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <span
            title={`${item.date}: ${item.count} 条`}
            className="w-full rounded-t-sm bg-primary/70"
            style={{ height: Math.max(4, Math.round((item.count / max) * 28)) }}
          />
          <span className="max-w-full truncate font-mono text-[9px] text-gray-400">{item.date.slice(5)}</span>
        </div>
      ))}
    </div>
  );
}

function EvidenceRow({ item }: { item: TrendEvidenceItem }) {
  const { openReader } = useAppContext();
  const score = formatScore(item.score);

  return (
    <li className="rounded-sm border border-gray-200 bg-white px-3.5 py-3 shadow-[0_2px_8px_rgba(15,23,42,0.025)]">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          {item.content_id ? (
            <button
              type="button"
              onClick={() => openReader(item.content_id!)}
              className="block max-w-full text-left text-[13px] font-bold leading-5 text-gray-900 hover:text-primary"
              title="站内阅读"
            >
              {item.title}
            </button>
          ) : (
            <div className="text-[13px] font-bold leading-5 text-gray-900">{item.title}</div>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
            <SourceBadge
              name={item.source_name}
              type={item.source_type}
              compact
              fallback={item.platform || undefined}
            />
            <span className="text-[10px] text-gray-400">{formatItemTime(item)}</span>
          </div>
        </div>
        {score !== null && (
          <div className="shrink-0 text-right">
            <div className="font-mono text-sm font-black text-primary">{score}</div>
            <div className="text-[9px] font-bold text-gray-400">SCORE</div>
          </div>
        )}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {item.selected && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700">
            <Check size={10} /> 已入选
          </span>
        )}
        <EvidenceTag mark={item.evidence_mark} />
        {item.content_id && (
          <button
            type="button"
            onClick={() => openReader(item.content_id!)}
            className="ml-auto inline-flex items-center gap-1 text-[11px] font-bold text-gray-500 hover:text-primary"
          >
            <FileText size={12} /> 站内阅读
          </button>
        )}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-bold text-gray-500 hover:text-primary"
          >
            <ExternalLink size={12} /> 原文
          </a>
        )}
      </div>
    </li>
  );
}

export default function TrendEvidenceDrawer({
  request,
  onClose,
}: {
  request: TrendEvidenceRequest | null;
  onClose: () => void;
}) {
  const isOpen = request !== null;
  const [filter, setFilter] = useState<TrendEvidenceFilter>('all');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TrendEvidenceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = requestKey(request);
  const previousKeyRef = useRef(key);
  const loadSerialRef = useRef(0);
  const { dialogRef, onKeyDown } = useDialogFocus<HTMLDivElement>(isOpen, onClose);

  const load = useCallback(async () => {
    if (!request) return;
    const serial = ++loadSerialRef.current;
    setLoading(true);
    setError(null);
    try {
      const result = request.kind === 'topic'
        ? await trendsApi.topicEvidence(request.topicId, request.date, { filter, page, page_size: PAGE_SIZE })
        : await trendsApi.keywordEvidence(request.keyword, { days: request.days, filter, page, page_size: PAGE_SIZE });
      if (serial === loadSerialRef.current) setData(result);
    } catch (err) {
      if (serial === loadSerialRef.current) {
        setData(null);
        setError(err instanceof Error ? err.message : '暂时无法加载可溯源内容');
      }
    } finally {
      if (serial === loadSerialRef.current) setLoading(false);
    }
  }, [filter, page, request]);

  useEffect(() => {
    if (!request) return;
    if (previousKeyRef.current !== key) {
      previousKeyRef.current = key;
      loadSerialRef.current += 1;
      setFilter('all');
      setPage(1);
      setData(null);
      setError(null);
      // If this is already the default filter/page (the usual first open),
      // React will bail out of the state updates above. Load immediately so
      // the drawer never remains empty waiting for a rerender that will not
      // happen. Otherwise the state update below triggers the next effect.
      if (filter === 'all' && page === 1) {
        void load();
      }
      return;
    }
    void load();
  }, [filter, key, load, page, request]);

  const pageCount = useMemo(
    () => Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE)),
    [data?.total],
  );
  const title = request?.kind === 'topic'
    ? `${request.topicName} · ${request.date}`
    : request
      ? `关键词 · ${request.keyword}`
      : '来源明细';

  const switchFilter = (nextFilter: TrendEvidenceFilter) => {
    setFilter(nextFilter);
    setPage(1);
  };

  return (
    <>
      <div
        aria-hidden="true"
        className={cx(
          'fixed inset-0 z-40 bg-black/40 transition-opacity duration-300',
          isOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={onClose}
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="trend-evidence-title"
        aria-hidden={!isOpen}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={cx(
          'fixed right-0 top-0 z-50 flex h-full w-full max-w-[640px] flex-col bg-[#F7F8FA] shadow-2xl transition-transform duration-300',
          isOpen ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-gray-200 bg-white px-5 py-4">
          <div className="min-w-0">
            <div className="text-[11px] font-bold tracking-wide text-primary">TREND PROVENANCE</div>
            <h2 id="trend-evidence-title" className="mt-0.5 truncate text-base font-black text-gray-900">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-xs text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="关闭来源明细"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && !data ? (
            <div className="grid min-h-[280px] place-items-center text-sm text-gray-400">
              <span className="inline-flex items-center gap-2"><Loader2 size={17} className="animate-spin" />加载来源明细…</span>
            </div>
          ) : error ? (
            <div className="grid min-h-[280px] place-items-center text-center">
              <div>
                <p className="text-sm font-bold text-gray-700">{error}</p>
                <button type="button" onClick={() => void load()} className="mt-3 text-xs font-bold text-primary hover:underline">重试</button>
              </div>
            </div>
          ) : data ? (
            <div className="space-y-4">
              <SnapshotNotice data={data} />

              <section className="grid grid-cols-4 gap-2" aria-label="范围统计">
                <Metric label="内容" value={data.summary.content_count} />
                <Metric label="信源" value={data.summary.source_count} />
                <Metric label="已入选" value={data.summary.selected_count} />
                <Metric label="有证据" value={data.summary.evidenced_count} />
              </section>

              <section className="rounded-sm border border-gray-100 bg-white px-3 py-2.5">
                <div className="mb-1.5 text-[10px] font-bold text-gray-400">每日贡献内容</div>
                <DailyCounts data={data} />
              </section>

              <div className="flex flex-wrap gap-1.5" role="group" aria-label="来源明细筛选">
                {FILTERS.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    aria-pressed={filter === item.key}
                    onClick={() => switchFilter(item.key)}
                    className={cx(
                      'rounded-full border px-2.5 py-1 text-[11px] font-bold transition',
                      filter === item.key
                        ? 'border-primary-border bg-primary-light text-primary'
                        : 'border-gray-200 bg-white text-gray-500 hover:border-primary-border hover:text-primary',
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              {loading && <div className="text-center text-xs text-gray-400">正在更新…</div>}
              {data.items.length === 0 ? (
                <div className="rounded-sm border border-dashed border-gray-200 bg-white px-4 py-12 text-center text-sm text-gray-400">
                  这个范围内没有符合条件的内容。
                </div>
              ) : (
                <ul className="space-y-2.5">
                  {data.items.map((item, index) => (
                    <EvidenceRow key={`${item.content_id ?? item.url ?? item.title}-${index}`} item={item} />
                  ))}
                </ul>
              )}

              {data.total > 0 && (
                <nav className="flex items-center justify-between gap-3 pt-1" aria-label="来源明细分页">
                  <span className="text-[11px] text-gray-400">共 {data.total} 条 · 第 {page} / {pageCount} 页</span>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      disabled={page <= 1 || loading}
                      onClick={() => setPage((current) => Math.max(1, current - 1))}
                      className="inline-flex items-center gap-1 rounded-xs border border-gray-200 bg-white px-2 py-1 text-[11px] font-bold text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <ChevronLeft size={13} /> 上一页
                    </button>
                    <button
                      type="button"
                      disabled={page >= pageCount || loading}
                      onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
                      className="inline-flex items-center gap-1 rounded-xs border border-gray-200 bg-white px-2 py-1 text-[11px] font-bold text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      下一页 <ChevronRight size={13} />
                    </button>
                  </div>
                </nav>
              )}
            </div>
          ) : null}
        </div>
      </aside>
    </>
  );
}
