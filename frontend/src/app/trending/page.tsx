'use client';

import React, { useState, useEffect, useCallback, Suspense } from 'react';
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BarChart3,
  Clock3,
  ExternalLink,
  Filter,
  Gauge,
  Layers3,
  Lightbulb,
  Radar,
  RefreshCw,
  Rss,
  Star,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import {
  trendingApi,
  type TrendingItem,
  type TrendingSource,
  type TrendingAngleRecommendation,
  type CrossPlatformCluster,
  type CrossPlatformSourceItem,
  type PersistentTopic,
} from '@/lib/api';
import { timeAgoShort as formatTime } from '@/lib/datetime';

/* ── Constants ── */

const CATEGORIES = [
  { value: '', label: '全部' },
  { value: 'hot', label: '热点' },
  { value: 'tech', label: '科技' },
  { value: 'finance', label: '财经' },
  { value: 'webnovel', label: '网文' },
  { value: 'podcast', label: '播客' },
  { value: 'community', label: '社区' },
  { value: 'entertainment', label: '娱乐' },
] as const;

const SOURCE_BRAND: Record<string, { label: string; color: string; bg: string }> = {
  weibo:       { label: '微博',     color: '#FF8200', bg: '#FFF7EB' },
  baidu:       { label: '百度',     color: '#306CFF', bg: '#EBF1FF' },
  douyin:      { label: '抖音',     color: '#161823', bg: '#F5F5F7' },
  toutiao:     { label: '头条',     color: '#F85959', bg: '#FFF0F0' },
  zhihu:       { label: '知乎',     color: '#0066FF', bg: '#EBF2FF' },
  bilibili:    { label: 'B站',      color: '#FB7299', bg: '#FFF0F5' },
  hackernews:  { label: 'HN',       color: '#FF6600', bg: '#FFF5EB' },
  ithome:      { label: 'IT之家',   color: '#D22222', bg: '#FFF0F0' },
  juejin:      { label: '掘金',     color: '#1E80FF', bg: '#EBF3FF' },
  eastmoney:   { label: '东方财富', color: '#D4940A', bg: '#FFF8E8' },
  douban:      { label: '豆瓣',     color: '#00B51D', bg: '#EEFBF0' },
  tieba:       { label: '贴吧',     color: '#4E6EF2', bg: '#EEF1FD' },
  netease:     { label: '网易',     color: '#C03A3A', bg: '#FDF0F0' },
  v2ex:        { label: 'V2EX',     color: '#333333', bg: '#F0F0F0' },
  github:      { label: 'GitHub',   color: '#24292F', bg: '#F0F1F3' },
  sspai:       { label: '少数派',   color: '#D6192B', bg: '#FDF0F0' },
  xueqiu:      { label: '雪球',     color: '#1478FF', bg: '#ECF3FF' },
  sohu:        { label: '搜狐',     color: '#D8503C', bg: '#FDF0EF' },
  hupu:        { label: '虎扑',     color: '#D43030', bg: '#FDF0F0' },
  kr36:        { label: '36氪',     color: '#0080FF', bg: '#ECF3FF' },
  heiyan:      { label: '黑岩',     color: '#A855F7', bg: '#F5F0FF' },
  ishugui:     { label: '点众',     color: '#0EA5E9', bg: '#EBF8FF' },
  xyzrank:     { label: '播客榜',   color: '#9333EA', bg: '#F5F0FF' },
};

function sourceBrand(source: string) {
  return SOURCE_BRAND[source] || { label: source, color: '#4B5563', bg: '#F3F4F6' };
}

const SOURCE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(SOURCE_BRAND).map(([k, v]) => [k, v.label])
);

const CATEGORY_COLORS: Record<string, { bgClass: string; textClass: string; borderClass: string }> = {
  hot: { bgClass: 'bg-primary-light', textClass: 'text-primary', borderClass: 'border-primary-border' },
  tech: { bgClass: 'bg-teal-light', textClass: 'text-teal', borderClass: 'border-teal-border' },
  finance: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border' },
  webnovel: { bgClass: 'bg-purple-light', textClass: 'text-purple', borderClass: 'border-purple-border' },
  podcast: { bgClass: 'bg-purple-light', textClass: 'text-purple', borderClass: 'border-purple-border' },
  community: { bgClass: 'bg-teal-light', textClass: 'text-teal', borderClass: 'border-teal-border' },
  entertainment: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border' },
};

/** 是否为网文类目 (走 bookId/cover/author/tags 字段而非纯 hot_value) */
function isWebnovelSource(source: string): boolean {
  return source === 'heiyan' || source === 'ishugui';
}

