'use client';

import React, { useState } from 'react';
import {
  BarChart3,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Flame,
  Gauge,
  Inbox,
  Layers3,
  Radar,
  SlidersHorizontal,
  Star,
  Target,
  Zap,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { viralApi } from '@/lib/api';
import { useAppContext } from '@/components/ClientLayout';
import CategoryChip from '@/components/CategoryChip';
import AnalysisPanel from '@/components/AnalysisPanel';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import type { ContentAnalysis, ContentItem } from '@/types';

const TIME_RANGES = [
  { value: 24, label: '24h' },
  { value: 48, label: '48h' },
  { value: 168, label: '7d' },
] as const;

const PAGE_SIZE = 20;
const CATEGORY_OPTIONS = ['AI', '职场', '商业', '教育', '自媒体', '科技', '生活', '产品'] as const;

type AnalysisWithMeta = ContentAnalysis & { _content_id?: number };

export default function LowFollowerViralPage() {
  const { toggleFavorite } = useAppContext();
  const [page, setPage] = useState(1);
  const [hours, setHours] = useState<number>(48);
  const [category, setCategory] = useState('');
  const [selectedAnalysis, setSelectedAnalysis] = useState<AnalysisWithMeta | null>(null);

  // hours / category 切换时回到第 1 页
  React.useEffect(() => { setPage(1); }, [hours, category]);

  type ListPayload = { items: ContentItem[]; total: number };
  const { data, loading } = useFetch<ListPayload>(
    async () => {
      const res = await viralApi.list({
        page,
        hours,
        category: category || undefined,
        page_size: PAGE_SIZE,
      });
      return { items: res.items || [], total: res.total || 0 };
    },
    [page, hours, category],
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const startItem = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const endItem = Math.min(page * PAGE_SIZE, total);
  const topItem = items[0] || null;
  const visibleContentIds = React.useMemo(() => items.map((item) => item.id), [items]);
  const contentFavoriteState = useContentFavoriteStates(visibleContentIds);
  const avgLfv = items.length ? Math.round(items.reduce((sum, item) => sum + lfvScore(item), 0) / items.length) : 0;
  const strongCount = items.filter((item) => lfvScore(item) >= 40).length;
  const lowAuthorityCount = items.filter((item) => sourceWeight(item) <= 35).length;
  const sourceCount = new Set(items.map((item) => item.source_name).filter(Boolean)).size;

  const openAnalysis = (item: ContentItem) => {
    const analysis = getAnalysis(item);
    if (analysis) setSelectedAnalysis({ ...analysis, _content_id: item.id });
  };

  return (
    <div className="fade-in min-h-full overflow-y-auto bg-page px-10 pb-12">
      <div className="sticky top-0 z-10 -mx-10 border-b border-gray-200 bg-page/95 px-10 py-[18px] backdrop-blur">
        <div className="mx-auto flex max-w-[1180px] items-center justify-between gap-[18px]">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-black text-gray-900">低粉爆文</h1>
              <Badge tone="primary" className="font-mono text-[10px]">
                BREAKOUT RADAR
              </Badge>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              发现低权威来源里的高传播样本，优先捕捉小号突破信号
            </p>
          </div>
          <div className="flex gap-1.5 rounded-sm bg-gray-100 p-1">
            {TIME_RANGES.map((range) => {
              const active = hours === range.value;
              return (
                <button
                  key={range.value}
                  type="button"
                  onClick={() => setHours(range.value)}
                  className={cx(
                    'rounded-xs border-0 px-2.5 py-1.5 text-[11px] font-bold transition',
                    active ? 'bg-white font-black text-primary shadow-sm' : 'bg-transparent text-gray-500 hover:text-gray-700',
                  )}
                >
                  {range.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="mx-auto mt-6 grid max-w-[1180px] items-start gap-[18px] lg:grid-cols-[minmax(0,1fr)_260px]">
        <main className="min-w-0">
          <section className="mb-4 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard icon={Radar} label="突破样本" value={total} hint={`${startItem}-${endItem}`} tone="primary" />
            <StatCard icon={Gauge} label="平均 LFV" value={avgLfv || '-'} hint="当前页" tone="teal" />
            <StatCard icon={Zap} label="强突破" value={strongCount} hint="LFV >= 40" tone="amber" />
            <StatCard icon={Layers3} label="来源数" value={sourceCount} hint={`${lowAuthorityCount} 个低权威信号`} tone="purple" />
          </section>

          {topItem && !loading && (
            <HeroBreakout item={topItem} isFav={contentFavoriteState.isFavorited(topItem.id)} onFav={async (id) => {
              await toggleFavorite(id);
              contentFavoriteState.refresh();
            }} onOpen={openAnalysis} />
          )}

          {loading ? (
            <LoadingState label="扫描突破样本…" minHeight="200px" />
          ) : items.length === 0 ? (
            <EmptyState icon={Inbox} title="暂无低粉爆文数据" desc="可以放宽时间窗口或分类范围。" />
          ) : (
            <div className="flex flex-col gap-2.5">
              {items.map((item, index) => (
                <BreakoutCard
                  key={item.id}
                  item={item}
                  rank={(page - 1) * PAGE_SIZE + index + 1}
                  isFav={contentFavoriteState.isFavorited(item.id)}
                  onFav={async (id) => {
                    await toggleFavorite(id);
                    contentFavoriteState.refresh();
                  }}
                  onOpen={openAnalysis}
                />
              ))}
            </div>
          )}

          {!loading && totalPages > 1 && (
            <Pagination page={page} totalPages={totalPages} onPage={setPage} />
          )}
        </main>

        <aside className="sticky top-[88px] flex flex-col gap-3.5">
          <FilterPanel category={category} setCategory={setCategory} />
          <SignalPanel items={items} />
        </aside>
      </div>

      {selectedAnalysis && (
        <AnalysisPanel analysis={selectedAnalysis} onClose={() => setSelectedAnalysis(null)} />
      )}
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: number | string;
  hint: string;
  tone: 'primary' | 'teal' | 'amber' | 'purple';
}) {
  const toneClass = {
    primary: 'text-primary',
    teal: 'text-teal',
    amber: 'text-amber',
    purple: 'text-purple',
  }[tone];
  return (
    <Panel className="min-w-0 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Icon size={15} className={toneClass} strokeWidth={2.2} />
        <span className="text-xs font-extrabold text-gray-500">{label}</span>
      </div>
      <div className="font-mono text-[28px] font-black leading-none text-gray-900">{value}</div>
      <div className="mt-1.5 text-[11px] text-gray-400">{hint}</div>
    </Panel>
  );
}

function HeroBreakout({
  item,
  isFav,
  onFav,
  onOpen,
}: {
  item: ContentItem;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (item: ContentItem) => void;
}) {
  const analysis = getAnalysis(item);
  const score = lfvScore(item);
  const obscure = obscureFactor(item);
  const authority = sourceWeight(item);
  const reason = analysis?.recommendation || analysis?.recommended_reason || item.summary || '';

  return (
    <Panel className="relative mb-4 overflow-hidden p-6 shadow-lg">
      <div className="absolute bottom-0 left-0 top-0 w-1 bg-primary" />
      <div className="relative grid gap-5 sm:grid-cols-[minmax(0,1fr)_132px]">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge tone="primary" className="gap-1 text-[11px]">
              <Flame size={13} /> 最强突破
            </Badge>
            <span className="text-[11px] text-gray-500">{item.source_name}</span>
            <SignalPill label={`隐蔽 x${obscure.toFixed(2)}`} />
            <SignalPill label={`源权威 ${Math.round(authority)}`} />
          </div>
          <h2 className="mb-2.5 text-[23px] font-black leading-[1.38] text-gray-900">
            {item.title}
          </h2>
          {reason && <p className="max-w-[680px] text-[13px] leading-7 text-gray-600">{reason}</p>}
          <ActionRow item={item} isFav={isFav} onFav={onFav} onOpen={onOpen} />
        </div>
        <div className="flex self-stretch flex-col items-center justify-center rounded-sm border border-primary-border bg-primary-light">
          <div className="mb-1.5 text-[11px] text-gray-500">LFV</div>
          <div className="font-mono text-[42px] font-black leading-none text-primary">
            {score.toFixed(1)}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function BreakoutCard({
  item,
  rank,
  isFav,
  onFav,
  onOpen,
}: {
  item: ContentItem;
  rank: number;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (item: ContentItem) => void;
}) {
  const analysis = getAnalysis(item);
  const score = lfvScore(item);
  const authority = sourceWeight(item);
  const obscure = obscureFactor(item);
  const reason = analysis?.recommendation || analysis?.recommended_reason || item.summary || '';
  const rankTone = score >= 40 ? 'bg-primary-light text-primary' : score >= 25 ? 'bg-amber-light text-amber' : 'bg-gray-100 text-gray-500';
  const scoreTone = score >= 40 ? 'text-primary' : score >= 25 ? 'text-amber' : 'text-teal';

  return (
    <article
      onClick={() => analysis && onOpen(item)}
      className={cx(
        'grid grid-cols-[44px_minmax(0,1fr)_76px] items-start gap-3 rounded-lg border border-gray-200 bg-white px-[18px] py-4 transition hover:border-primary-border hover:shadow-lg',
        analysis ? 'cursor-pointer' : 'cursor-default',
      )}
    >
      <div className={cx('flex h-[34px] w-[34px] items-center justify-center rounded-sm font-mono text-xs font-black', rankTone)}>
        {rank}
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <span className="text-xs font-extrabold text-gray-500">{item.source_name}</span>
          {item.category && <SignalPill label={item.category} />}
          <SignalPill label={`源权威 ${Math.round(authority)}`} />
          <SignalPill label={`隐蔽 x${obscure.toFixed(2)}`} tone={authority <= 35 ? 'good' : 'muted'} />
        </div>
        <h3 className={cx('text-[15px] font-black leading-[1.45] text-gray-900', reason && 'mb-2')}>
          {item.title}
        </h3>
        {reason && (
          <p className="mb-2.5 text-xs leading-6 text-gray-500">
            {reason}
          </p>
        )}
        <ActionRow item={item} isFav={isFav} onFav={onFav} onOpen={onOpen} />
      </div>
      <div className="text-right">
        <div className={cx('font-mono text-2xl font-black leading-none', scoreTone)}>
          {score.toFixed(1)}
        </div>
        <div className="mt-1 text-[10px] text-gray-400">LFV</div>
      </div>
    </article>
  );
}

function ActionRow({
  item,
  isFav,
  onFav,
  onOpen,
  dark = false,
}: {
  item: ContentItem;
  isFav: boolean;
  onFav: (id: number) => void;
  onOpen: (item: ContentItem) => void;
  dark?: boolean;
}) {
  const analysis = getAnalysis(item);
  return (
    <Toolbar className={cx('gap-2', dark && 'mt-4')}>
      {analysis && (
        <Button
          type="button"
          variant="secondary"
          className="min-h-0 px-2.5 py-1 text-[11px]"
          onClick={(event) => {
            event.stopPropagation();
            onOpen(item);
          }}
        >
          <Target size={13} /> 分析
        </Button>
      )}
      {item.url && (
        <a
          href={`/contents/${item.id}/reader`}
          onClick={(event) => event.stopPropagation()}
          className="inline-flex items-center gap-1.5 rounded-xs border border-primary-border bg-primary-light px-2.5 py-1 text-[11px] font-extrabold text-primary no-underline transition hover:border-primary"
        >
          <BookOpen size={13} /> 阅读
        </a>
      )}
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => event.stopPropagation()}
          className="inline-flex items-center gap-1.5 rounded-xs border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-extrabold text-gray-600 no-underline transition hover:border-primary-border hover:text-primary"
        >
          原文 <ExternalLink size={13} />
        </a>
      )}
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onFav(item.id);
        }}
        className={cx(
          'inline-flex items-center gap-1.5 rounded-xs border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-extrabold transition hover:border-primary-border',
          isFav ? 'text-primary' : 'text-gray-400 hover:text-primary',
        )}
      >
        <Star size={13} fill={isFav ? '#FF6B35' : 'none'} /> 收藏
      </button>
    </Toolbar>
  );
}

function FilterPanel({
  category,
  setCategory,
}: {
  category: string;
  setCategory: (value: string) => void;
}) {
  return (
    <Panel className="p-4">
      <PanelTitle icon={SlidersHorizontal} title="侦测范围" />
      <div className="flex flex-wrap gap-1.5">
        <CategoryChip name="全部" active={!category} onClick={() => setCategory('')} />
        {CATEGORY_OPTIONS.map((item) => (
          <CategoryChip key={item} name={item} active={category === item} onClick={() => setCategory(category === item ? '' : item)} />
        ))}
      </div>
    </Panel>
  );
}

function SignalPanel({ items }: { items: ContentItem[] }) {
  const rows = [
    { label: '强突破', value: items.filter((item) => lfvScore(item) >= 40).length, className: 'bg-primary' },
    { label: '低权威源', value: items.filter((item) => sourceWeight(item) <= 35).length, className: 'bg-teal' },
    { label: '隐蔽高', value: items.filter((item) => obscureFactor(item) >= 0.6).length, className: 'bg-amber' },
  ];

  return (
    <Panel className="p-4">
      <PanelTitle icon={BarChart3} title="突破信号" />
      <div className="flex flex-col gap-2.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2">
            <span className={cx('h-2 w-2 shrink-0 rounded-full', row.className)} />
            <span className="flex-1 text-xs text-gray-600">{row.label}</span>
            <span className="font-mono text-[13px] font-black text-gray-900">{row.value}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-gray-100 pt-3 text-xs leading-7 text-gray-500">
        LFV 越高，说明内容在低权威来源中越可能完成了异常传播。
      </div>
    </Panel>
  );
}

function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (updater: number | ((page: number) => number)) => void;
}) {
  const pageNumbers = Array.from({ length: Math.min(5, totalPages) }, (_, index) => {
    if (totalPages <= 5) return index + 1;
    if (page <= 3) return index + 1;
    if (page >= totalPages - 2) return totalPages - 4 + index;
    return page - 2 + index;
  });

  return (
    <div className="mt-6 flex items-center justify-between gap-3">
      <PageButton disabled={page === 1} onClick={() => onPage((current) => Math.max(1, current - 1))}>
        <ChevronLeft size={14} /> 上一页
      </PageButton>
      <div className="flex gap-1">
        {pageNumbers.map((pageNumber) => (
          <button
            key={pageNumber}
            type="button"
            onClick={() => onPage(pageNumber)}
            className={cx(
              'h-8 w-8 rounded-sm border text-[13px] transition',
              page === pageNumber
                ? 'border-primary-border bg-primary font-black text-white'
                : 'border-gray-200 bg-white font-bold text-gray-600 hover:border-primary-border hover:text-primary',
            )}
          >
            {pageNumber}
          </button>
        ))}
      </div>
      <PageButton disabled={page === totalPages} onClick={() => onPage((current) => Math.min(totalPages, current + 1))}>
        下一页 <ChevronRight size={14} />
      </PageButton>
    </div>
  );
}

function PageButton({
  disabled,
  onClick,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled}
      variant="secondary"
      className={cx('px-3.5 py-2 text-[13px]', disabled && 'cursor-not-allowed bg-gray-50 text-gray-300')}
    >
      {children}
    </Button>
  );
}

function PanelTitle({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <Icon size={15} className="text-primary" strokeWidth={2.2} />
      <span className="text-sm font-black text-gray-900">{title}</span>
    </div>
  );
}

function SignalPill({
  label,
  tone = 'muted',
  dark = false,
}: {
  label: string;
  tone?: 'good' | 'muted';
  dark?: boolean;
}) {
  return (
    <span
      className={cx(
        'whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-extrabold',
        dark
          ? 'border-white/10 bg-white/10 text-gray-300'
          : tone === 'good'
            ? 'border-teal-border bg-teal-light text-teal'
            : 'border-gray-200 bg-gray-100 text-gray-500',
      )}
    >
      {label}
    </span>
  );
}

function getAnalysis(item: ContentItem): ContentAnalysis | undefined {
  return item.analysis || item.analyses?.[0];
}

function lfvScore(item: ContentItem): number {
  const analysis = getAnalysis(item);
  return analysis?.adjusted_curation_score ?? analysis?.curation_score ?? 0;
}

function sourceWeight(item: ContentItem): number {
  return getAnalysis(item)?.score_breakdown?.dimension_scores?.source_weight ?? 0;
}

function obscureFactor(item: ContentItem): number {
  return getAnalysis(item)?.score_breakdown?.dimension_scores?.obscure_factor ?? 0;
}
