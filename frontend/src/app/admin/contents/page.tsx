'use client';

import { useEffect, useState } from 'react';
import { Copy, Download, ExternalLink, Newspaper } from 'lucide-react';
import { CATEGORIES, SOURCE_TYPE_COLOR_MAP } from '@/lib/design-tokens';
import { contentsApi } from '@/lib/api';
import { Badge, Button } from '@/components/ui';
import { Pagination } from '@/components/Pagination';
import { buildContentsCsv } from './_csv-utils';
import { useFetch } from '@/hooks/useFetch';
import { AdminPageShell, AdminPageHeader } from '@/components/admin-ui';
import { AdminEmptyState, AdminFilterChips, AdminFilters, AdminTable, toast } from '@/components/admin';
import type { AdminFilterChip, AdminTableColumn } from '@/components/admin';
import type { ContentItem } from '@/types';
import { timeAgo } from '@/lib/datetime';

// ─── 常量 ──

const CONTENT_STATUS_TONE: Record<string, 'neutral' | 'teal' | 'red'> = {
  pending: 'neutral',
  analyzed: 'teal',
  error: 'red',
};

const CONTENT_STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  analyzed: '已分析',
  error: '错误',
};

const DEFAULT_PAGE_SIZE = 50;
const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;

/* ─── URL query 同步（#121 四页试点之一）──
 * 挂载时从 location.search 恢复初始状态；此后筛选/搜索/页码变化用
 * history.replaceState 覆写 query——不产生历史记录、不触发导航，
 * 刻意不用 useSearchParams 以避开 Suspense 边界。
 * 默认值（第 1 页、全部分类、空搜索、每页 50）不写入 query，保持 URL 干净。 */

type ContentsQueryState = { page: number; pageSize: number; category: string; q: string };

function defaultContentsQueryState(): ContentsQueryState {
  return { page: 1, pageSize: DEFAULT_PAGE_SIZE, category: '全部', q: '' };
}

function readInitialStateFromLocation(): ContentsQueryState {
  const sp = new URLSearchParams(window.location.search);
  const page = Math.max(1, Number.parseInt(sp.get('page') ?? '', 10) || 1);
  const rawPageSize = Number.parseInt(sp.get('page_size') ?? '', 10);
  const pageSize = (PAGE_SIZE_OPTIONS as readonly number[]).includes(rawPageSize)
    ? rawPageSize
    : DEFAULT_PAGE_SIZE;
  const rawCategory = sp.get('category') ?? '全部';
  const category = (CATEGORIES as readonly string[]).includes(rawCategory) ? rawCategory : '全部';
  const q = sp.get('q') ?? '';
  return { page, pageSize, category, q };
}

/* ─── Page Component ── */

