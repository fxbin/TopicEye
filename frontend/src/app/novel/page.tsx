'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  Crown,
  ExternalLink,
  Filter,
  Library,
  LineChart,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  TrendingUp,
  X,
} from 'lucide-react';
import { Button, Panel, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import { useAppContext } from '@/components/ClientLayout';
import {
  favoritesApi,
  fanqieApi,
  qimaoApi,
  trendingApi,
  webnovelReportsApi,
  zhihuApi,
  type FanqieCategory,
  type FanqieBook,
  type QimaoBook,
  type WebnovelMovementItem,
  type WebnovelWeeklyReport,
  type ZhihuAlbum,
  type TrendingItem,
} from '@/lib/api';
import {
  type Platform,
  type BookItem,
  type ViewMode,
  type BookFavoriteMeta,
  PLATFORM_META,
  GROUP_LABELS,
  RANK_TYPE_LABELS,
  QIMAO_RANK_LABELS,
  ISHUGUI_RANK_LABELS,
  ISHUGUI_SHELF_TO_RANK,
  HEIYAN_SORT_STYLE,
  HEIYAN_SORT_FALLBACK,
  HEIYAN_HOME_SHELF_LABELS,
  HEIYAN_TYPE_STYLE,
  QIMAO_CHANNEL_LABELS,
  ZHIHU_SORT_LABELS,
  ZHIHU_SUBCATS,
  formatCount,
  getItemTitle,
  getItemAuthor,
  getItemAbstract,
  getItemCover,
  getItemUrl,
  getPositionChange,
  getBookStableId,
  getBookFavoriteMeta,
  chipStyle,
  formatDate,
} from './_novel-utils';


function MetricPill({ children, color = '#6B7280', bg = '#F3F4F6' }: { children: React.ReactNode; color?: string; bg?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ background: bg, color }}>
      {children}
    </span>
  );
}


