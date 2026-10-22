'use client';

import React, { useState, useEffect, useCallback, useRef, Suspense } from 'react';
import {
  ChevronDown,
  Activity,
  BarChart3,
  Clock3,
  Filter,
  Gauge,
  Layers3,
  Radar,
  RefreshCw,
  Rss,
} from 'lucide-react';
import { createRequestGuard } from '@/lib/request-guard';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import {
  ClusterCard,
  PanelTitle,
  StatTile,
  TrendBadge,
  WebnovelItemRow,
} from './_components';
import {
  CATEGORIES,
  CATEGORY_COLORS,
  SOURCE_LABELS,
  isWebnovelSource,
  sourceBrand,
  RESONANCE_COLORS,
} from './_trending-utils';
import {
  trendingApi,
  type TrendingItem,
  type TrendingSource,
  type CrossPlatformCluster,
  type PersistentTopic,
} from '@/lib/api';
import { timeAgoShort as formatTime } from '@/lib/datetime';

/* ── Constants ── */


/* ── Page ── */

function TrendingPage() {
  const { currentUser } = useAppContext();
  const [filtersOpen, setFiltersOpen] = useState(false);
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
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const requests = useRef(createRequestGuard());
  const [minResonance, setMinResonance] = useState(2);

  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedSource, setSelectedSource] = useState('');

  const fetchList = useCallback(async () => {
    const active = requests.current.begin();
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
      if (active()) setItems(itemList);
    } catch (e) {
      if (active()) setError(e instanceof Error ? e.message : '趋势数据加载失败');
    } finally {
      if (active()) setLoading(false);
    }
  }, [selectedCategory, selectedSource]);

  const fetchClusters = useCallback(async () => {
    const active = requests.current.begin();
    setLoading(true);
    setError(null);
    try {
      const data = await trendingApi.crossPlatform({ min_resonance: minResonance, limit: 50 });
      if (!active()) return;
      setClusters(data.clusters || []);
      if (minResonance === 2) {
        setStats(prev => ({ ...prev, resonanceCount: data.total ?? data.clusters?.length ?? 0 }));
      }
    } catch (e) {
      if (active()) setError(e instanceof Error ? e.message : '共振数据加载失败');
    } finally {
      if (active()) setLoading(false);
    }
  }, [minResonance]);

  const fetchPersistent = useCallback(async () => {
    const active = requests.current.begin();
    setLoading(true);
    setError(null);
    try {
      const data = await trendingApi.persistent({ min_days: 2, min_sources: 1, days_back: 7 });
      if (!active()) return;
      setPersistentTopics(data.topics || []);
      setStats(prev => ({ ...prev, persistentCount: data.total ?? data.topics?.length ?? 0 }));
    } catch (e) {
      if (active()) setError(e instanceof Error ? e.message : '持续热度数据加载失败');
    } finally {
      if (active()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const guard = requests.current;
    if (tab === 'list') fetchList();
    else if (tab === 'resonance') fetchClusters();
    else fetchPersistent();
    return () => guard.invalidate();
  }, [tab, fetchList, fetchClusters, fetchPersistent, refreshVersion]);

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
    if (syncing) return;
    setSyncing(true);
    setSyncError(null);
    setSyncNotice(null);
    try {
      await trendingApi.syncAll();
      await fetchStats();
      setRefreshVersion(version => version + 1);
      setSyncNotice('全量同步已完成');
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : '同步失败，请重试');
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
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="hidden sm:flex mb-3 flex flex-wrap items-center gap-2.5">
              <Badge tone="primary" className="gap-1.5 font-mono">
                <Radar size={13} strokeWidth={2.4} />
                TREND RADAR
              </Badge>
              <span className="text-xs font-black text-gray-500">{activeLabel}</span>
            </div>
            <h1 className="m-0 text-2xl font-black leading-snug sm:text-[28px] text-gray-900">
              趋势雷达
            </h1>
            <p className="mt-2 max-w-[760px] text-[13px] leading-7 text-gray-500">
              按平台扫描榜单，寻找跨平台共振与持续热度。
            </p>
          </div>
          {canSyncTrending && (
            <Button type="button" variant="primary" onClick={handleSyncAll} disabled={syncing || syncingSource !== null} className="whitespace-nowrap px-4 shadow-[0_10px_22px_rgba(255,107,53,0.18)]">
              <RefreshCw size={14} strokeWidth={2.3} className={syncing ? 'animate-spin' : ''} />
              {syncing ? '同步中...' : '刷新全量'}
            </Button>
          )}
        </div>
        <div className="mt-4.5 hidden grid-cols-4 gap-2.5 sm:grid">
          <StatTile icon={Rss} label="信源" value={stats.sourceCount || filteredSources.length || sources.length} hint="当前可扫描平台" colorClass="text-primary" />
          <StatTile icon={Layers3} label="样本" value={stats.sampleCount || items.length} hint="榜单候选内容" colorClass="text-teal" />
          <StatTile icon={Activity} label="共振" value={stats.resonanceCount} hint="最低 2 平台" colorClass="text-red" />
          <StatTile icon={Clock3} label="持续" value={stats.persistentCount} hint="近 7 天持续话题" colorClass="text-amber" />
        </div>
        <p className="mt-3 text-sm text-gray-600 sm:hidden">{sources.length} 个信源 · {items.length} 条榜单内容</p>
      </Panel>

      {syncError && <p role="alert" className="mt-3 rounded-sm bg-red-light p-3 text-sm text-red">{syncError}</p>}
      {syncNotice && <p role="status" className="mt-3 text-sm text-teal">{syncNotice}</p>}
      <div className="mt-4.5 grid grid-cols-[minmax(0,1fr)_300px] items-start gap-4.5 max-xl:grid-cols-1">
        <main className="min-w-0">
          {loading && <LoadingState />}

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
                          disabled={syncing || syncingSource !== null}
                          aria-label={`刷新${SOURCE_LABELS[source] || source}榜单`}
                          onClick={async () => {
                            setSyncingSource(source);
                            setSyncError(null);
                            setSyncNotice(null);
                            try {
                              await trendingApi.sync(source);
                              await fetchStats();
                              setRefreshVersion(version => version + 1);
                              setSyncNotice(`${SOURCE_LABELS[source] || source}同步已完成`);
                            } catch (err) {
                              setSyncError(err instanceof Error ? err.message : '信源同步失败，请重试');
                            } finally {
                              setSyncingSource(null);
                            }
                          }}
                          className="inline-flex h-[22px] w-6 items-center justify-center rounded-xs border border-gray-200 bg-white p-0 transition disabled:cursor-wait disabled:opacity-60"
                          style={{ color: brand.color }}
                          title="刷新此榜单"
                        >
                          <RefreshCw size={12} strokeWidth={2.2} className={syncingSource === source ? 'animate-spin' : ''} />
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
            <PanelTitle icon={BarChart3} title="视图切换" hint={activeLabel} className="hidden xl:flex" />
            <div role="group" aria-label="趋势视图" className="grid grid-cols-3 gap-2 xl:grid-cols-1">
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
                    aria-pressed={active}
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
                    <div className="mt-1 hidden text-xs leading-5 text-gray-600 xl:block">{t.desc}</div>
                  </button>
                );
              })}
            </div>
          </Panel>

          <button type="button" aria-expanded={filtersOpen} aria-controls="trending-filters" onClick={() => setFiltersOpen(value => !value)} className="flex min-h-11 items-center justify-between rounded-sm border border-gray-200 bg-white px-4 text-sm text-gray-700 xl:hidden">筛选与信源<ChevronDown size={16} className={filtersOpen ? 'rotate-180 transition' : 'transition'} /></button>
          <div id="trending-filters" className={cx(filtersOpen ? 'contents' : 'hidden', 'xl:contents')}>
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
                      aria-pressed={active}
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
                      aria-pressed={active}
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
          </div>
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