function exportContentsAsCSV(items: ContentItem[]): void {
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
  // #124：BOM 与换行此前写成双反斜杠字面量（Excel 打开是一整行），
  // 生成逻辑抽到 _csv-utils.ts 纯函数并有回归测试
  const csv = buildContentsCsv(headers, rows);
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
  // 两段式恢复：SSR 与首帧一律用默认值（防 hydration mismatch——惰性读
  // location 会让带参数直达时服务端/客户端首帧不一致），挂载后再从 URL 恢复
  const [initial] = useState(defaultContentsQueryState);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [category, setCategory] = useState(initial.category);
  const [q, setQ] = useState(initial.q);
  const [didRestore, setDidRestore] = useState(false);

  // 挂载后恢复 URL 状态（两段式的第二段），随后放行首拉
  useEffect(() => {
    const restored = readInitialStateFromLocation();
    if (restored.page !== initial.page) setPage(restored.page);
    if (restored.pageSize !== initial.pageSize) setPageSize(restored.pageSize);
    if (restored.category !== initial.category) setCategory(restored.category);
    if (restored.q !== initial.q) setQ(restored.q);
    setDidRestore(true);
    // 仅挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  type ListPayload = { items: ContentItem[]; total: number };
  const { data, loading, error, refetch } = useFetch<ListPayload>(
    async () => {
      const params: Record<string, unknown> = { page, page_size: pageSize, admin_view: true };
      if (category && category !== '全部') params.category = category;
      if (q.trim()) params.q = q.trim();
      const res = await contentsApi.list(params);
      return {
        items: (res?.items || []) as ContentItem[],
        total: res?.total ?? (res?.items?.length ?? 0),
      };
    },
    [page, pageSize, category, q],
    // 恢复完成前不拉，避免默认值先打一发再被 URL 值重打的double fetch
    { enabled: didRestore },
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // URL query 覆写：与恢复逻辑对称，非默认值才落 query（恢复完成前不写，
  // 防止把直达 URL 清成默认态）
  useEffect(() => {
    if (!didRestore) return;
    const sp = new URLSearchParams();
    if (page > 1) sp.set('page', String(page));
    if (q.trim()) sp.set('q', q.trim());
    if (category !== '全部') sp.set('category', category);
    if (pageSize !== DEFAULT_PAGE_SIZE) sp.set('page_size', String(pageSize));
    const qs = sp.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [didRestore, page, pageSize, category, q]);

  // 恢复的页码可能越过当前筛选下的总页数（如书签里存着 page=99），收回最后一页
  useEffect(() => {
    if (!loading && page > totalPages) setPage(totalPages);
  }, [loading, page, totalPages]);

  /* ─── 筛选与动作 ── */

  const hasActiveFilters = q.trim() !== '' || category !== '全部';

  const handleSearchChange = (value: string) => {
    setQ(value);
    setPage(1);
  };

  const handleCategoryChange = (cat: string) => {
    setCategory(cat);
    setPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  const clearAllFilters = () => {
    setQ('');
    setCategory('全部');
    setPage(1);
  };

  const chips: AdminFilterChip[] = [];
  if (q.trim()) {
    const keyword = q.trim();
    chips.push({
      key: 'q',
      label: `搜索：${keyword.length > 16 ? `${keyword.slice(0, 16)}…` : keyword}`,
      onRemove: () => handleSearchChange(''),
    });
  }
  if (category !== '全部') {
    chips.push({
      key: 'category',
      label: `分类：${category}`,
      onRemove: () => handleCategoryChange('全部'),
    });
  }

  const handleExportCsv = () => {
    exportContentsAsCSV(items);
    toast.success(`已导出本页 ${items.length} 条到 CSV`);
  };

  const handleCopyLink = async (item: ContentItem) => {
    if (!item.url) return;
    try {
      await navigator.clipboard.writeText(item.url);
      toast.success('原文链接已复制');
    } catch {
      // 剪贴板被拒绝等场景：给可感知的失败反馈，不静默吞掉
      toast.error('复制失败，请打开原文后复制地址栏链接');
    }
  };

  /* ─── 列定义 ── */

  const columns: AdminTableColumn<ContentItem>[] = [
    {
      key: 'title',
      header: '标题',
      render: (item) =>
        item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block max-w-[440px] truncate text-[13px] font-medium text-ink-900 no-underline transition hover:text-primary"
          >
            {item.title || '无标题'}
          </a>
        ) : (
          <span className="block max-w-[440px] truncate text-[13px] font-medium text-ink-900">
            {item.title || '无标题'}
          </span>
        ),
    },
    {
      key: 'source',
      header: '来源',
      width: 170,
      render: (item) => {
        const color = SOURCE_TYPE_COLOR_MAP[item.source_type] || { bg: '#F3F4F6', color: '#6B7280' };
        return (
          <div className="flex items-center gap-1.5 overflow-hidden">
            <span className="truncate text-[13px] text-ink-700">{item.source_name}</span>
            <span
              className="shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold"
              style={{ background: color.bg, color: color.color }}
            >
              {item.source_type}
            </span>
          </div>
        );
      },
    },
    {
      key: 'category',
      header: '分类',
      width: 96,
      render: (item) => (
        <span className="whitespace-nowrap rounded bg-primary-light px-2 py-1 text-[11px] font-semibold text-primary">
          {item.category}
        </span>
      ),
    },
    {
      key: 'tags',
      header: '标签',
      width: 200,
      render: (item) => (
        <div className="flex flex-wrap gap-1 overflow-hidden">
          {item.tags && item.tags.length > 0 ? (
            item.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="whitespace-nowrap rounded bg-purple-light px-2 py-0.5 text-[10px] font-medium text-purple"
              >
                {tag}
              </span>
            ))
          ) : (
            <span className="text-ink-500">-</span>
          )}
          {item.tags && item.tags.length > 3 && (
            <span className="text-[10px] text-ink-500">+{item.tags.length - 3}</span>
          )}
        </div>
      ),
    },
    {
      key: 'published_at',
      header: '发布时间',
      width: 110,
      render: (item) => <span className="whitespace-nowrap font-mono text-xs text-ink-500">{timeAgo(item.published_at)}</span>,
    },
    {
      key: 'status',
      header: '状态',
      width: 88,
      render: (item) => {
        const statusKey = item.status || 'pending';
        const statusTone = CONTENT_STATUS_TONE[statusKey] || CONTENT_STATUS_TONE.pending;
        return (
          <Badge tone={statusTone} className="rounded px-2.5 py-1 text-[11px] font-semibold">
            {CONTENT_STATUS_LABEL[statusKey] || statusKey}
          </Badge>
        );
      },
    },
    {
      key: 'actions',
      header: '操作',
      width: 92,
      sticky: 'right',
      render: (item) => <ContentRowActions item={item} onCopyLink={handleCopyLink} />,
    },
  ];

  return (
    <AdminPageShell maxWidth={1200}>
      <AdminPageHeader
        title="内容列表"
        description={<>从各信源采集到的原始内容 · 共 <b className="font-mono text-gray-600">{total}</b> 条</>}
      />

      {/* 筛选行：搜索（防抖后提交）+ 分类下拉；导出为右侧动作 */}
      <div className="space-y-2">
        <AdminFilters
          searchPlaceholder="搜索标题 / 标签 / 正文…"
          searchValue={q}
          onSearchChange={handleSearchChange}
          actions={
            !loading && items.length > 0 ? (
              <Button
                type="button"
                variant="secondary"
                onClick={handleExportCsv}
                className="!px-2.5 !py-1 text-[12px]"
              >
                <Download size={12} />
                导出本页 CSV（{items.length} 条）
              </Button>
            ) : undefined
          }
        >
          <select
            value={category}
            onChange={(e) => handleCategoryChange(e.target.value)}
            aria-label="按分类筛选"
            className="h-9 rounded-xs border border-ink-200 bg-white px-2 text-[13px] text-ink-900 focus:border-admin-accent focus:outline-none"
          >
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {cat === '全部' ? '全部分类' : cat}
              </option>
            ))}
          </select>
        </AdminFilters>

        {/* 已选条件 chips：单个移除 / 清空全部（无 chips 时整行不渲染） */}
        <AdminFilterChips chips={chips} onClearAll={clearAllFilters} />
      </div>

      {/* 三态（加载/错误/空）由 AdminTable 内建，页面层不自造 */}
      <AdminTable
        columns={columns}
        rows={items}
        rowKey={(item) => item.id}
        loading={loading}
        error={error}
        onRetry={() => void refetch()}
        empty={
          <AdminEmptyState
            compact
            icon={Newspaper}
            title={hasActiveFilters ? '没有匹配的内容' : '内容池为空'}
            description={hasActiveFilters ? '试试更换关键词或切换分类' : '内容池为空，请检查信源采集状态'}
            action={
              hasActiveFilters ? (
                <Button type="button" variant="secondary" onClick={clearAllFilters}>
                  清空筛选
                </Button>
              ) : undefined
            }
          />
        }
        minWidth={980}
      />

      {/* 分页：后端 /contents 支持 page_size（1–200），条数选择器随之落地 */}
      {!loading && total > 0 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onPage={setPage}
          pageSize={pageSize}
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          onPageSizeChange={handlePageSizeChange}
          summary={
            <>
              第 <b className="font-mono">{page}</b> / <b className="font-mono">{totalPages}</b> 页，共 {total} 条
            </>
          }
        />
      )}
    </AdminPageShell>
  );
}

/* ─── 行操作 ───
 * 本页只有两个高频动作（打开原文 / 复制链接），≤2 全部直接可见，
 * 无需「···」折叠菜单；两者皆非破坏性，也没有需要二次确认的入口。 */

function ContentRowActions({
  item,
  onCopyLink,
}: {
  item: ContentItem;
  onCopyLink: (item: ContentItem) => void;
}) {
  if (!item.url) {
    return <span className="text-ink-500">—</span>;
  }
  return (
    <div className="flex items-center justify-center gap-1">
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`打开原文：${item.title || '无标题'}`}
        title="打开原文"
        className="flex h-7 w-7 items-center justify-center rounded-xs text-ink-500 transition hover:bg-ink-100 hover:text-ink-900"
      >
        <ExternalLink size={14} strokeWidth={2} />
      </a>
      <button
        type="button"
        onClick={() => onCopyLink(item)}
        aria-label={`复制链接：${item.title || '无标题'}`}
        title="复制链接"
        className="flex h-7 w-7 items-center justify-center rounded-xs text-ink-500 transition hover:bg-ink-100 hover:text-ink-900"
      >
        <Copy size={14} strokeWidth={2} />
      </button>
    </div>
  );
}