function MovementBadge({ change }: { change: number }) {
  const rising = change > 0;
  return (
    <span className={cx('inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 font-mono text-[11px] font-black', rising ? 'bg-teal-light text-teal' : 'bg-red-light text-red')}>
      {rising ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
      {Math.abs(change)}
    </span>
  );
}

function MovementList({ title, items, tone }: { title: string; items: WebnovelMovementItem[]; tone: 'up' | 'down' }) {
  return (
    <Panel className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[13px] font-black text-gray-800">
          {tone === 'up' ? <ArrowUp size={16} className="text-teal" /> : <ArrowDown size={16} className="text-red" />}
          {title}
        </div>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 font-mono text-[11px] text-gray-500">{items.length}</span>
      </div>
      <div className="flex flex-col gap-2">
        {items.length === 0 ? (
          <div className="rounded-sm border border-gray-100 bg-gray-50 p-4 text-center text-xs text-gray-400">暂无明显变化</div>
        ) : items.map((item, index) => (
          <a
            key={`${item.platform}-${item.title}-${item.rank_type}-${index}`}
            href={item.url || undefined}
            target="_blank"
            rel="noreferrer"
            className="grid grid-cols-[24px_minmax(0,1fr)_auto] items-start gap-2 rounded-sm border border-gray-100 bg-gray-50 p-3 text-left transition hover:border-primary-border hover:bg-white"
          >
            <div className="grid h-6 w-6 place-items-center rounded-xs bg-white font-mono text-[11px] font-black text-gray-500">{index + 1}</div>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-black text-gray-900">{item.title}</div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-gray-400">
                <span>{item.platform_label}</span>
                <span>{item.category}</span>
                <span>#{item.position}</span>
              </div>
            </div>
            <MovementBadge change={item.change} />
          </a>
        ))}
      </div>
    </Panel>
  );
}

function WebnovelWeeklyPanel({ report, loading, onRefresh, days, onDaysChange }: { report: WebnovelWeeklyReport | null; loading: boolean; onRefresh: () => void; days: number; onDaysChange: (d: number) => void }) {
  const maxDaily = Math.max(...(report?.daily_counts.map((item) => item.count) || [1]), 1);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-[18px]">
      {loading ? (
        <LoadingState label="正在生成网文周报" />
      ) : !report ? (
        <EmptyState icon={BookOpen} title="暂无网文周报" desc="同步网文榜单后再刷新周报。" />
      ) : (
        <div className="mx-auto flex max-w-6xl flex-col gap-4">
          {/* 时间窗切换：'按 X 天上升最快' */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-gray-500">时间窗：</span>
            {[3, 7, 14, 30].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => onDaysChange(d)}
                className={cx(
                  'rounded-sm border px-2.5 py-0.5 text-[12px] transition',
                  days === d
                    ? 'border-orange bg-orange text-white'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                )}
              >
                {d} 天
              </button>
            ))}
          </div>
          <Panel className="overflow-hidden p-0">
            <div className="border-b border-gray-100 bg-white px-5 py-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-2 flex items-center gap-2 text-xs font-black text-primary">
                    <LineChart size={16} />
                    WEBNOVEL WEEKLY
                  </div>
                  <h2 className="m-0 text-[24px] font-black text-gray-900">网文周报</h2>
                  <p className="mt-1 text-xs text-gray-500">{report.period.label} · 覆盖 {report.platforms.length} 个平台 · {report.summary.snapshot_days} 天历史快照</p>
                </div>
                <Button type="button" variant="secondary" onClick={onRefresh}>
                  <RefreshCw size={15} />
                  刷新周报
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-0 border-b border-gray-100 md:grid-cols-4">
              <SummaryMetric label="榜单样本" value={report.summary.total_items} />
              <SummaryMetric label="上升作品" value={report.summary.rising_count} tone="teal" />
              <SummaryMetric label="下跌作品" value={report.summary.falling_count} tone="red" />
              <SummaryMetric label="阅读增量" value={formatCount(report.summary.read_count_delta)} />
            </div>
            <div className="grid grid-cols-1 gap-3 p-4 lg:grid-cols-3">
              {report.platforms.map((platform) => (
                <div key={platform.platform} className="rounded-sm border border-gray-100 bg-gray-50 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-sm font-black text-gray-900">{platform.label}</div>
                    <span className="rounded-full bg-white px-2 py-0.5 font-mono text-[11px] text-gray-500">{platform.history_days}d</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <MiniMetric label="样本" value={platform.item_count} />
                    <MiniMetric label="上升" value={platform.rising_count} tone="teal" />
                    <MiniMetric label="下跌" value={platform.falling_count} tone="red" />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <MovementList title="上升最快" items={report.top_risers} tone="up" />
              <MovementList title="下跌明显" items={report.top_fallers} tone="down" />
            </div>

            <div className="flex flex-col gap-4">
              <Panel className="p-4">
                <div className="mb-3 flex items-center gap-2 text-[13px] font-black text-gray-800">
                  <LineChart size={16} className="text-primary" />
                  番茄快照覆盖
                </div>
                <div className="flex items-end gap-1.5">
                  {report.daily_counts.length === 0 ? (
                    <div className="rounded-sm border border-gray-100 bg-gray-50 p-4 text-center text-xs text-gray-400">暂无历史快照</div>
                  ) : report.daily_counts.map((item) => (
                    <div key={item.date} className="flex flex-1 flex-col items-center gap-1.5">
                      <div className="w-full rounded-t-xs bg-primary" style={{ height: `${Math.max(12, (item.count / maxDaily) * 86)}px` }} />
                      <span className="text-[10px] text-gray-400">{formatDate(item.date)}</span>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel className="p-4">
                <div className="mb-3 flex items-center gap-2 text-[13px] font-black text-gray-800">
                  <Sparkles size={16} className="text-amber" />
                  分类热度
                </div>
                <div className="flex flex-col gap-3">
                  {Object.entries(report.category_mix).map(([platform, items]) => (
                    <div key={platform}>
                      <div className="mb-1.5 text-[11px] font-black text-gray-400">{PLATFORM_META[platform as Platform]?.label || platform}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {items.slice(0, 6).map((item) => (
                          <span key={`${platform}-${item.category}`} className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] font-bold text-gray-600">
                            {item.category} · {item.count}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel className="p-4">
                <div className="mb-2 text-[13px] font-black text-gray-800">数据说明</div>
                <div className="space-y-2 text-xs leading-6 text-gray-500">
                  {report.notes.map((note, index) => (
                    <p key={index} className="m-0">{note}</p>
                  ))}
                </div>
              </Panel>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 黑岩 / 点众卡片: 取 trending item extra 里的元数据 (author/words/tags/shelf) */
function WebnovelCard({ item, platform }: { item: TrendingItem; platform: Platform }) {
  const ex = (item.extra || {}) as Record<string, unknown>;
  const author = (ex.author as string) || '';
  const words = (ex.words_str as string) || (ex.total_word_size as string) || '';
  const intro = (ex.intro as string) || '';
  const tags = Array.isArray(ex.tags)
    ? (ex.tags as string[])
    : Array.isArray(ex.tag_v3)
      ? (ex.tag_v3 as string[])
      : [];
  const shelf = (ex.shelf as string) || item.hot_value_raw || '';
  const score = ex.book_score != null ? String(ex.book_score) : '';
  const isShort = (ex.type as number) === 1 || (ex.words as number) <= 30000;
  const finished = ex.finished === true;
  const platformMeta = PLATFORM_META[platform];

  return (
    <article className="fanqie-book-card flex gap-3 rounded-sm border border-gray-200 bg-white p-3 transition hover:border-primary-border">
      <a
        href={item.url || '#'}
        target="_blank"
        rel="noopener noreferrer"
        className="relative h-[100px] w-[68px] shrink-0 overflow-hidden rounded-xs bg-gray-100"
      >
        {item.cover_url ? (
          <img src={item.cover_url} alt={item.title} className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[10px] text-gray-400">无封面</div>
        )}
      </a>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <a
            href={item.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="line-clamp-1 text-[13px] font-black leading-snug text-gray-900 no-underline"
          >
            {item.title}
          </a>
          <span className="font-mono text-[10px] text-gray-400">#{item.rank}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-gray-500">
          {author && <span>{author}</span>}
          {words && <span>· {words}</span>}
          {isShort && <span className="rounded-xs px-1 py-px font-bold" style={{ background: platformMeta.bg, color: platformMeta.color }}>短篇</span>}
          {finished && <span className="rounded-xs bg-gray-100 px-1 py-px font-bold text-gray-600">完结</span>}
          {score && <span className="text-amber">★ {score}</span>}
        </div>
        {intro && (
          <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-gray-500">{intro}</p>
        )}
        {tags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {tags.slice(0, 3).map((t, i) => (
              <span key={i} className="rounded-xs bg-gray-100 px-1 py-px text-[9px] text-gray-600">{t}</span>
            ))}
          </div>
        )}
        <div className="mt-1 flex items-center justify-between text-[10px] text-gray-400">
          <span>{shelf}</span>
          {item.url && (
            <a href={item.url} target="_blank" rel="noreferrer" title="打开原文" className="rounded-xs p-1 text-gray-400 transition hover:bg-gray-100 hover:text-primary">
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

function BookCard({
  item,
  platform,
  rankTab,
  favorite,
  favoritePending,
  onFavorite,
}: {
  item: BookItem;
  platform: Platform;
  rankTab: string;
  favorite: boolean;
  favoritePending: boolean;
  onFavorite: (item: BookItem) => void;
}) {
  const [coverFailed, setCoverFailed] = useState(false);
  const pos = item.position;
  const title = getItemTitle(item);
  const author = getItemAuthor(item);
  const cover = getItemCover(item);
  const coverSrc = cover && !coverFailed ? cover : null;
  const abstract = getItemAbstract(item);
  const itemUrl = getItemUrl(item);
  const diff = getPositionChange(item);
  const isTop = pos <= 3;
  const platformMeta = PLATFORM_META[platform];

  useEffect(() => {
    setCoverFailed(false);
  }, [cover]);

  const meta = (() => {
    if (platform === 'fanqie' && 'read_count' in item) {
      const rankInfo = RANK_TYPE_LABELS[rankTab as keyof typeof RANK_TYPE_LABELS];
      return (
        <>
          <MetricPill color={rankInfo?.color} bg={rankInfo?.bg}>{rankInfo?.label || '榜单'}</MetricPill>
          <MetricPill>{formatCount(item.read_count)}阅读</MetricPill>
          <MetricPill>{formatCount(item.word_number)}字</MetricPill>
        </>
      );
    }
    if (platform === 'qimao' && 'collect_count' in item) {
      return (
        <>
          {item.is_continue_top === 1 && <MetricPill color="#D97706" bg="#FFFBEB"><Crown size={12} />霸榜</MetricPill>}
          {item.is_over === 1 && <MetricPill color="#4B5563" bg="#F3F4F6"><CheckCircle2 size={12} />完结</MetricPill>}
          <MetricPill color="#DC2626" bg="#FEF2F2">{formatCount(item.collect_count)}收藏</MetricPill>
          <MetricPill>{item.words_num}</MetricPill>
        </>
      );
    }
    if (platform === 'zhihu' && 'price_yuan' in item) {
      const sortInfo = ZHIHU_SORT_LABELS[item.sort_type as keyof typeof ZHIHU_SORT_LABELS] || ZHIHU_SORT_LABELS.hottest;
      return (
        <>
          <MetricPill color={sortInfo.color} bg={sortInfo.bg}>{sortInfo.label}</MetricPill>
          {item.is_exclusive && <MetricPill color="#D97706" bg="#FFFBEB">独家</MetricPill>}
          {item.tag === '会员专享' && <MetricPill color="#2563EB" bg="#EFF6FF">会员</MetricPill>}
          {item.chapter_text && <MetricPill>{item.chapter_text}</MetricPill>}
          {item.price_yuan && item.price_yuan !== '免费' && <MetricPill color="#DC2626" bg="#FEF2F2">{item.price_yuan}</MetricPill>}
        </>
      );
    }
    return null;
  })();

  const categoryText = (() => {
    if ('category1_name' in item && item.category1_name) {
      return [item.category1_name, item.category2_name].filter(Boolean).join(' · ');
    }
    return '';
  })();

  return (
    <article
      className={cx(
        'fanqie-book-card grid min-w-0 gap-[var(--fanqie-card-gap,16px)] rounded-sm border bg-white p-4 shadow-sm',
        isTop ? 'border-amber-border shadow-amber-100' : 'border-gray-200',
      )}
      style={{ gridTemplateColumns: 'var(--fanqie-card-cols, 44px 82px minmax(0, 1fr))' }}
    >
      <div className="flex flex-col items-center gap-1.5">
        <div className={cx('grid h-[34px] w-[34px] place-items-center rounded-sm font-mono text-base font-black', isTop ? 'bg-amber-light text-amber' : 'bg-gray-50 text-gray-400')}>
          {pos}
        </div>
        {typeof diff === 'number' && diff !== 0 && (
          <span className={cx('inline-flex items-center gap-0.5 font-mono text-[11px] font-extrabold', diff > 0 ? 'text-teal' : 'text-red')}>
            {diff > 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
            {Math.abs(diff)}
          </span>
        )}
      </div>

      {coverSrc ? (
        // eslint-disable-next-line @next/next/no-img-element -- Covers come from multiple external book platforms.
        <img
          src={coverSrc}
          alt={title}
          className="h-[var(--fanqie-cover-h,108px)] w-[var(--fanqie-cover-w,82px)] rounded-sm bg-gray-100 object-cover shadow-lg"
          onError={() => setCoverFailed(true)}
        />
      ) : (
        <div
          aria-label={`${title} 封面占位`}
          style={{
            width: 'var(--fanqie-cover-w, 82px)',
            height: 'var(--fanqie-cover-h, 108px)',
            background: `linear-gradient(160deg, ${platformMeta.bg}, #FAFAFA)`,
            color: platformMeta.color,
          }}
          className="grid place-items-center rounded-sm border border-gray-200 p-2 text-center text-[13px] font-black leading-tight shadow-md"
        >
          {title.slice(0, 2) || '书'}
        </div>
      )}

      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="m-0 truncate text-[17px] font-black leading-tight text-gray-900">{title}</h2>
            <div className="mt-1 text-xs text-gray-500">
              {author}{categoryText && <span className="text-gray-400"> · {categoryText}</span>}
            </div>
          </div>
          <button
            type="button"
            disabled={favoritePending}
            onClick={() => onFavorite(item)}
            title={favorite ? '移出收藏' : '收藏作品'}
            className={cx(
              'grid h-7 w-7 shrink-0 place-items-center rounded-xs border transition disabled:cursor-wait disabled:opacity-60',
              favorite ? 'border-amber-border bg-amber-light text-amber' : 'border-gray-200 bg-white text-gray-400 hover:border-amber-border hover:text-amber',
            )}
          >
            <Star size={15} strokeWidth={2.1} fill={favorite ? 'currentColor' : 'none'} />
          </button>
          {itemUrl && (
            <a href={itemUrl} target="_blank" rel="noreferrer" title="打开官网原文" className="rounded-xs p-1 text-gray-400 transition hover:bg-gray-100 hover:text-primary">
              <ExternalLink size={16} />
            </a>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">{meta}</div>

        {abstract && (
          <p className="line-clamp-3 m-0 text-xs leading-6 text-gray-500">
            {abstract}
          </p>
        )}

        {'latest_chapter_title' in item && item.latest_chapter_title && (
          <div className="truncate text-[11px] text-gray-400">更新 {item.latest_chapter_title}</div>
        )}
        {'last_chapter_title' in item && item.last_chapter_title && (
          <div className="truncate text-[11px] text-gray-400">更新 {item.last_chapter_title}</div>
        )}
      </div>
    </article>
  );
}

export default function FanqiePage() {
  const { currentUser, refreshCounts } = useAppContext();
  const [viewMode, setViewMode] = useState<ViewMode>('rankings');
  const [platform, setPlatform] = useState<Platform>('fanqie');
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [weeklyReport, setWeeklyReport] = useState<WebnovelWeeklyReport | null>(null);
  const [weeklyLoading, setWeeklyLoading] = useState(false);

  const [categories, setCategories] = useState<FanqieCategory[]>([]);
  const [booksMap, setBooksMap] = useState<Record<string, FanqieBook[]>>({});
  const [initLoading, setInitLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [rankTab, setRankTab] = useState<'new' | 'reading'>('reading');
  const [activeCat, setActiveCat] = useState('');
  const [groupTab, setGroupTab] = useState<'male' | 'female'>('male');

  const [qimaoBooks, setQimaoBooks] = useState<QimaoBook[]>([]);
  const [qimaoLoading, setQimaoLoading] = useState(false);
  const [qimaoSyncing, setQimaoSyncing] = useState(false);
  const [qimaoChannel, setQimaoChannel] = useState<'boy' | 'girl'>('boy');
  const [qimaoRank, setQimaoRank] = useState<keyof typeof QIMAO_RANK_LABELS>('hot');

  const [zhihuAlbums, setZhihuAlbums] = useState<ZhihuAlbum[]>([]);
  const [zhihuLoading, setZhihuLoading] = useState(false);
  const [zhihuSyncing, setZhihuSyncing] = useState(false);
  const [zhihuSort, setZhihuSort] = useState<keyof typeof ZHIHU_SORT_LABELS>('hottest');
  const [zhihuSubcat, setZhihuSubcat] = useState('');
  const [bookFavoriteKeys, setBookFavoriteKeys] = useState<Set<string>>(new Set());
  const [bookFavoriteIds, setBookFavoriteIds] = useState<Map<string, number>>(new Map());
  const [bookFavoritePendingKeys, setBookFavoritePendingKeys] = useState<Set<string>>(new Set());

  // heiyan / ishugui: 数据来源是 trending scrapers, 用 trendingApi.list 拉
  const [heiyanBooks, setHeiyanBooks] = useState<TrendingItem[]>([]);
  const [heiyanLoading, setHeiyanLoading] = useState(false);
  const [heiyanSyncing, setHeiyanSyncing] = useState(false);
  const [ishuguiBooks, setIshuguiBooks] = useState<TrendingItem[]>([]);
  const [ishuguiLoading, setIshuguiLoading] = useState(false);
  const [ishuguiSyncing, setIshuguiSyncing] = useState(false);
  // 同步重入保护: 避免 React state 异步刷新窗口内的快速双击触发并发 sync
  const syncInFlightRef = useRef(false);

  // 点众过滤: 男频/女频 × 6 榜单
  const [ishuguiGender, setIshuguiGender] = useState<'male' | 'female'>('male');
  const [ishuguiRankFilter, setIshuguiRankFilter] = useState<string>('');  // 空=全部

  // 黑岩过滤: 来源 (推荐 vs 书库全量) + sortName 分类 + tags
  const [heiyanShelfFilter, setHeiyanShelfFilter] = useState<'home' | 'search_all'>('home');
  const [heiyanSortFilter, setHeiyanSortFilter] = useState<string>('');  // sortName, ''=全部
  const [heiyanTagFilter, setHeiyanTagFilter] = useState<string>('');    // tag, ''=全部
  // 标签面板默认折叠 (15 个 tag 视觉噪音大, 按需展开)
  const [heiyanTagsExpanded, setHeiyanTagsExpanded] = useState(false);

  // 切到「推荐」时, sortName 字段不存在, 自动清空 (避免 UI 残留显示已选)
  useEffect(() => {
    if (heiyanShelfFilter === 'home' && heiyanSortFilter !== '') {
      setHeiyanSortFilter('');
    }
  }, [heiyanShelfFilter, heiyanSortFilter]);

  // 黑岩 chip 面板数据: 从当前 heiyanBooks 动态聚合, 不再硬编码
  // 推荐 (home) 没有 sortName 字段 → availableSortNames 为空
  // 标签在两个 shelf 上都从数据中取 top 15 (不重叠: 当前 shelf 看不到另一 shelf 的 tags)
  const heiyanAvailableSorts = useMemo(() => {
    if (heiyanShelfFilter !== 'search_all') return [] as Array<{ key: string; count: number }>;
    const counter: Record<string, number> = {};
    for (const item of heiyanBooks) {
      const ex = (item.extra || {}) as Record<string, unknown>;
      if (ex.shelf !== '书库全量') continue;
      const sn = ((ex.sortName as string) || '').trim();
      if (!sn) continue;
      counter[sn] = (counter[sn] || 0) + 1;
    }
    return Object.entries(counter)
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, count }));
  }, [heiyanBooks, heiyanShelfFilter]);

  const heiyanAvailableTags = useMemo(() => {
    const target = heiyanShelfFilter === 'search_all' ? '书库全量' : null;  // null=除书库全量外
    const counter: Record<string, number> = {};
    for (const item of heiyanBooks) {
      const ex = (item.extra || {}) as Record<string, unknown>;
      const isSearchAll = ex.shelf === '书库全量';
      if (target === '书库全量' && !isSearchAll) continue;
      if (target === null && isSearchAll) continue;
      const tags = Array.isArray(ex.tags) ? (ex.tags as string[]) : [];
      for (const t of tags) {
        if (t) counter[t] = (counter[t] || 0) + 1;
      }
    }
    return Object.entries(counter)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15)
      .map(([key, count]) => ({ key, count }));
  }, [heiyanBooks, heiyanShelfFilter]);

  const [weeklyDays, setWeeklyDays] = useState(7);
  const fetchWeeklyReport = useCallback(async (days: number = 7) => {
    setWeeklyLoading(true);
    setError(null);
    try {
      setWeeklyReport(await webnovelReportsApi.weekly(days));
    } catch (err) {
      setError(err instanceof Error ? err.message : '网文周报加载失败');
    } finally {
      setWeeklyLoading(false);
    }
  }, []);

  const fetchFanqieData = useCallback(async (rt: string, isInit = false) => {
    if (isInit) setInitLoading(true); else setSwitching(true);
    setError(null);
    try {
      const cats = categories.length ? categories : await fanqieApi.categories();
      if (isInit || categories.length === 0) setCategories(cats);

      const fallbackCat = cats.find((cat) => cat.group === groupTab)?.fanqie_id || cats[0]?.fanqie_id || '';
      const catId = activeCat || fallbackCat;
      if (!activeCat && catId) setActiveCat(catId);

      if (catId) {
        const result = await fanqieApi.categoryBooks(catId, { rank_type: rt });
        setBooksMap((prev) => ({ ...prev, [`${catId}|${rt}`]: result.books }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '番茄榜单加载失败');
    } finally {
      setInitLoading(false);
      setSwitching(false);
    }
  }, [activeCat, categories, groupTab]);

  const fetchQimaoData = useCallback(async () => {
    setQimaoLoading(true);
    setError(null);
    try {
      const result = await qimaoApi.list(qimaoChannel, qimaoRank);
      setQimaoBooks(result.books);
    } catch (err) {
      setError(err instanceof Error ? err.message : '七猫榜单加载失败');
    } finally {
      setQimaoLoading(false);
    }
  }, [qimaoChannel, qimaoRank]);

  const fetchZhihuData = useCallback(async () => {
    setZhihuLoading(true);
    setError(null);
    try {
      const result = await zhihuApi.list(zhihuSort, '故事', zhihuSubcat || undefined);
      setZhihuAlbums(result.albums);
    } catch (err) {
      setError(err instanceof Error ? err.message : '知乎盐选加载失败');
    } finally {
      setZhihuLoading(false);
    }
  }, [zhihuSort, zhihuSubcat]);

  const fetchHeiyanData = useCallback(async () => {
    setHeiyanLoading(true);
    setError(null);
    try {
      const items = await trendingApi.list({ source: 'heiyan', limit: 100 });
      setHeiyanBooks(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '黑岩榜单加载失败');
    } finally {
      setHeiyanLoading(false);
    }
  }, []);

  const fetchIshuguiData = useCallback(async () => {
    setIshuguiLoading(true);
    setError(null);
    try {
      const items = await trendingApi.list({ source: 'ishugui', limit: 100 });
      setIshuguiBooks(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '点众榜单加载失败');
    } finally {
      setIshuguiLoading(false);
    }
  }, []);

  useEffect(() => {
    if (platform === 'fanqie') void fetchFanqieData(rankTab, true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (platform !== 'fanqie' || categories.length === 0) return;
    const first = categories.find((cat) => cat.group === groupTab);
    if (first && first.fanqie_id !== activeCat) {
      setActiveCat(first.fanqie_id);
      setBooksMap({});
    }
  }, [groupTab, categories]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (platform === 'fanqie') void fetchFanqieData(rankTab);
  }, [platform, rankTab, activeCat]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (platform === 'qimao') void fetchQimaoData();
  }, [platform, qimaoChannel, qimaoRank, fetchQimaoData]);

  useEffect(() => {
    if (platform === 'zhihu') void fetchZhihuData();
  }, [platform, zhihuSort, zhihuSubcat, fetchZhihuData]);

  useEffect(() => {
    if (platform === 'heiyan' && heiyanBooks.length === 0) void fetchHeiyanData();
  }, [platform, heiyanBooks.length, fetchHeiyanData]);

  useEffect(() => {
    if (platform === 'ishugui' && ishuguiBooks.length === 0) void fetchIshuguiData();
  }, [platform, ishuguiBooks.length, fetchIshuguiData]);

  useEffect(() => {
    if (viewMode === 'weekly' && !weeklyReport && !weeklyLoading) void fetchWeeklyReport();
  }, [viewMode, weeklyReport, weeklyLoading, fetchWeeklyReport]);

  const fanqieBooks = useMemo(() => booksMap[`${activeCat}|${rankTab}`] || [], [activeCat, booksMap, rankTab]);
  const currentBooks: BookItem[] = platform === 'fanqie' ? fanqieBooks : platform === 'qimao' ? qimaoBooks : zhihuAlbums;
  const loading = platform === 'fanqie' ? initLoading || switching : platform === 'qimao' ? qimaoLoading : platform === 'heiyan' ? heiyanLoading : platform === 'ishugui' ? ishuguiLoading : zhihuLoading;
  const platformMeta = PLATFORM_META[platform];
  const currentCategory = categories.find((cat) => cat.fanqie_id === activeCat);

  const filteredBooks = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return currentBooks;
    return currentBooks.filter((item) => {
      const haystack = [getItemTitle(item), getItemAuthor(item), getItemAbstract(item)].join(' ').toLowerCase();
      return haystack.includes(q);
    });
  }, [currentBooks, query]);
  const visibleBookKeysKey = useMemo(
    () => filteredBooks.map((item) => getBookFavoriteMeta(item, platform, rankTab).target_key).sort().join(','),
    [filteredBooks, platform, rankTab],
  );

  useEffect(() => {
    const visibleBookKeys = visibleBookKeysKey ? visibleBookKeysKey.split(',') : [];
    if (visibleBookKeys.length === 0) {
      setBookFavoriteKeys(new Set());
      setBookFavoriteIds(new Map());
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const result = await favoritesApi.state({ target_type: 'book', target_keys: visibleBookKeys });
        if (cancelled) return;
        const nextKeys = new Set<string>();
        const nextIds = new Map<string, number>();
        for (const item of result.items || []) {
          if (item.is_favorited) {
            nextKeys.add(item.target_key);
            if (item.favorite_id) nextIds.set(item.target_key, item.favorite_id);
          }
        }
        setBookFavoriteKeys(nextKeys);
        setBookFavoriteIds(nextIds);
      } catch {
        if (!cancelled) {
          setBookFavoriteKeys(new Set());
          setBookFavoriteIds(new Map());
        }
      }
    })();
    return () => { cancelled = true; };
  }, [visibleBookKeysKey]);

  const risingCount = currentBooks.filter((item) => (getPositionChange(item) || 0) > 0).length;
  const topItem = currentBooks[0];
  const heiyanContextLabel = heiyanShelfFilter === 'search_all'
    ? `书库全量${heiyanSortFilter ? ` · 分类=${HEIYAN_SORT_STYLE[heiyanSortFilter]?.label || heiyanSortFilter}` : ''}${heiyanTagFilter ? ` · 标签=${heiyanTagFilter}` : ''}`
    : `推荐 · 4 个榜单${heiyanTagFilter ? ` · 标签=${heiyanTagFilter}` : ''}`;
  const contextLabel = platform === 'fanqie'
    ? `${GROUP_LABELS[groupTab].label} · ${RANK_TYPE_LABELS[rankTab].label}${currentCategory ? ` · ${currentCategory.name}` : ''}`
    : platform === 'qimao'
      ? `${QIMAO_CHANNEL_LABELS[qimaoChannel].label} · ${QIMAO_RANK_LABELS[qimaoRank].label}`
      : platform === 'heiyan'
        ? heiyanContextLabel
        : platform === 'ishugui'
          ? `${ishuguiGender === 'male' ? '男频' : '女频'} · ${ishuguiRankFilter ? (ISHUGUI_RANK_LABELS[ishuguiRankFilter]?.label || '') : '全部 6 个榜单（畅销/完本/新书/热读/好评/经典）'}`
          : `故事 · ${ZHIHU_SORT_LABELS[zhihuSort].label}${zhihuSubcat ? ` · ${zhihuSubcat}` : ''}`;

  const handleSync = async () => {
    // 重入保护: ref 同步生效，绕过 React state 异步刷新窗口
    if (syncInFlightRef.current) return;
    syncInFlightRef.current = true;
    try {
      await doSync();
    } finally {
      syncInFlightRef.current = false;
    }
  };

  const doSync = async () => {
    if (platform === 'fanqie') {
      setSyncing(true);
      try {
        await fanqieApi.sync();
        await fetchFanqieData(rankTab, true);
      } catch (err) {
        setError(err instanceof Error ? err.message : '番茄同步失败');
      } finally {
        setSyncing(false);
      }
      return;
    }
    if (platform === 'qimao') {
      setQimaoSyncing(true);
      try {
        await qimaoApi.sync();
        await fetchQimaoData();
      } catch (err) {
        setError(err instanceof Error ? err.message : '七猫同步失败');
      } finally {
        setQimaoSyncing(false);
      }
      return;
    }
    if (platform === 'heiyan' || platform === 'ishugui') {
      // 网文榜已从趋势雷达定时同步下线（重源拖慢全局），
      // 小说页通过 trendingApi.sync 手动单源刷新
      const setSyncing = platform === 'heiyan' ? setHeiyanSyncing : setIshuguiSyncing;
      const refetch = platform === 'heiyan' ? fetchHeiyanData : fetchIshuguiData;
      setSyncing(true);
      try {
        await trendingApi.sync(platform);
        await refetch();
      } catch (err) {
        setError(err instanceof Error ? err.message : `${platformMeta.label}同步失败`);
      } finally {
        setSyncing(false);
      }
      return;
    }
    setZhihuSyncing(true);
    try {
      await zhihuApi.sync();
      await fetchZhihuData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '知乎同步失败');
    } finally {
      setZhihuSyncing(false);
    }
  };

  const handleToggleBookFavorite = async (item: BookItem) => {
    const meta = getBookFavoriteMeta(item, platform, rankTab);
    if (bookFavoritePendingKeys.has(meta.target_key)) return;

    const wasFavorited = bookFavoriteKeys.has(meta.target_key);
    setBookFavoritePendingKeys((prev) => new Set(prev).add(meta.target_key));
    setError(null);
    try {
      if (wasFavorited) {
        let favoriteId = bookFavoriteIds.get(meta.target_key);
        if (!favoriteId) {
          const state = await favoritesApi.state({ target_type: 'book', target_keys: [meta.target_key] });
          favoriteId = state.items.find((stateItem) => stateItem.is_favorited)?.favorite_id || undefined;
        }
        if (!favoriteId) throw new Error('收藏记录不存在，请刷新后重试');
        await favoritesApi.delete(favoriteId);
        setBookFavoriteKeys((prev) => {
          const next = new Set(prev);
          next.delete(meta.target_key);
          return next;
        });
        setBookFavoriteIds((prev) => {
          const next = new Map(prev);
          next.delete(meta.target_key);
          return next;
        });
        refreshCounts();
        return;
      }

      const favorite = await favoritesApi.create({
        target_type: 'book',
        target_key: meta.target_key,
        title: meta.title,
        url: meta.url,
        cover_url: meta.cover_url,
        source_name: meta.source_name,
        snapshot: meta.snapshot,
      });
      setBookFavoriteKeys((prev) => new Set(prev).add(meta.target_key));
      setBookFavoriteIds((prev) => new Map(prev).set(meta.target_key, favorite.id));
      refreshCounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : '收藏作品失败');
    } finally {
      setBookFavoritePendingKeys((prev) => {
        const next = new Set(prev);
        next.delete(meta.target_key);
        return next;
      });
    }
  };

  const syncBusy = syncing || qimaoSyncing || zhihuSyncing || heiyanSyncing || ishuguiSyncing;
  const canSyncRankings = currentUser?.role === 'admin';

  return (
    <div className="flex h-full flex-col overflow-hidden bg-page">
      <div className="shrink-0 border-b border-gray-200 bg-white px-7 pb-4 pt-[18px]">
        <div className="flex flex-wrap items-center gap-3.5">
          <div className="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-md" style={{ background: platformMeta.bg, color: platformMeta.color }}>
            <Library size={22} strokeWidth={2.2} />
          </div>
          <div className="min-w-[220px]">
            <h1 className="m-0 text-[22px] font-black leading-tight text-gray-900">网文雷达</h1>
            <div className="mt-1 text-xs text-gray-500">{contextLabel}</div>
          </div>

          <div className="fanqie-platform-tabs flex gap-1.5 rounded-sm border border-gray-200 bg-gray-100 p-1">
            {(Object.keys(PLATFORM_META) as Platform[]).map((key) => {
              const meta = PLATFORM_META[key];
              const active = platform === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => { setPlatform(key); setQuery(''); }}
                  className={cx('flex min-w-28 cursor-pointer flex-col items-start gap-0.5 rounded-xs border-0 px-2.5 py-2 transition', active ? 'bg-white shadow-sm' : 'bg-transparent text-gray-500 hover:bg-white/60')}
                  style={{ color: active ? meta.color : undefined }}
                >
                  <span className="text-[13px] font-black">{meta.label}</span>
                  <span className={cx('text-[10px]', active ? 'text-gray-500' : 'text-gray-400')}>{meta.subtitle}</span>
                </button>
              );
            })}
          </div>

          <div className="flex-1" />
          <div className="flex rounded-sm border border-gray-200 bg-gray-100 p-1">
            <button
              type="button"
              onClick={() => setViewMode('rankings')}
              className={cx('rounded-xs px-3 py-2 text-xs font-black transition', viewMode === 'rankings' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:bg-white/60')}
            >
              榜单
            </button>
            <button
              type="button"
              onClick={() => setViewMode('weekly')}
              className={cx('rounded-xs px-3 py-2 text-xs font-black transition', viewMode === 'weekly' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:bg-white/60')}
            >
              周报
            </button>
          </div>
          {canSyncRankings && (
            <button
              type="button"
              onClick={handleSync}
              disabled={syncBusy}
              className="inline-flex items-center gap-2 rounded-sm border-0 px-3.5 py-2 text-[13px] font-extrabold text-white transition disabled:cursor-wait disabled:bg-gray-200"
              style={{ background: syncBusy ? undefined : platformMeta.color }}
            >
              <RefreshCw size={15} className={syncBusy ? 'fanqie-spin' : undefined} />
              {syncBusy ? '同步中' : `同步${platformMeta.label}`}
            </button>
          )}
        </div>
      </div>

      {viewMode === 'weekly' ? (
        <WebnovelWeeklyPanel
          report={weeklyReport}
          loading={weeklyLoading}
          onRefresh={fetchWeeklyReport}
          days={weeklyDays}
          onDaysChange={(d) => {
            setWeeklyDays(d);
            void fetchWeeklyReport(d);
          }}
        />
      ) : (
      <div className="fanqie-layout grid min-h-0 flex-1 gap-4 p-[18px]">
        <aside className="fanqie-filter-panel flex min-h-0 flex-col gap-3 pr-0.5">
          <Panel className="p-4">
            <div className="mb-3 flex items-center gap-2">
              <Filter size={16} style={{ color: platformMeta.color }} />
              <div className="text-[13px] font-black text-gray-800">筛选控制台</div>
            </div>

            {platform === 'fanqie' && (
              <div className="flex flex-col gap-3.5">
                <FilterGroup title="频道">
                  {(Object.entries(GROUP_LABELS) as Array<[keyof typeof GROUP_LABELS, typeof GROUP_LABELS[keyof typeof GROUP_LABELS]]>).map(([key, value]) => (
                    <FilterChip key={key} active={groupTab === key} color={value.color} onClick={() => setGroupTab(key)}>{value.label}</FilterChip>
                  ))}
                </FilterGroup>
                <FilterGroup title="榜单">
                  {(Object.entries(RANK_TYPE_LABELS) as Array<[keyof typeof RANK_TYPE_LABELS, typeof RANK_TYPE_LABELS[keyof typeof RANK_TYPE_LABELS]]>).map(([key, value]) => (
                    <FilterChip key={key} active={rankTab === key} color={value.color} onClick={() => setRankTab(key)}>{value.label}</FilterChip>
                  ))}
                </FilterGroup>
                <FilterGroup title={`分类 · ${categories.filter((cat) => cat.group === groupTab).length}`}>
                  <div className="grid max-h-80 w-full grid-cols-2 gap-1.5 overflow-y-auto pr-1">
                    {categories.filter((cat) => cat.group === groupTab).map((cat) => (
                      <FilterChip
                        key={cat.fanqie_id}
                        title={cat.name}
                        active={activeCat === cat.fanqie_id}
                        color="#111827"
                        onClick={() => setActiveCat(cat.fanqie_id)}
                        className="min-h-8 w-full justify-center overflow-hidden px-2.5 py-2 text-center"
                      >
                        <span className="truncate">{cat.name}</span>
                      </FilterChip>
                    ))}
                  </div>
                </FilterGroup>
              </div>
            )}

            {platform === 'qimao' && (
              <div className="flex flex-col gap-3.5">
                <FilterGroup title="频道">
                  {(Object.entries(QIMAO_CHANNEL_LABELS) as Array<[keyof typeof QIMAO_CHANNEL_LABELS, typeof QIMAO_CHANNEL_LABELS[keyof typeof QIMAO_CHANNEL_LABELS]]>).map(([key, value]) => (
                    <FilterChip key={key} active={qimaoChannel === key} color={value.color} onClick={() => setQimaoChannel(key)}>{value.label}</FilterChip>
                  ))}
                </FilterGroup>
                <FilterGroup title="榜单">
                  {(Object.entries(QIMAO_RANK_LABELS) as Array<[keyof typeof QIMAO_RANK_LABELS, typeof QIMAO_RANK_LABELS[keyof typeof QIMAO_RANK_LABELS]]>).map(([key, value]) => (
                    <FilterChip key={key} active={qimaoRank === key} color={value.color} onClick={() => setQimaoRank(key)}>{value.label}</FilterChip>
                  ))}
                </FilterGroup>
              </div>
            )}

            {platform === 'zhihu' && (
              <div className="flex flex-col gap-3.5">
                <FilterGroup title="排序">
                  {(Object.entries(ZHIHU_SORT_LABELS) as Array<[keyof typeof ZHIHU_SORT_LABELS, typeof ZHIHU_SORT_LABELS[keyof typeof ZHIHU_SORT_LABELS]]>).map(([key, value]) => (
                    <FilterChip key={key} active={zhihuSort === key} color={value.color} onClick={() => setZhihuSort(key)}>{value.label}</FilterChip>
                  ))}
                </FilterGroup>
                <FilterGroup title="故事分类">
                  <div className="grid w-full grid-cols-2 gap-1.5">
                    {ZHIHU_SUBCATS.map((cat) => (
                      <FilterChip key={cat.key} active={zhihuSubcat === cat.key} color="#0066F5" onClick={() => setZhihuSubcat(cat.key)} className="min-w-0 justify-center">{cat.label}</FilterChip>
                    ))}
                  </div>
                </FilterGroup>
              </div>
            )}

            {platform === 'heiyan' && (
              <div className="flex flex-col gap-3.5">
                <FilterGroup title="来源">
                  <FilterChip active={heiyanShelfFilter === 'home'} color="#A855F7" onClick={() => setHeiyanShelfFilter('home')}>推荐</FilterChip>
                  <FilterChip active={heiyanShelfFilter === 'search_all'} color="#7C3AED" onClick={() => setHeiyanShelfFilter('search_all')}>书库全量</FilterChip>
                </FilterGroup>
                {heiyanShelfFilter === 'search_all' && heiyanAvailableSorts.length > 0 && (
                  <FilterGroup title={`分类 (${heiyanAvailableSorts.length})`}>
                    <div className="grid w-full grid-cols-2 gap-1.5">
                      <FilterChip
                        active={heiyanSortFilter === ''}
                        color="#4B5563"
                        onClick={() => setHeiyanSortFilter('')}
                        className="justify-center"
                      >
                        全部
                      </FilterChip>
                      {heiyanAvailableSorts.map(({ key, count }) => {
                        const style = HEIYAN_SORT_STYLE[key] || HEIYAN_SORT_FALLBACK;
                        return (
                          <FilterChip
                            key={key}
                            active={heiyanSortFilter === key}
                            color={style.color}
                            onClick={() => setHeiyanSortFilter(key)}
                            className="justify-center"
                          >
                            {style.label} ({count})
                          </FilterChip>
                        );
                      })}
                    </div>
                  </FilterGroup>
                )}
                {heiyanAvailableTags.length > 0 && (
                  <div>
                    <button
                      type="button"
                      onClick={() => setHeiyanTagsExpanded(v => !v)}
                      className="mb-2 flex w-full items-center justify-between text-[11px] font-extrabold text-gray-500 hover:text-gray-700"
                    >
                      <span>标签{heiyanTagFilter ? ` · ${heiyanTagFilter}` : ` (${heiyanAvailableTags.length})`}</span>
                      <span className="text-[10px] text-gray-400">{(heiyanTagsExpanded || heiyanTagFilter) ? '收起 ▲' : '展开 ▼'}</span>
                    </button>
                    {(heiyanTagsExpanded || heiyanTagFilter) && (
                      <div className="flex w-full flex-wrap gap-1.5">
                        <FilterChip active={heiyanTagFilter === ''} color="#4B5563" onClick={() => setHeiyanTagFilter('')}>全部</FilterChip>
                        {heiyanAvailableTags.map(({ key, count }) => (
                          <FilterChip
                            key={key}
                            active={heiyanTagFilter === key}
                            color="#A855F7"
                            onClick={() => setHeiyanTagFilter(key)}
                          >
                            {key} ({count})
                          </FilterChip>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {platform === 'ishugui' && (
              <div className="flex flex-col gap-3.5">
                <FilterGroup title="频道">
                  {(Object.entries(GROUP_LABELS) as Array<[keyof typeof GROUP_LABELS, typeof GROUP_LABELS[keyof typeof GROUP_LABELS]]>).map(([key, value]) => (
                    <FilterChip key={key} active={ishuguiGender === key} color={value.color} onClick={() => setIshuguiGender(key)}>{value.label}</FilterChip>
                  ))}
                </FilterGroup>
                <FilterGroup title="榜单">
                  <div className="grid w-full grid-cols-2 gap-1.5">
                    <FilterChip active={ishuguiRankFilter === ''} color="#0EA5E9" onClick={() => setIshuguiRankFilter('')} className="justify-center">全部</FilterChip>
                    {(Object.entries(ISHUGUI_RANK_LABELS) as Array<[string, typeof ISHUGUI_RANK_LABELS[string]]>).map(([key, value]) => (
                      <FilterChip
                        key={key}
                        active={ishuguiRankFilter === key}
                        color={value.color}
                        onClick={() => setIshuguiRankFilter(key)}
                        className="justify-center"
                      >
                        {value.label}
                      </FilterChip>
                    ))}
                  </div>
                </FilterGroup>
              </div>
            )}
          </Panel>

          <Panel className="p-4">
            <div className="mb-3 flex items-center gap-2 text-[13px] font-black text-gray-800">
              <Sparkles size={16} style={{ color: platformMeta.color }} />
              榜单摘要
            </div>
            <div className="grid grid-cols-2 gap-2">
              <SummaryTile label="当前条目" value={currentBooks.length} />
              <SummaryTile label="上升作品" value={risingCount} />
            </div>
            {topItem && (
              <div className="mt-3 rounded-sm p-3" style={{ background: platformMeta.bg, color: platformMeta.color }}>
                <div className="mb-1 flex items-center gap-1.5 text-[11px] font-black">
                  <Crown size={14} />
                  榜首
                </div>
                <div className="text-[13px] font-black leading-tight text-gray-900">{getItemTitle(topItem)}</div>
                <div className="mt-1 text-[11px] text-gray-600">{getItemAuthor(topItem)}</div>
              </div>
            )}
          </Panel>
        </aside>

        <main className="fanqie-main-panel flex min-h-0 flex-col gap-3">
          <Panel className="flex flex-wrap items-center gap-3 p-3.5">
            <div className="min-w-[220px] flex-1">
              <div className="flex items-center gap-2 text-xs font-black" style={{ color: platformMeta.color }}>
                <TrendingUp size={15} />
                {platformMeta.label}
              </div>
              <div className="mt-1 text-lg font-black text-gray-900">{contextLabel}</div>
              <div className="mt-1 text-xs text-gray-400">
                {query.trim() ? `筛出 ${filteredBooks.length} / ${currentBooks.length} 条` : `${currentBooks.length} 条榜单记录`}
              </div>
            </div>
            <div className="relative w-[280px] max-w-full">
              <Search size={15} className="absolute left-3 top-2.5 text-gray-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索书名、作者、简介"
                className="w-full rounded-sm border border-gray-200 py-2 pl-8 pr-9 text-[13px] text-gray-800 outline-none transition focus:border-primary"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  title="清空搜索"
                  className="absolute right-2 top-1.5 grid h-[26px] w-[26px] cursor-pointer place-items-center rounded-xs border-0 bg-gray-100 text-gray-500"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </Panel>

          {error && (
            <div className="rounded-sm border border-red-light bg-red-light px-3 py-2.5 text-[13px] text-red">{error}</div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto pr-0.5">
            {(() => {
              const isWebnovel = platform === 'heiyan' || platform === 'ishugui';
              const sourceBooks: TrendingItem[] = isWebnovel
                ? (platform === 'heiyan' ? heiyanBooks : ishuguiBooks)
                : (filteredBooks as unknown as TrendingItem[]);
              const matchesQuery = (item: TrendingItem) => {
                const q = query.trim().toLowerCase();
                if (!q) return true;
                const ex = (item.extra || {}) as Record<string, unknown>;
                const hay = [item.title, ex.author, ex.intro,
                  ...(Array.isArray(ex.tags) ? (ex.tags as string[]) : []),
                  ...(Array.isArray(ex.tag_v3) ? (ex.tag_v3 as string[]) : []),
                ].join(' ').toLowerCase();
                return hay.includes(q);
              };
              const filteredWebnovel = isWebnovel
                ? sourceBooks.filter(matchesQuery)
                : (filteredBooks as unknown as TrendingItem[]);

              if (loading) {
                return <LoadingState label="正在拉取榜单" />;
              }
              if (filteredWebnovel.length === 0) {
                return query.trim()
                  ? <EmptyState icon={BookOpen} title="没有匹配的作品" desc="换一个书名、作者或简介关键词试试。" />
                  : <EmptyState icon={BookOpen} title="暂无榜单数据" desc="可以先同步当前平台，或切换榜单筛选。" />;
              }
              if (isWebnovel) {
                // ishugui: 按 gender × rank 分组 (男频 6 块 + 女频 6 块)
                // heiyan: 按 shelf 分组 (4 个公开榜单)
                if (platform === 'ishugui') {
                  // 先按 gender 过滤, 再按 shelf 分组
                  const genderLabel = ishuguiGender === 'male' ? '男频' : '女频';
                  const rankFilterActive = ishuguiRankFilter !== '';
                  const books = (filteredWebnovel as TrendingItem[]).filter((item) => {
                    const ex = (item.extra || {}) as Record<string, unknown>;
                    if (ex.gender !== genderLabel) return false;
                    if (rankFilterActive) {
                      const shelf = (ex.shelf as string) || '';
                      const expectedShelf = ishuguiGender === 'male'
                        ? `男生小说${ISHUGUI_RANK_LABELS[ishuguiRankFilter]?.label || ''}`
                        : `女生小说${ISHUGUI_RANK_LABELS[ishuguiRankFilter]?.label || ''}`;
                      if (shelf !== expectedShelf) return false;
                    }
                    return true;
                  });

                  // 按 shelf 分组
                  const groups = new Map<string, TrendingItem[]>();
                  books.forEach((item) => {
                    const shelf = (item.extra?.shelf as string) || '其他';
                    if (!groups.has(shelf)) groups.set(shelf, []);
                    groups.get(shelf)!.push(item);
                  });

                  if (books.length === 0) {
                    return <EmptyState icon={BookOpen} title="该榜单暂无作品" />;
                  }

                  return (
                    <div className="flex flex-col gap-4">
                      {Array.from(groups.entries()).map(([shelf, items]) => {
                        const rankKey = ISHUGUI_SHELF_TO_RANK[shelf] || '';
                        const rankMeta = ISHUGUI_RANK_LABELS[rankKey];
                        return (
                          <div key={shelf}>
                            <div className="mb-2 flex items-center gap-2 px-1">
                              <span
                                className="rounded-xs px-2 py-0.5 text-[12px] font-black"
                                style={rankMeta ? { background: rankMeta.bg, color: rankMeta.color } : { background: '#F3F4F6', color: '#4B5563' }}
                              >
                                {rankMeta?.label || shelf}
                              </span>
                              <span className="text-[11px] text-gray-400">{items.length} 本</span>
                            </div>
                            <div className="fanqie-book-grid grid gap-2.5">
                              {items.map((item) => (
                                <WebnovelCard
                                  key={item.id}
                                  item={item}
                                  platform={platform}
                                />
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                }
                // heiyan: 来源 (推荐 vs 书库全量) + 分类 (sortName) + 标签 (tag) 三组过滤
                // 推荐: 维持 4 个 home shelf 分组
                // 书库全量: 按 sortName 分组
                if (platform === 'heiyan') {
                  const shelfFilterActive = heiyanShelfFilter === 'home';
                  const books = (filteredWebnovel as TrendingItem[]).filter((item) => {
                    const ex = (item.extra || {}) as Record<string, unknown>;
                    const isSearchAll = ex.shelf === '书库全量';
                    if (shelfFilterActive && isSearchAll) return false;
                    if (!shelfFilterActive && !isSearchAll) return false;
                    // 防御: 推荐数据没有 sortName, 跳过该过滤 (UI 也会自动清空)
                    if (heiyanSortFilter && !shelfFilterActive) {
                      if (((ex.sortName as string) || '') !== heiyanSortFilter) return false;
                    }
                    if (heiyanTagFilter) {
                      const tags = Array.isArray(ex.tags) ? (ex.tags as string[]) : [];
                      if (!tags.includes(heiyanTagFilter)) return false;
                    }
                    return true;
                  });

                  if (books.length === 0) {
                    return <EmptyState icon={BookOpen} title="没有匹配的作品" desc="试试调整来源 / 分类 / 标签组合" />;
                  }

                  // 推荐: 按 shelf 分组 (书城轮播 / 爆款力荐 / 热门绝佳 / 新书尝鲜)
                  // 书库全量: 按 sortName 分组
                  const groupKey = shelfFilterActive ? 'shelf' : 'sortName';
                  const groups = new Map<string, TrendingItem[]>();
                  books.forEach((item) => {
                    const ex = (item.extra || {}) as Record<string, unknown>;
                    const key = ((ex[groupKey] as string) || '其他').trim() || '其他';
                    if (!groups.has(key)) groups.set(key, []);
                    groups.get(key)!.push(item);
                  });

                  return (
                    <div className="flex flex-col gap-4">
                      {Array.from(groups.entries()).map(([group, items]) => {
                        const sortMeta = !shelfFilterActive
                          ? (HEIYAN_SORT_STYLE[group] || HEIYAN_SORT_FALLBACK)
                          : null;
                        // 推荐 shelf 名走映射表 (书城轮播图 → 编辑精选), 书库全量 sortName 直接显示
                        const displayLabel = sortMeta?.label
                          || (shelfFilterActive ? (HEIYAN_HOME_SHELF_LABELS[group] || group) : (group || '其他'));
                        return (
                          <div key={group}>
                            <div className="mb-2 flex items-center gap-2 px-1">
                              <span
                                className="rounded-xs px-2 py-0.5 text-[12px] font-black"
                                style={
                                  sortMeta
                                    ? { background: sortMeta.bg, color: sortMeta.color }
                                    : { background: '#F5F0FF', color: '#A855F7' }
                                }
                              >
                                {displayLabel}
                              </span>
                              <span className="text-[11px] text-gray-400">{items.length} 本</span>
                            </div>
                            <div className="fanqie-book-grid grid gap-2.5">
                              {items.map((item) => (
                                <WebnovelCard
                                  key={item.id}
                                  item={item}
                                  platform={platform}
                                />
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                }
              }
              return (
                <div className="fanqie-book-grid grid gap-2.5">
                  {filteredBooks.map((item) => (
                    <BookCard
                      key={'book_id' in item ? `${platform}-${item.book_id}-${item.position}` : `${platform}-${item.business_id}-${item.position}`}
                      item={item}
                      platform={platform}
                      rankTab={rankTab}
                      favorite={bookFavoriteKeys.has(getBookFavoriteMeta(item, platform, rankTab).target_key)}
                      favoritePending={bookFavoritePendingKeys.has(getBookFavoriteMeta(item, platform, rankTab).target_key)}
                      onFavorite={handleToggleBookFavorite}
                    />
                  ))}
                </div>
              );
            })()}
          </div>
        </main>
      </div>
      )}
    </div>
  );
}

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-extrabold text-gray-500">{title}</div>
      <div className="flex w-full flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function SummaryMetric({ label, value, tone = 'neutral' }: { label: string; value: string | number; tone?: 'neutral' | 'teal' | 'red' }) {
  const toneClass = tone === 'teal' ? 'text-teal' : tone === 'red' ? 'text-red' : 'text-gray-900';
  return (
    <div className="border-r border-gray-100 p-4 last:border-r-0">
      <div className="mb-1 text-[11px] text-gray-400">{label}</div>
      <div className={cx('font-mono text-2xl font-black leading-none', toneClass)}>{value}</div>
    </div>
  );
}

function MiniMetric({ label, value, tone = 'neutral' }: { label: string; value: string | number; tone?: 'neutral' | 'teal' | 'red' }) {
  const toneClass = tone === 'teal' ? 'text-teal' : tone === 'red' ? 'text-red' : 'text-gray-900';
  return (
    <div className="rounded-xs bg-white px-2 py-2">
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className={cx('mt-0.5 font-mono text-sm font-black', toneClass)}>{value}</div>
    </div>
  );
}

function FilterChip({
  active,
  color,
  onClick,
  children,
  className,
  title,
}: {
  active: boolean;
  color: string;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cx('whitespace-nowrap rounded-xs border px-3 py-2 text-xs font-bold transition', className)}
      style={chipStyle(active, color)}
    >
      {children}
    </button>
  );
}

function SummaryTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
      <div className="mb-1 text-[11px] text-gray-400">{label}</div>
      <div className="font-mono text-xl font-black text-gray-900">{value}</div>
    </div>
  );
}
