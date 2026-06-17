'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { CATEGORIES, SOURCE_TYPE_COLOR_MAP } from '@/lib/design-tokens';
import { contentsApi } from '@/lib/api';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import type { ContentItem } from '@/types';

// ─── Helpers ──

function parseUTC(s: string): Date {
  const normalized = s.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(s) ? s : s + 'Z';
  return new Date(normalized);
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '-';
  const date = parseUTC(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return '刚刚';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  const months = Math.floor(days / 30);
  return `${months} 个月前`;
}

const STATUS_TONE: Record<string, 'neutral' | 'teal' | 'red'> = {
  pending: 'neutral',
  analyzed: 'teal',
  error: 'red',
};

const PAGE_SIZE = 50;

// ─── Spinner ───

function Spinner() {
  return (
    <span className="inline-block h-[18px] w-[18px] animate-spin rounded-full border-2 border-gray-200 border-t-primary" />
  );
}

// ─── Page Component ───

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
  const [items, setItems] = useState<ContentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<string>('全部');

  // ─── Fetch contents ───
  const fetchContents = useCallback(async (p: number, cat: string) => {
    try {
      setLoading(true);
      setError(null);
      const params: Record<string, unknown> = { page: p, page_size: PAGE_SIZE, admin_view: true };
      if (cat && cat !== '全部') params.category = cat;
      const res = await contentsApi.list(params);
      const list = res?.items || [];
      setItems(list as ContentItem[]);
      setTotal(res?.total ?? list.length);
      setPage(res?.page ?? p);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '加载内容列表失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchContents(1, category);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleCategoryChange = (cat: string) => {
    setCategory(cat);
    setPage(1);
  };

  const handlePrev = () => {
    if (page > 1) {
      const next = page - 1;
      setPage(next);
      fetchContents(next, category);
    }
  };

  const handleNext = () => {
    if (page < totalPages) {
      const next = page + 1;
      setPage(next);
      fetchContents(next, category);
    }
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
        <div className="mb-4 flex items-center justify-between rounded-sm bg-red-light px-4 py-2.5 text-[13px] text-red">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="cursor-pointer border-0 bg-transparent px-1 text-base font-bold leading-none text-red"
          >
            ×
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="flex h-[200px] items-center justify-center gap-2.5 text-sm text-gray-400">
          <Spinner />
          <span>加载中…</span>
        </div>
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
        <div className="mt-4 flex items-center justify-between gap-3 text-[13px] text-gray-500">
          <span>
            第 <b className="font-mono">{page}</b> / <b className="font-mono">{totalPages}</b> 页，共 {total} 条
          </span>
          <div className="flex gap-2">
            <Button
              type="button"
              onClick={handlePrev}
              disabled={page <= 1}
              variant="secondary"
              className={cx('min-h-0 px-4 py-1.5 text-[13px] font-medium', page <= 1 && 'cursor-not-allowed bg-gray-100 text-gray-300')}
            >
              <ChevronLeft size={14} strokeWidth={2} />
              上一页
            </Button>
            <Button
              type="button"
              onClick={handleNext}
              disabled={page >= totalPages}
              variant="secondary"
              className={cx('min-h-0 px-4 py-1.5 text-[13px] font-medium', page >= totalPages && 'cursor-not-allowed bg-gray-100 text-gray-300')}
            >
              下一页
              <ChevronRight size={14} strokeWidth={2} />
            </Button>
          </div>
        </div>
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
