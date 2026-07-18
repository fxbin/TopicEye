'use client';

import React, { useState } from 'react';
import { Download } from 'lucide-react';
import { CATEGORIES, SOURCE_TYPE_COLOR_MAP } from '@/lib/design-tokens';
import { contentsApi } from '@/lib/api';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import { Pagination } from '@/components/Pagination';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import type { ContentItem } from '@/types';
import { timeAgo } from '@/lib/datetime';

// ─── Helpers ──

const STATUS_TONE: Record<string, 'neutral' | 'teal' | 'red'> = {
  pending: 'neutral',
  analyzed: 'teal',
  error: 'red',
};

const PAGE_SIZE = 50;

/* ─── Page Component ── */

function exportContentsAsCSV(items: ContentItem[]): void {
  // CSV 安全转义：双引号包裹 + 内部双引号转义
  const esc = (v: any) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const headers = ['ID', '标题', '来源', '分类', '标签', '作者', '发布时间', '状态', 'URL'];
  const rows = items.map((it) => [
    it.id,
    it.title || '',
    it.source_name || it.source_id || '',
    it.category || '',
    Array.isArray(it.tags) ? it.tags.join('; ') : (it.tags || ''),
    it.author || '',
    it.published_at || it.crawled_at || '',
    it.status || '',
    it.url || '',
  ]);
  // 加 BOM 让 Excel 正确识别 UTF-8
  const BOM = '\\uFEFF';
  const csv = BOM + [headers, ...rows]
    .map((r) => r.map(esc).join(','))
    .join('\\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const ts = new Date().toISOString().slice(0, 10);
  a.download = `contents-${ts}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ContentsPage() {
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState<string>('全部');

  type ListPayload = { items: ContentItem[]; total: number };
  const { data, loading, error, refetch } = useFetch<ListPayload>(
    async () => {
      const params: Record<string, unknown> = { page, page_size: PAGE_SIZE, admin_view: true };
      if (category && category !== '全部') params.category = category;
      const res = await contentsApi.list(params);
      return {
        items: (res?.items || []) as ContentItem[],
        total: res?.total ?? (res?.items?.length ?? 0),
      };
    },
    [page, category],
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleCategoryChange = (cat: string) => {
    setCategory(cat);
    setPage(1);
  };

  return (
    <div className="fade-in h-full overflow-y-auto px-10 py-8">
      {/* Header */}
      <div className="mb-7">
        <h1 className="mb-1.5 text-[26px] font-bold text-gray-900">
          内容列表
        </h1>
        <p className="text-[13px] text-gray-400">
          从各信源采集到的原始内容 · 共{' '}
          <b className="font-mono text-gray-600">{total}</b> 条
        </p>
      </div>

      {/* Category Filter Bar */}
      <Toolbar className="mb-5 gap-2">
        {CATEGORIES.map((cat) => {
          const active = category === cat;
          return (
            <button
              key={cat}
              type="button"
              onClick={() => handleCategoryChange(cat)}
              className={cx(
                'rounded-xs border px-3.5 py-1.5 text-xs transition',
                active
                  ? 'border-primary-border bg-primary-light font-semibold text-primary'
                  : 'border-gray-200 bg-white font-medium text-gray-600 hover:border-primary-border hover:text-primary',
              )}
            >
              {cat}
            </button>
          );
        })}
      </Toolbar>

      {/* Error Banner */}
      {error && (
        <div className="mb-4">
          <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <LoadingState label="加载中…" minHeight="200px" />
      )}

      {/* Table */}
      {!loading && items.length > 0 && (
        <div className="mb-2 flex justify-end">
          <Button
            type="button"
            variant="secondary"
            onClick={() => exportContentsAsCSV(items)}
            className="!px-2.5 !py-1 text-[12px]"
          >
            <Download size={12} />
            导出本页 CSV（{items.length} 条）
          </Button>
        </div>
      )}
      {!loading && (
        <Panel className="overflow-hidden">
          {/* Table Header */}
          <div className="grid grid-cols-[3fr_1.2fr_0.8fr_1.5fr_1fr_0.8fr] border-b border-gray-200 bg-gray-50 px-6 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
            <span>标题</span>
            <span>来源</span>
            <span>分类</span>
            <span>标签</span>
            <span>发布时间</span>
            <span>状态</span>
          </div>

          {/* Empty State */}
          {items.length === 0 && (
            <div className="px-6 py-12 text-center text-sm text-gray-400">
              暂无内容数据
            </div>
          )}

          {/* Rows */}
          {items.map((item) => (
            <ContentRow key={item.id} item={item} />
          ))}
        </Panel>
      )}

      {/* Pagination */}
      {!loading && total > 0 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onPage={setPage}
          summary={
            <>
              第 <b className="font-mono">{page}</b> / <b className="font-mono">{totalPages}</b> 页，共 {total} 条
            </>
          }
        />
      )}
    </div>
  );
}

// ─── Content Row ───

function ContentRow({ item }: { item: ContentItem }) {
  const statusKey = item.status || 'pending';
  const statusTone = STATUS_TONE[statusKey] || STATUS_TONE.pending;
  const sourceTypeColor = SOURCE_TYPE_COLOR_MAP[item.source_type] || { bg: '#F3F4F6', color: '#6B7280' };
  const statusLabel: Record<string, string> = {
    pending: '待处理',
    analyzed: '已分析',
    error: '错误',
  };

  return (
    <div className="grid grid-cols-[3fr_1.2fr_0.8fr_1.5fr_1fr_0.8fr] items-center border-b border-gray-100 px-6 py-3.5 text-[13px] transition hover:bg-gray-50">
      {/* 标题 */}
      <div className="truncate pr-3">
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-gray-800 no-underline transition hover:text-primary"
          >
            {item.title || '无标题'}
          </a>
        ) : (
          <span className="font-medium text-gray-800">{item.title || '无标题'}</span>
        )}
      </div>

      {/* 来源 */}
      <div className="flex items-center gap-1.5 overflow-hidden">
        <span className="truncate text-gray-700">
          {item.source_name}
        </span>
        <span
          className="shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold"
          style={{ background: sourceTypeColor.bg, color: sourceTypeColor.color }}
        >
          {item.source_type}
        </span>
      </div>

      {/* 分类 */}
      <div>
        <span className="whitespace-nowrap rounded bg-primary-light px-2 py-1 text-[11px] font-semibold text-primary">
          {item.category}
        </span>
      </div>

      {/* 标签 */}
      <div className="flex flex-wrap gap-1 overflow-hidden">
        {item.tags && item.tags.length > 0
          ? item.tags.slice(0, 3).map((tag) => (
              <span key={tag} className="whitespace-nowrap rounded bg-purple-light px-2 py-0.5 text-[10px] font-medium text-purple">
                {tag}
              </span>
            ))
          : <span className="text-gray-300">-</span>
        }
        {item.tags && item.tags.length > 3 && (
          <span className="text-[10px] text-gray-400">+{item.tags.length - 3}</span>
        )}
      </div>

      {/* 发布时间 */}
      <div className="font-mono text-xs text-gray-500">
        {timeAgo(item.published_at)}
      </div>

      {/* 状态 */}
      <div>
        <Badge tone={statusTone} className="rounded px-2.5 py-1 text-[11px] font-semibold">
          {statusLabel[statusKey] || statusKey}
        </Badge>
      </div>
    </div>
  );
}