/** 网文 item 卡片: 取 extra 里的封面/作者/字数/标签做信息密度更高的展示 */
function WebnovelItemRow({ item, rank }: { item: TrendingItem; rank: number }) {
  const extra = (item.extra || {}) as Record<string, unknown>;
  const author = (extra.author as string) || '';
  const words = (extra.words_str as string) || (extra.total_word_size as string) || '';
  const tags = Array.isArray(extra.tags)
    ? (extra.tags as unknown[]).map(String)
    : Array.isArray(extra.tag_v3)
      ? (extra.tag_v3 as unknown[]).map(String)
      : [];
  const shelf = (extra.shelf as string) || item.hot_value_raw || '';
  const score = extra.book_score != null ? String(extra.book_score) : '';
  const isShort = (extra.type as number) === 1 || (extra.words as number) <= 30000;

  return (
    <a
      href={item.url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      className={cx(
        'flex items-start gap-2.5 border-b border-gray-100 px-3.5 py-2 no-underline transition hover:bg-purple-light',
        rank <= 3 ? 'bg-gray-50' : 'bg-white',
      )}
    >
      <span className={cx(
        'mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-xs font-mono text-[11px] font-black',
        rank === 1 ? 'bg-gradient-to-br from-purple to-[#C084FC] text-white'
          : rank === 2 ? 'bg-gradient-to-br from-amber to-[#FFB870] text-white'
            : rank === 3 ? 'bg-gradient-to-br from-[#FFD59E] to-[#FFE0B2] text-white'
              : 'bg-gray-100 text-gray-500',
      )}>
        {rank}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-black leading-snug text-gray-900">
          {item.title}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-gray-500">
          {author && <span>{author}</span>}
          {words && <span>· {words}</span>}
          {isShort && <span className="rounded-xs bg-purple-light px-1 py-px font-bold text-purple">短篇</span>}
          {score && <span className="text-amber">★ {score}</span>}
        </div>
        {tags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {tags.slice(0, 3).map((t, i) => (
              <span key={i} className="rounded-xs bg-gray-100 px-1 py-px text-[9px] text-gray-600">
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      <span className="mt-0.5 shrink-0 whitespace-nowrap text-[9px] text-gray-400">
        {shelf}
      </span>
    </a>
  );
}

const TREND_ICONS: Record<string, LucideIcon> = {
  up: ArrowUp, down: ArrowDown, new: Star, stable: ArrowRight,
};

const RESONANCE_COLORS: Record<number, { bgClass: string; textClass: string; borderClass: string; label: string }> = {
  5: { bgClass: 'bg-red-light', textClass: 'text-red', borderClass: 'border-red-light', label: '超强共振' },
  4: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border', label: '强共振' },
  3: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border', label: '共振' },
  2: { bgClass: 'bg-teal-light', textClass: 'text-teal', borderClass: 'border-teal-border', label: '轻微' },
};

/* ── Components ── */

function TrendBadge({ trend }: { trend: string | null }) {
  if (!trend || trend === 'stable') return null;
  const colors: Record<string, { className: string; fill: string }> = {
    up: { className: 'bg-red-light text-red', fill: 'none' },
    down: { className: 'bg-teal-light text-teal', fill: 'none' },
    new: { className: 'bg-primary-light text-primary', fill: 'currentColor' },
  };
  const c = colors[trend] || { className: 'bg-gray-100 text-gray-600', fill: 'none' };
  const Icon = TREND_ICONS[trend] || ArrowRight;
  return (
    <span className={cx('inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-black', c.className)}>
      <Icon size={11} strokeWidth={2.2} fill={c.fill} />
    </span>
  );
}

function PanelTitle({
  icon: Icon,
  title,
  hint,
}: {
  icon: LucideIcon;
  title: string;
  hint?: string;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <Icon size={15} className="text-primary" strokeWidth={2.2} />
        <span className="text-[13px] font-black text-gray-900">{title}</span>
      </div>
      {hint && <span className="whitespace-nowrap text-[11px] text-gray-400">{hint}</span>}
    </div>
  );
}

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  colorClass,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  hint: string;
  colorClass: string;
}) {
  return (
    <div className="min-w-0 rounded-sm border border-gray-200 bg-gray-50 px-3.5 py-3">
      <div className="mb-2 flex items-center gap-2">
        <Icon size={14} className={colorClass} strokeWidth={2.2} />
        <span className="text-[11px] font-black text-gray-500">{label}</span>
      </div>
      <div className="font-mono text-[25px] font-black leading-none text-gray-900">
        {value}
      </div>
      <div className="mt-1.5 text-[10.5px] text-gray-400">{hint}</div>
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <Panel className="p-[72px] text-center text-sm text-gray-400">
      {children}
    </Panel>
  );
}

/* ── 共振话题卡片 ── */

function ResonanceBadge({ resonance }: { resonance: number }) {
  const c = RESONANCE_COLORS[resonance] || RESONANCE_COLORS[2];
  return (
    <span className={cx('whitespace-nowrap rounded-xs px-2 py-0.5 text-[11px] font-black', c.bgClass, c.textClass)}>
      {c.label} · {resonance}平台
    </span>
  );
}

function SourceMiniItem({ item }: { item: CrossPlatformSourceItem }) {
  return (
    <a
      href={item.url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      className="flex min-w-0 flex-1 items-center gap-2 rounded-xs border border-gray-100 bg-white px-2.5 py-1.5 no-underline transition hover:border-primary-border hover:bg-primary-light"
    >
      <span className={cx('min-w-4 text-[10px] font-black', item.rank <= 3 ? 'text-primary' : 'text-gray-400')}>
        #{item.rank}
      </span>
      <span className="flex-1 truncate text-xs text-gray-700">
        {item.title}
      </span>
      <span className="shrink-0 text-[10px] text-gray-400">
        {SOURCE_LABELS[item.source] || item.source}
      </span>
    </a>
  );
}

/* ── 角度推荐面板 ── */

function AnglePanel({ cluster }: { cluster: CrossPlatformCluster }) {
  const { currentUser } = useAppContext();
  const [angles, setAngles] = useState<TrendingAngleRecommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetched, setFetched] = useState(false);

  const fetchAngles = async () => {
    if (fetched || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await trendingApi.angles(cluster.topic);
      setAngles(data);
      setFetched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '角度生成失败');
    } finally {
      setLoading(false);
    }
  };

  if (!currentUser) return null;

  return (
    <div className="mt-2 rounded-sm border border-amber-border bg-amber-light px-3.5 py-2.5">
      {/* 按钮行 */}
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[11px] font-black text-amber">AI 角度推荐</span>
        {!fetched && !loading && (
          <button
            type="button"
            onClick={fetchAngles}
            className="rounded-full bg-amber px-2 py-0.5 text-[10px] font-black text-white"
          >
            生成反差角度
          </button>
        )}
        {loading && (
          <span className="text-[10px] text-amber">生成中...</span>
        )}
      </div>

      {/* 大众角度（不要写） */}
      {angles && angles.common_angles.length > 0 && (
        <div className="mb-2">
          <div className="mb-1 text-[10px] font-black text-amber">
            大众角度（不要写）：
          </div>
          <div className="flex flex-wrap gap-1">
            {angles.common_angles.map((a, i) => (
              <span key={i} className="rounded-xs bg-amber-light px-1.5 py-0.5 text-[10px] text-amber line-through">{a}</span>
            ))}
          </div>
        </div>
      )}

      {/* 反差角度 */}
      {angles && angles.contrast_angles.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-black text-teal">
            反差角度（值得写）：
          </div>
          {angles.contrast_angles.map((c, i) => (
            <div key={i} className="mb-1.5 rounded-xs bg-teal-light px-2.5 py-1.5">
              <div className="mb-0.5 text-xs font-black text-teal">
                <span className="inline-flex items-center gap-1.5">
                  <ArrowRight size={12} strokeWidth={2} />
                  {c.angle}
                </span>
              </div>
              <div className="text-[10px] text-teal">
                {c.reasoning}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 角度洞察 */}
      {angles && angles.angle_note && (
        <div className="mt-1.5 flex items-start gap-1.5 rounded-xs bg-teal-light px-2 py-1 text-[10px] italic text-teal">
          <Lightbulb size={12} strokeWidth={2} className="mt-px shrink-0" />
          <span>{angles.angle_note}</span>
        </div>
      )}

      {error && (
        <div className="text-[10px] text-red">{error}</div>
      )}
    </div>
  );
}

/* ── 展开后的完整 ClusterCard ── */

function ClusterCardExpanded({ cluster }: { cluster: CrossPlatformCluster }) {
  return (
    <>
      {/* 平台详情 */}
      <div className="mb-2 text-[11px] font-black uppercase tracking-[0.05em] text-gray-500">
        各平台排名
      </div>
      <div className="flex flex-wrap gap-1.5">
        {cluster.source_items.map(item => (
          <SourceMiniItem key={`${item.source}-${item.rank}`} item={item} />
        ))}
      </div>
      <div className="mt-2.5 flex items-center justify-between gap-3 border-t border-dashed border-gray-200 pt-2">
        <span className="text-[11px] text-gray-400">
          平均排名 #{cluster.avg_rank} · {cluster.total_hot.toLocaleString()} 总热度
        </span>
        <a
          href={cluster.source_items[0]?.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[11px] font-black text-primary no-underline"
        >
          查看详情
          <ExternalLink size={12} strokeWidth={2} />
        </a>
      </div>

      {/* AI 角度推荐 */}
      <AnglePanel cluster={cluster} />
    </>
  );
}

function ClusterCard({ cluster }: { cluster: CrossPlatformCluster }) {
  const [expanded, setExpanded] = useState(false);
  const resonanceMeta = RESONANCE_COLORS[cluster.resonance] || RESONANCE_COLORS[2];

  return (
    <Panel className="overflow-hidden shadow-[0_10px_26px_rgba(15,23,42,0.04)] transition hover:border-gray-300 hover:shadow-md">
      {/* 卡片头部 */}
      <div
        onClick={() => setExpanded(!expanded)}
        className={cx('cursor-pointer px-4 py-3.5', expanded ? 'bg-primary-light/60' : 'bg-white')}
      >
        <div className="flex items-start gap-2.5">
          {/* 左侧：共振强度标识 */}
          <div className={cx('flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-md border', resonanceMeta.bgClass, resonanceMeta.textClass, resonanceMeta.borderClass)}>
            <span className="text-base font-black leading-none">{cluster.resonance}</span>
            <span className="mt-0.5 text-[8px] font-black">平台</span>
          </div>

          {/* 中间：标题+关键词 */}
          <div className="min-w-0 flex-1">
            <div className="line-clamp-2 text-sm font-bold leading-snug text-gray-900">
              {cluster.topic}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {cluster.keywords.slice(0, 4).map(kw => (
                <span key={kw} className="rounded bg-gray-100 px-1.5 py-px text-[10px] text-gray-500">#{kw}</span>
              ))}
            </div>
          </div>

          {/* 右侧：平台标签+展开按钮 */}
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <ResonanceBadge resonance={cluster.resonance} />
            <span className="inline-flex items-center gap-1 text-[11px] text-gray-400">
              {expanded ? '收起' : '展开'}
              {expanded ? <ArrowUp size={12} strokeWidth={2} /> : <ArrowDown size={12} strokeWidth={2} />}
            </span>
          </div>
        </div>

        {/* 平台横向滚动条 */}
        <div className="mt-2.5 flex gap-1.5 overflow-x-auto pb-1">
          {cluster.source_labels.map((label, i) => (
            <span key={i} className="shrink-0 whitespace-nowrap rounded-full bg-teal-light px-2 py-0.5 text-[10px] font-semibold text-teal">
              {label}
            </span>
          ))}
          <span className="ml-1 shrink-0 text-[10px] text-gray-400">
            {cluster.item_count}条相关内容
          </span>
        </div>
      </div>

      {/* 展开详情 */}
      {expanded && (
        <div className="border-t border-gray-100 bg-primary-light/60 px-4 pb-3.5 pt-2.5">
          <ClusterCardExpanded cluster={cluster} />
        </div>
      )}
    </Panel>
  );
}

/* ── Page ── */

function TrendingPage() {
  const { currentUser } = useAppContext();
  const [tab, setTab] = useState<'list' | 'resonance' | 'persistent'>('list');
  const [items, setItems] = useState<TrendingItem[]>([]);
  const [sources, setSources] = useState<TrendingSource[]>([]);
  const [clusters, setClusters] = useState<CrossPlatformCluster[]>([]);
  const [persistentTopics, setPersistentTopics] = useState<PersistentTopic[]>([]);
  const [stats, setStats] = useState({
    sourceCount: 0,
    sampleCount: 0,
    resonanceCount: 0,
    persistentCount: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [minResonance, setMinResonance] = useState(2);

  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedSource, setSelectedSource] = useState('');

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 黑岩/点众是网文平台，不属于"普通热榜"——它们在网文雷达页面 (/novel) 看
      const itemList = await trendingApi.list({
        category: selectedCategory || undefined,
        source: selectedSource || undefined,
        exclude_sources: ['heiyan', 'ishugui'],
        limit: 200,
      });
      setItems(itemList);
    } catch (e) {
      setError(e instanceof Error ? e.message : '趋势数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [selectedCategory, selectedSource]);

  const fetchClusters = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await trendingApi.crossPlatform({ min_resonance: minResonance, limit: 50 });
      setClusters(data.clusters || []);
      if (minResonance === 2) {
        setStats(prev => ({ ...prev, resonanceCount: data.total ?? data.clusters?.length ?? 0 }));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '共振数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [minResonance]);

  const fetchPersistent = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await trendingApi.persistent({ min_days: 2, min_sources: 1, days_back: 7 });
      setPersistentTopics(data.topics || []);
      setStats(prev => ({ ...prev, persistentCount: data.total ?? data.topics?.length ?? 0 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '持续热度数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'list') fetchList();
    else if (tab === 'resonance') fetchClusters();
    else fetchPersistent();
  }, [tab, fetchList, fetchClusters, fetchPersistent]);

  const fetchStats = useCallback(async () => {
    try {
      const [srcList, resonance, persistent] = await Promise.all([
        trendingApi.listSources(),
        trendingApi.crossPlatform({ min_resonance: 2, limit: 50 }),
        trendingApi.persistent({ min_days: 2, min_sources: 1, days_back: 7 }),
      ]);
      setStats({
        sourceCount: srcList.length,
        sampleCount: srcList.reduce((sum, source) => sum + source.count, 0),
        resonanceCount: resonance.total ?? resonance.clusters?.length ?? 0,
        persistentCount: persistent.total ?? persistent.topics?.length ?? 0,
      });
      setSources(prev => (prev.length > 0 ? prev : srcList));
    } catch (e) {
      console.error('Failed to fetch trending stats:', e);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const handleSyncAll = async () => {
    setSyncing(true);
    try {
      await trendingApi.syncAll();
      await fetchStats();
      if (tab === 'list') await fetchList();
      else await fetchClusters();
    } catch (e) {
      console.error('Sync failed:', e);
    } finally {
      setSyncing(false);
    }
  };

  const filteredSources = Array.from(
    (selectedCategory
      ? sources.filter(s => s.category === selectedCategory)
      : sources
    ).reduce((bySource, src) => {
      const existing = bySource.get(src.source);
      if (!existing) {
        bySource.set(src.source, src);
        return bySource;
      }
      bySource.set(src.source, {
        ...existing,
        count: existing.count + src.count,
        last_synced: existing.last_synced && src.last_synced
          ? existing.last_synced > src.last_synced ? existing.last_synced : src.last_synced
          : existing.last_synced || src.last_synced,
      });
      return bySource;
    }, new Map<string, TrendingSource>()).values()
  );

  // Group items by source for display
  const groupedItems: Record<string, TrendingItem[]> = {};
  for (const item of items) {
    if (!groupedItems[item.source]) groupedItems[item.source] = [];
    groupedItems[item.source].push(item);
  }

  const activeLabel = tab === 'list' ? '榜单扫描' : tab === 'resonance' ? '共振发现' : '持续热度';
  const canSyncTrending = currentUser?.role === 'admin';
  const topSources = Object.entries(groupedItems)
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 8);

  return (
    <div className="mx-auto min-h-full max-w-[1480px] px-9 pb-20 pt-7 max-md:px-3.5 max-md:pb-16 max-md:pt-4.5">
      <Panel className="relative overflow-hidden p-5.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] before:absolute before:left-0 before:right-0 before:top-0 before:h-1 before:bg-gradient-to-r before:from-primary before:to-teal max-md:p-4.5">
        <div className="relative grid grid-cols-[minmax(0,1fr)_auto] items-start gap-5 max-md:grid-cols-1">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2.5">
              <Badge tone="primary" className="gap-1.5 font-mono">
                <Radar size={13} strokeWidth={2.4} />
                TREND RADAR
              </Badge>
              <span className="text-xs font-black text-gray-500">{activeLabel}</span>
            </div>
            <h1 className="m-0 text-[28px] font-black leading-[1.12] text-gray-900">
              趋势雷达工作台
            </h1>
            <p className="mt-2 max-w-[760px] text-[13px] leading-7 text-gray-500">
              把多平台榜单、跨平台共振和持续热度放在同一个扫描台里，优先看到正在扩散、已经共振、还在持续的内容信号。
            </p>
          </div>
          {canSyncTrending && (
            <Button type="button" variant="primary" onClick={handleSyncAll} disabled={syncing} className="whitespace-nowrap px-4 shadow-[0_10px_22px_rgba(255,107,53,0.18)]">
              <RefreshCw size={14} strokeWidth={2.3} className={syncing ? 'animate-spin' : ''} />
              {syncing ? '同步中...' : '刷新全量'}
            </Button>
          )}
        </div>
        <div className="mt-4.5 grid grid-cols-4 gap-2.5 max-md:grid-cols-2">
          <StatTile icon={Rss} label="信源" value={stats.sourceCount || filteredSources.length || sources.length} hint="当前可扫描平台" colorClass="text-primary" />
          <StatTile icon={Layers3} label="样本" value={stats.sampleCount || items.length} hint="榜单候选内容" colorClass="text-teal" />
          <StatTile icon={Activity} label="共振" value={stats.resonanceCount} hint="最低 2 平台" colorClass="text-red" />
          <StatTile icon={Clock3} label="持续" value={stats.persistentCount} hint="近 7 天持续话题" colorClass="text-amber" />
        </div>
      </Panel>

      <div className="mt-4.5 grid grid-cols-[minmax(0,1fr)_300px] items-start gap-4.5 max-xl:grid-cols-1">
        <main className="min-w-0">
          {loading && <EmptyState>加载中...</EmptyState>}

          {!loading && error && (
            <EmptyState>
              <span className="text-red">⚠ {error}</span>
              <button
                type="button"
                onClick={() => { setError(null); (tab === 'list' ? fetchList : tab === 'resonance' ? fetchClusters : fetchPersistent)(); }}
                className="mt-2 rounded-xs border border-gray-300 px-3 py-1 text-xs font-bold text-gray-600 hover:bg-gray-50"
              >
                重试
              </button>
            </EmptyState>
          )}

          {!loading && !error && tab === 'resonance' && (
            clusters.length === 0 ? (
              <EmptyState>暂无共振数据，切换「1平台+」试试</EmptyState>
            ) : (
              <div className="flex flex-col gap-3">
                {clusters.map((cluster, idx) => (
                  <ClusterCard key={`${cluster.topic}-${idx}`} cluster={cluster} />
                ))}
              </div>
            )
          )}

          {!loading && !error && tab === 'persistent' && (
            <div className="flex flex-col gap-3">
              <Panel className="flex items-center gap-2.5 border-teal-border bg-teal-light px-4 py-3">
                <Gauge size={16} className="text-teal" strokeWidth={2.3} />
                <span className="text-[13px] font-bold text-gray-700">
                  连续多天在榜的话题代表热度韧性，适合沉淀成复盘、观察和解释型选题。
                </span>
              </Panel>
              {persistentTopics.length === 0 ? (
                <EmptyState>暂无持续热度数据，需积累多天快照</EmptyState>
              ) : (
                <div className="flex flex-col gap-2.5">
                  {persistentTopics.map((topic, idx) => {
                    const brand0 = sourceBrand(topic.sources[0] || 'weibo');
                    const dayTone = topic.days_on_list >= 3
                      ? 'border-primary-border bg-primary-light text-primary'
                      : topic.days_on_list >= 2
                        ? 'border-amber-border bg-amber-light text-amber'
                        : 'border-teal-border bg-teal-light text-teal';
                    return (
                      <Panel key={idx} className="grid grid-cols-[64px_minmax(0,1fr)_auto] items-center gap-4 p-4.5 shadow-[0_8px_22px_rgba(15,23,42,0.035)] max-md:grid-cols-[56px_minmax(0,1fr)]">
                        <div className={cx('flex h-[58px] min-w-[58px] flex-col items-center justify-center rounded-lg border font-mono text-xl font-black leading-none', dayTone)}>
                          {topic.days_on_list}
                          <span className="mt-1 font-sans text-[9px] font-black">天在榜</span>
                        </div>

                        <div className="min-w-0">
                          <div className="truncate text-[15px] font-black text-gray-900">
                            {topic.title}
                          </div>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {topic.sources.map(s => {
                              const b = sourceBrand(s);
                              return (
                                <span key={s} className="rounded-full px-2 py-0.5 text-[11px] font-black" style={{ color: b.color, background: b.bg }}>
                                  {SOURCE_LABELS[s] || s}
                                </span>
                              );
                            })}
                          </div>
                        </div>

                        <div className="flex shrink-0 items-center gap-4.5 max-md:col-span-2 max-md:pl-[72px]">
                          <div className="text-center">
                            <div className="font-mono text-lg font-black text-gray-800">
                              {topic.source_count}
                            </div>
                            <div className="text-[10px] text-gray-400">平台</div>
                          </div>
                          <div className="text-center">
                            <div className="font-mono text-lg font-black text-gray-800">
                              #{topic.best_rank || '-'}
                            </div>
                            <div className="text-[10px] text-gray-400">最佳</div>
                          </div>
                          {topic.rank_trend && topic.rank_trend.length > 1 && (
                            <div className="relative h-[38px] w-[84px]">
                              <svg viewBox="0 0 84 38" className="h-full w-full">
                                {(() => {
                                  const vals = topic.rank_trend.filter(v => v > 0);
                                  if (vals.length < 2) return null;
                                  const maxR = Math.max(...vals);
                                  const minR = Math.min(...vals);
                                  const range = maxR - minR || 1;
                                  const pts = vals.map((v, i) => {
                                    const x = (i / (vals.length - 1)) * 78 + 3;
                                    const y = 35 - ((v - minR) / range) * 30;
                                    return `${x},${y}`;
                                  });
                                  return (
                                    <polyline
                                      points={pts.join(' ')}
                                      fill="none"
                                      stroke={brand0.color}
                                      strokeWidth="2"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                    />
                                  );
                                })()}
                              </svg>
                            </div>
                          )}
                        </div>
                      </Panel>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {!loading && !error && tab === 'list' && items.length === 0 && (
            <EmptyState>暂无趋势数据，点击右上角「刷新全量」同步</EmptyState>
          )}

          {!loading && !error && tab === 'list' && items.length > 0 && (
            <div className="grid content-start gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(360px,1fr))] max-md:grid-cols-1">
              {Object.entries(groupedItems).map(([source, srcItems]) => {
                const brand = sourceBrand(source);
                const sourceInfo = sources.find(s => s.source === source);
                const lastSynced = sourceInfo?.last_synced;
                return (
                  <Panel key={source} className="overflow-hidden shadow-sm transition hover:border-gray-300 hover:shadow-md">
                    <div className="flex cursor-default items-center gap-2 border-b border-gray-200 px-3.5 py-2.5" style={{ background: brand.bg }}>
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm" style={{ background: brand.color }}>
                        <span className="text-[13px] font-black text-white">
                          {(SOURCE_LABELS[source] || source).charAt(0)}
                        </span>
                      </div>
                      <span className="flex-1 text-[13px] font-black" style={{ color: brand.color }}>
                        {SOURCE_LABELS[source] || source}
                      </span>
                      <span className="rounded-xs bg-white px-1.5 py-0.5 text-[9px] font-black" style={{ color: brand.color }}>
                        {srcItems.length}条
                      </span>
                      {canSyncTrending && (
                        <button
                          type="button"
                          onClick={async (e) => {
                            e.stopPropagation();
                            const btn = e.currentTarget as HTMLButtonElement;
                            btn.disabled = true;
                            try {
                              const data = await trendingApi.sync(source);
                              if (data.fetched > 0) {
                                await Promise.all([fetchList(), fetchStats()]);
                              }
                            } catch (err) {
                              console.error('Sync source failed:', err);
                            } finally {
                              btn.disabled = false;
                            }
                          }}
                          className="inline-flex h-[22px] w-6 items-center justify-center rounded-xs border border-gray-200 bg-white p-0 transition disabled:cursor-wait disabled:opacity-60"
                          style={{ color: brand.color }}
                          title="刷新此榜单"
                        >
                          <RefreshCw size={12} strokeWidth={2.2} />
                        </button>
                      )}
                      {lastSynced && (
                        <span className="rounded bg-white px-1.5 py-px text-[9px] text-gray-400">
                          {formatTime(lastSynced)}
                        </span>
                      )}
                    </div>

                    <div className="max-h-[460px] overflow-y-auto [scrollbar-color:#D1D5DB_transparent] [scrollbar-width:thin]">
                      {srcItems.map((item, idx) => {
                        const rank = idx + 1;
                        if (isWebnovelSource(item.source)) {
                          return <WebnovelItemRow key={item.id} item={item} rank={rank} />;
                        }
                        return (
                        <a
                          key={item.id}
                          href={item.url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={cx(
                            'flex items-center gap-2 border-b border-gray-100 px-3.5 py-2 no-underline transition hover:bg-primary-light',
                            idx < 3 ? 'bg-gray-50' : 'bg-white',
                          )}
                        >
                          <span className={cx(
                            'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-xs font-mono text-[11px] font-black',
                            idx === 0 ? 'bg-gradient-to-br from-primary to-[#FF8F65] text-white'
                              : idx === 1 ? 'bg-gradient-to-br from-amber to-[#FFB870] text-white'
                                : idx === 2 ? 'bg-gradient-to-br from-[#FFD59E] to-[#FFE0B2] text-white'
                                  : 'bg-gray-100 text-gray-500',
                          )}>
                            {idx + 1}
                          </span>
                          <span className="flex-1 truncate text-[12.5px] leading-snug text-gray-800">
                            {item.title}
                          </span>
                          {item.hot_value > 0 && (
                            <span className={cx('shrink-0 whitespace-nowrap font-mono text-[10px] font-medium', item.hot_value > 10000 ? 'text-primary' : 'text-gray-400')}>
                              {item.hot_value >= 10000 ? `${(item.hot_value / 10000).toFixed(1)}万` : item.hot_value.toLocaleString()}
                            </span>
                          )}
                          <TrendBadge trend={item.trend} />
                        </a>
                        );
                      })}
                    </div>
                  </Panel>
                );
              })}
            </div>
          )}
        </main>

        <aside className="sticky top-4.5 flex min-w-0 flex-col gap-3 max-xl:static max-xl:row-start-1">
          <Panel className="p-4">
            <PanelTitle icon={BarChart3} title="视图切换" hint={activeLabel} />
            <div className="grid gap-2">
              {[
                { key: 'list' as const, label: '榜单扫描', desc: '按信源查看实时榜单' },
                { key: 'resonance' as const, label: '共振发现', desc: '同一主题跨平台出现' },
                { key: 'persistent' as const, label: '持续热度', desc: '多天仍在扩散的话题' },
              ].map(t => {
                const active = tab === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setTab(t.key)}
                    className={cx(
                      'w-full rounded-sm border px-3 py-2.5 text-left transition',
                      active ? 'border-primary-border bg-primary-light' : 'border-gray-200 bg-white hover:border-gray-300',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={cx('text-[13px] font-black', active ? 'text-primary' : 'text-gray-800')}>{t.label}</span>
                      {active && <span className="h-2 w-2 rounded-full bg-primary" />}
                    </div>
                    <div className="mt-1 text-[11px] leading-5 text-gray-400">{t.desc}</div>
                  </button>
                );
              })}
            </div>
          </Panel>

          {tab === 'list' && (
            <Panel className="p-4">
              <PanelTitle icon={Filter} title="榜单筛选" hint={`${Object.keys(groupedItems).length} 个信源`} />
              <div className="mb-3 flex flex-wrap gap-2">
                {CATEGORIES.map(c => {
                  const active = selectedCategory === c.value;
                  const catColor = c.value ? CATEGORY_COLORS[c.value] : CATEGORY_COLORS.hot;
                  return (
                    <button
                      key={c.value}
                      type="button"
                      onClick={() => {
                        setSelectedCategory(c.value);
                        setSelectedSource('');
                      }}
                      className={cx(
                        'rounded-full border px-2.5 py-1 text-xs transition',
                        active ? `${catColor.bgClass} ${catColor.textClass} ${catColor.borderClass} font-black` : 'border-gray-200 bg-white font-semibold text-gray-600 hover:border-gray-300',
                      )}
                    >
                      {c.label}
                    </button>
                  );
                })}
              </div>
              <div className="flex max-h-[270px] flex-col gap-2 overflow-y-auto">
                {filteredSources.slice(0, 16).map(src => {
                  const brand = sourceBrand(src.source);
                  const active = selectedSource === src.source;
                  return (
                    <button
                      key={src.source}
                      type="button"
                      onClick={() => setSelectedSource(active ? '' : src.source)}
                      className="flex w-full items-center gap-2 rounded-xs border px-2 py-1.5 text-left transition"
                      style={{ borderColor: active ? brand.color : '#F3F4F6', background: active ? brand.bg : '#FAFAFA' }}
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: brand.color }} />
                      <span className="min-w-0 flex-1 truncate text-xs font-bold text-gray-700">
                        {brand.label}
                      </span>
                      <span className="font-mono text-[10px] text-gray-400">
                        {(groupedItems[src.source] || []).length}
                      </span>
                    </button>
                  );
                })}
              </div>
            </Panel>
          )}

          {tab === 'resonance' && (
            <Panel className="p-4">
              <PanelTitle icon={Activity} title="共振阈值" hint={`${clusters.length} 个话题`} />
              <div className="grid grid-cols-5 gap-2">
                {[1, 2, 3, 4, 5].map(r => {
                  const active = minResonance === r;
                  const meta = RESONANCE_COLORS[r] || RESONANCE_COLORS[2];
                  return (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setMinResonance(r)}
                      className={cx(
                        'rounded-xs border py-2 font-mono text-xs transition',
                        active ? `${meta.bgClass} ${meta.textClass} ${meta.borderClass} font-black` : 'border-gray-200 bg-white font-bold text-gray-500 hover:border-gray-300',
                      )}
                    >
                      {r}+
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 text-[11px] leading-5 text-gray-400">
                阈值越高，越偏向社会级话题；阈值越低，更适合捕捉早期扩散苗头。
              </p>
            </Panel>
          )}

          <Panel className="p-4">
            <PanelTitle icon={Rss} title="信源构成" hint={`${items.length} 条`} />
            {topSources.length === 0 ? (
              <div className="text-xs text-gray-400">暂无样本</div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {topSources.map(([source, srcItems]) => {
                  const brand = sourceBrand(source);
                  const width = Math.max(8, Math.round((srcItems.length / Math.max(items.length, 1)) * 100));
                  return (
                    <div key={source}>
                      <div className="mb-1 flex justify-between gap-2">
                        <span className="text-xs font-bold text-gray-700">{brand.label}</span>
                        <span className="font-mono text-[11px] text-gray-400">{srcItems.length}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-gray-100">
                        <div className="h-full rounded-full" style={{ width: `${width}%`, background: brand.color }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>
        </aside>
      </div>
    </div>
  );
}

export default function TrendingPageWrapper() {
  return (
    <Suspense fallback={<div className="p-20 text-center text-sm text-gray-400">加载中...</div>}>
      <TrendingPage />
    </Suspense>
  );
}
