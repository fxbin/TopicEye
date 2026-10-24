'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRequestGuard } from '@/lib/request-guard';
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BarChart3,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Folder,
  Flame,
  Inbox,
  KeyRound,
  Lightbulb,
  Loader2,
  Newspaper,
  Pin,
  RadioTower,
  RefreshCw,
  Smartphone,
  Target,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import { Button, Panel, cx } from '@/components/ui';
import { useAppContext } from '@/components/ClientLayout';
import {
  CurrentPeriodButton,
  PlatformHeading,
  ReportActionButton,
  ReportBadge,
  ReportFooterStat,
  ReportSectionTitle,
  ReportSidebarHeader,
  ReportStatusPanel,
} from '@/components/ReportLayout';

interface DigestTrend {
  title: string;
  desc: string;
  color?: string;
  momentum?: string;
}

interface DigestCluster {
  name: string;
  count: number;
  representative_title: string;
  heat: number;
}

interface DigestPick {
  title: string;
  reason: string;
  source?: string;
  category?: string;
  platforms: string[];
  score?: number;
  content_id?: number;
}

interface DigestActionItem {
  title: string;
  angle: string;
  platform?: string;
  difficulty?: string;
}

interface DigestCategoryInfo {
  count: number;
  top_title?: string;
  avg_score?: number;
}

export interface DigestRecord {
  id: number;
  overview: string | null;
  takeaway: string | null;
  keywords: string[] | string | null;
  trends: DigestTrend[] | string | null;
  top_picks: DigestPick[] | string | null;
  category_summary: Record<string, DigestCategoryInfo> | string | null;
  platform_tips: Record<string, string[]> | string | null;
  topic_clusters: DigestCluster[] | string | null;
  action_items: DigestActionItem[] | string | null;
  content_count: number;
  analyzed_count: number;
  source_count: number;
  category_count: number;
  status: string;
}

export interface DigestPeriodSummary {
  takeaway: string | null;
  status: string;
}

interface DigestReportPageProps<TDigest extends DigestRecord, TSummary extends DigestPeriodSummary> {
  title: string;
  badge: string;
  sidebarTitle: string;
  emptyHistoryText: string;
  emptyText: string;
  loadingText: string;
  generatingText: string;
  latestButtonLabel: string;
  periodName: string;
  topPicksTitle: string;
  actionTitle: string;
  overviewTitle: string;
  keywordTitle: string;
  /** R8 周刊化：话题聚类节的标题（周报传「本周脉络」） */
  clusterTitle?: string;
  /** R8 周刊化：聚类节是否前置到导语之后（周报=true） */
  clusterFirst?: boolean;
  /** R8 特刊化：分类概览节的标题（月报传「各版温度」） */
  categoryTitle?: string;
  historyIcon?: LucideIcon;
  api: {
    getCurrent: () => Promise<TDigest>;
    getByPeriod: (periodKey: string) => Promise<TDigest>;
    listPeriods: () => Promise<TSummary[]>;
    generate: (periodKey?: string) => Promise<TDigest>;
  };
  getDigestKey: (digest: TDigest) => string;
  getDigestLabel: (digest: TDigest) => string;
  getDigestStart: (digest: TDigest) => string;
  getDigestEnd: (digest: TDigest) => string;
  getSummaryKey: (summary: TSummary) => string;
  getSummaryLabel: (summary: TSummary) => string;
  onDigestChange?: (digest: TDigest | null) => void;
  children?: React.ReactNode;
}

function DigestStat({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><dt className="text-xs text-gray-500">{label}</dt><dd className="mt-1 font-mono text-lg font-bold text-gray-800">{value}</dd></div>;
}

function DigestPickRow({ pick, rank, onRead, lead = false }: { pick: DigestPick; rank: number; onRead: (id: number) => void; lead?: boolean }) {
  return (
    <div className={cx('grid grid-cols-[24px_minmax(0,1fr)] items-start gap-3', !lead && 'border-t border-gray-100 py-4 first:border-t-0')}>
      <span className={cx('flex h-6 w-6 items-center justify-center rounded-full font-mono text-xs font-bold', lead ? 'bg-primary text-white' : 'bg-gray-100 text-gray-600')}>{rank}</span>
      <div className="min-w-0">
        <h3 className={cx('font-bold leading-6 text-gray-900', lead ? 'text-[17px]' : 'text-[15px]')}>{pick.title}</h3>
        {pick.reason && <p className="mt-2 text-sm leading-6 text-gray-600">{pick.reason}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
          {pick.source && <span>{pick.source}</span>}
          {pick.category && <span>{pick.category}</span>}
          {(pick.platforms ?? []).map((platform, index) => <span key={`${platform}-${index}`}>{platform}</span>)}
          {pick.score ? <span className="font-mono text-primary">{pick.score} 分</span> : null}
        </div>
        {pick.content_id && <button type="button" onClick={() => onRead(pick.content_id!)} aria-label={`阅读：${pick.title}`} className="mt-2 inline-flex min-h-10 items-center gap-1.5 text-sm font-semibold text-primary hover:underline"><BookOpen size={15} />阅读原文</button>}
      </div>
    </div>
  );
}

function statusLabel(status: string) {
  if (status === 'DONE') return '已完成';
  if (status === 'ERROR') return '失败';
  if (status === 'GENERATING') return '生成中';
  return '待生成';
}

function statusClass(status: string) {
  if (status === 'DONE') return 'bg-teal-light text-teal';
  if (status === 'ERROR') return 'bg-red-light text-red';
  if (status === 'GENERATING') return 'bg-primary-light text-primary';
  return 'bg-gray-100 text-gray-400';
}

function momentumMeta(momentum?: string) {
  if (momentum === 'up') return { label: '上升', icon: ArrowUp, cls: 'bg-teal-light text-teal' };
  if (momentum === 'down') return { label: '下降', icon: ArrowDown, cls: 'bg-red-light text-red' };
  return { label: '平稳', icon: ArrowRight, cls: 'bg-gray-100 text-gray-500' };
}

function difficultyClass(value?: string) {
  if (value === '简单') return 'bg-teal-light text-teal';
  if (value === '中等') return 'bg-amber-light text-amber';
  return 'bg-red-light text-red';
}

function parseJson<T>(val: unknown, fallback: T): T {
  if (typeof val === 'string') {
    try {
      return JSON.parse(val) as T;
    } catch {
      return fallback;
    }
  }
  return (val as T) ?? fallback;
}

export default function DigestReportPage<TDigest extends DigestRecord, TSummary extends DigestPeriodSummary>({
  title,
  badge,
  sidebarTitle,
  emptyHistoryText,
  emptyText,
  loadingText,
  generatingText,
  latestButtonLabel,
  periodName,
  topPicksTitle,
  actionTitle,
  overviewTitle,
  keywordTitle,
  clusterTitle = '热门话题聚类',
  clusterFirst = false,
  categoryTitle = '分类概览',
  historyIcon: HistoryIcon = ClipboardList,
  api,
  getDigestKey,
  getDigestLabel,
  getDigestStart,
  getDigestEnd,
  getSummaryKey,
  getSummaryLabel,
  onDigestChange,
  children,
}: DigestReportPageProps<TDigest, TSummary>) {
  const [digest, setDigest] = useState<TDigest | null>(null);
  const [periods, setPeriods] = useState<TSummary[]>([]);
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [latestPeriod, setLatestPeriod] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [periodsLoading, setPeriodsLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [periodsError, setPeriodsError] = useState<string | null>(null);
  const requests = useRef(createRequestGuard());
  const historyRequests = useRef(createRequestGuard());
  const mobileHistory = useRef<HTMLDetailsElement>(null);
  // 站内阅读：点选题标题旁的 BookOpen 打开全局 ReaderDrawer（挂在 ClientLayout，全站单实例）
  const { openReader } = useAppContext();


  const loadPeriods = useCallback(async () => {
    const active = historyRequests.current.begin();
    try {
      setPeriodsLoading(true);
      setPeriodsError(null);
      const list = await api.listPeriods();
      if (active()) setPeriods(list);
    } catch (err) {
      if (active()) setPeriodsError(err instanceof Error ? err.message : '历史期刊加载失败');
    } finally {
      if (active()) setPeriodsLoading(false);
    }
  }, [api]);

  // mount-only：api 是父组件内联对象，每次 render 新引用，放依赖会无谓重查。
  useEffect(() => {
    void loadPeriods();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchDigest = useCallback(async (periodKey?: string) => {
    const active = requests.current.begin();
    try {
      setLoading(true);
      setGenerating(false);
      setError(null);
      setDigest(null);
      setSelectedPeriod(periodKey || null);
      onDigestChange?.(null);
      const data = periodKey ? await api.getByPeriod(periodKey) : await api.getCurrent();
      if (!active()) return;
      setDigest(data);
      setSelectedPeriod(getDigestKey(data));
      if (!periodKey) setLatestPeriod(getDigestKey(data));
      onDigestChange?.(data);
    } catch (err: unknown) {
      if (!active()) return;
      const errMsg = err instanceof Error ? err.message : String(err);
      if (errMsg?.includes('404') || errMsg?.includes('not found')) {
        setDigest(null);
        onDigestChange?.(null);
        setError(periodKey ? `${periodKey} 暂无${periodName}` : `暂无${periodName}数据`);
      } else {
        setError(errMsg || '加载失败');
      }
    } finally {
      if (active()) setLoading(false);
    }
  }, [api, getDigestKey, periodName, onDigestChange]);

  // 仅 mount 时加载当前期——不依赖 fetchDigest（其依赖 api/getDigestKey 是父组件
  // 内联传参，每次 render 新引用，若放依赖会重跑此 effect 拉回 current 覆盖用户切换）。
  // 后续切换由 handlePeriodSelect 主动调 fetchDigest(periodKey)。
  useEffect(() => {
    const guard = requests.current;
    const historyGuard = historyRequests.current;
    void fetchDigest();
    return () => { guard.invalidate(); historyGuard.invalidate(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePeriodSelect = useCallback((periodKey: string) => {
    if (periodKey === selectedPeriod && !error) return;
    if (mobileHistory.current) mobileHistory.current.open = false;
    void fetchDigest(periodKey);
  }, [fetchDigest, selectedPeriod, error]);

  const handleRegenerate = async (periodKey?: string) => {
    if (generating || loading) return;
    const active = requests.current.begin();
    try {
      setGenerating(true);
      setError(null);
      const data = await api.generate(periodKey);
      if (!active()) return;
      setDigest(data);
      setSelectedPeriod(getDigestKey(data));
      if (!periodKey) setLatestPeriod(getDigestKey(data));
      onDigestChange?.(data);
      await loadPeriods();
    } catch (err: unknown) {
      if (active()) setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      if (active()) setGenerating(false);
    }
  };

  const keywords = parseJson<string[]>(digest?.keywords, []);
  const trends = parseJson<DigestTrend[]>(digest?.trends, []);
  const topPicks = parseJson<DigestPick[]>(digest?.top_picks, []);
  const headlineText = digest?.takeaway || digest?.overview || `${periodName}内容已完成归档，等待进一步分析。`;
  const categorySummary = parseJson<Record<string, DigestCategoryInfo>>(digest?.category_summary, {});
  const platformTips = parseJson<Record<string, string[]>>(digest?.platform_tips, {});
  const topicClusters = parseJson<DigestCluster[]>(digest?.topic_clusters, []);

  // R8 周刊化：聚类块（clusterFirst=true 时前置到导语后，周报=本周脉络）
  const clustersSection = topicClusters.length > 0 ? (

              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={Flame} title={clusterTitle} />
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {topicClusters.map((cluster, index) => (
                    <div
                      key={`${cluster.name}-${index}`}
                      className={cx('rounded-sm border p-4', index === 0 ? 'border-primary-border bg-primary-light' : 'border-gray-200 bg-gray-50')}
                    >
                      <div className="mb-1.5 flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-black text-gray-900">{cluster.name}</span>
                        <span className={cx('shrink-0 rounded-full border px-2 py-0.5 font-mono text-[11px] font-black', index === 0 ? 'border-primary-border bg-white text-primary' : 'border-teal-border bg-teal-light text-teal')}>
                          {cluster.count}篇
                        </span>
                      </div>
                      <div className="text-xs leading-5 text-gray-500">代表: {cluster.representative_title}</div>
                      <div className="mt-2 flex items-center gap-1.5">
                        <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-100">
                          <div className="h-full rounded-full bg-[linear-gradient(90deg,var(--color-primary),var(--color-teal))]" style={{ width: `${Math.min(cluster.heat, 100)}%` }} />
                        </div>
                        <span className="font-mono text-[10px] text-gray-400">{cluster.heat}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
            
  ) : null;

  const actionItems = parseJson<DigestActionItem[]>(digest?.action_items, []);
  const visiblePeriods = useMemo(() => periods, [periods]);
  const currentKey = digest ? getDigestKey(digest) : selectedPeriod || undefined;

  const historyControls = (
    <>
        <ReportSidebarHeader icon={HistoryIcon} title={sidebarTitle} countText={`共 ${periods.length} 期`} />

        <div className="px-3 pb-1 pt-2">
          <CurrentPeriodButton active={!selectedPeriod || selectedPeriod === latestPeriod} icon={Pin} onClick={() => { if (mobileHistory.current) mobileHistory.current.open = false; void fetchDigest(); }}>
            {latestButtonLabel}
          </CurrentPeriodButton>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-3 pt-1">
          {periodsLoading ? (
            <div className="px-2 py-5 text-center text-xs text-gray-400">加载中...</div>
          ) : periodsError ? (
            <div role="alert" className="px-2 py-3 text-sm text-red">
              {periodsError}
              <Button type="button" variant="secondary" className="mt-2" onClick={() => void loadPeriods()}>重试加载历史</Button>
            </div>
          ) : visiblePeriods.length === 0 ? (
            <div className="px-2 py-5 text-center text-xs text-gray-400">{emptyHistoryText}</div>
          ) : (
            visiblePeriods.map((period) => {
              const periodKey = getSummaryKey(period);
              const isActive = selectedPeriod === periodKey;
              return (
                <button
                  key={periodKey}
                  type="button"
                  aria-current={isActive ? 'true' : undefined}
                  onClick={() => handlePeriodSelect(periodKey)}
                  className={cx(
                    'mb-0.5 block w-full rounded-xs border-l-3 px-3 py-2.5 text-left text-[13px] transition',
                    isActive ? 'border-l-primary bg-primary-light font-bold text-gray-900' : 'border-l-transparent text-gray-600 hover:bg-gray-50',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={cx('truncate', isActive ? 'text-gray-900' : 'text-gray-700')}>{getSummaryLabel(period)}</span>
                    <span className={cx('shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold', statusClass(period.status))}>
                      {statusLabel(period.status)}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-gray-400">{periodKey}</div>
                  {period.takeaway && <div className="mt-1 truncate text-[11px] text-gray-400">{period.takeaway}</div>}
                </button>
              );
            })
          )}
        </div>
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden lg:flex-row">
      <details ref={mobileHistory} className="shrink-0 border-b border-gray-200 bg-white lg:hidden">
        <summary className="cursor-pointer px-4 py-3 text-sm font-bold text-gray-700">选择期刊 · {digest ? getDigestLabel(digest) : sidebarTitle}</summary>
        <div className="flex max-h-[45dvh] flex-col overflow-y-auto">{historyControls}</div>
      </details>
      <aside className="hidden w-[260px] shrink-0 flex-col overflow-hidden border-r border-gray-200 bg-white lg:flex">
        {historyControls}
      </aside>

      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 py-5 pb-16 sm:px-6 lg:px-10 lg:py-7">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="m-0 text-[24px] font-black text-gray-900 sm:text-[26px]">{title}</h1>
              <span className="font-mono text-xs text-gray-500">{currentKey || selectedPeriod}</span>
              <span className="hidden lg:inline-flex"><ReportBadge>{badge}</ReportBadge></span>
            </div>
            <p className="mb-0 mt-1 text-xs leading-6 text-gray-500">
              {digest ? `${getDigestStart(digest)} ~ ${getDigestEnd(digest)}` : loading ? '加载中...' : selectedPeriod || `暂无${periodName}`}
            </p>
          </div>
          <ReportActionButton onClick={() => handleRegenerate(currentKey)} loading={generating || loading} loadingText={loading ? '加载中...' : '生成中...'} icon={RefreshCw}>
            重新生成
          </ReportActionButton>
        </header>

        {loading ? (
          <ReportStatusPanel icon={HistoryIcon}>{loadingText}</ReportStatusPanel>
        ) : error ? (
          <ReportStatusPanel icon={AlertTriangle} tone="error" action={<Button type="button" variant="secondary" onClick={() => void fetchDigest(selectedPeriod || undefined)}>重试加载</Button>}>{error}</ReportStatusPanel>
        ) : digest?.status === 'ERROR' ? (
          <div className="grid min-h-[360px] place-items-center p-10 text-center">
            <div>
              <AlertTriangle size={30} className="mx-auto mb-3 text-red" strokeWidth={1.9} />
              <div className="mb-3 text-sm text-gray-500">{digest.overview}</div>
              <ReportActionButton onClick={() => handleRegenerate(currentKey)} loading={generating || loading} loadingText={loading ? '加载中...' : '生成中...'} icon={RefreshCw}>
                重试生成
              </ReportActionButton>
            </div>
          </div>
        ) : digest?.status === 'GENERATING' || digest?.status === 'PENDING' ? (
          <ReportStatusPanel
            icon={Loader2}
            action={(
              <Button type="button" variant="secondary" onClick={() => currentKey && fetchDigest(currentKey)}>
                刷新状态
              </Button>
            )}
          >
            {generatingText}
          </ReportStatusPanel>
        ) : digest ? (
          <article className="max-w-[900px]">
            <Panel className="mb-4.5 p-4 sm:p-6">
              <div className="mb-2 text-xs font-semibold text-primary">本期判断</div>
              <h2 className="mb-4 text-balance text-[22px] font-bold leading-[1.4] text-gray-900 sm:text-[26px]">
                {headlineText}
              </h2>
              {topPicks[0] && <section className="border-t border-gray-200 pt-4" aria-label="头号选题">
                <div className="mb-3 text-xs font-semibold text-gray-500">头号选题</div>
                <DigestPickRow pick={topPicks[0]} rank={1} onRead={openReader} lead />
              </section>}
              <details className="mt-4 border-t border-gray-100 pt-2">
                <summary className="min-h-10 cursor-pointer py-2 text-xs leading-6 text-gray-500">分析依据 · {digest.content_count || 0} 条内容 · {digest.source_count || 0} 个信源</summary>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 pb-1 sm:grid-cols-4">
                  <DigestStat label="内容样本" value={digest.content_count || 0} />
                  <DigestStat label="完成分析" value={digest.analyzed_count || 0} />
                  <DigestStat label="推荐选题" value={topPicks.length} />
                  <DigestStat label="信源覆盖" value={digest.source_count || 0} />
                </dl>
              </details>
            </Panel>

            {digest.overview && digest.overview !== headlineText && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={Newspaper} title={overviewTitle} />
                <p className="text-sm leading-8 text-gray-600">{digest.overview}</p>
              </Panel>
            )}

            {/* R8 周刊化：聚类节前置（周报=本周脉络，紧跟导语） */}
            {clusterFirst && clustersSection}

            {keywords.length > 0 && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={KeyRound} title={keywordTitle} />
                <div className="flex flex-wrap gap-2">
                  {keywords.map((keyword, index) => (
                    <span
                      key={`${keyword}-${index}`}
                      className={cx(
                        'rounded-full border px-2.5 py-1 text-xs font-bold text-gray-700',
                        index === 0 ? 'border-primary-border bg-primary-light' : 'border-gray-200 bg-gray-50',
                      )}
                    >
                      {keyword}
                    </span>
                  ))}
                </div>
              </Panel>
            )}

            {trends.length > 0 && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={TrendingUp} title="内容趋势" />
                <div className="flex flex-col gap-3">
                  {trends.map((trend, index) => {
                    const meta = momentumMeta(trend.momentum);
                    const MomentumIcon = meta.icon;
                    return (
                      <div key={`${trend.title}-${index}`} className="grid grid-cols-[34px_minmax(0,1fr)_auto] items-start gap-3 border-t border-gray-100 py-3.5 first:border-t-0">
                        <div className="flex h-7 w-7 items-center justify-center rounded-sm bg-primary font-mono text-xs font-black text-white">
                          {String(index + 1).padStart(2, '0')}
                        </div>
                        <div className="min-w-0">
                          <div className="mb-1 text-[15px] font-black text-gray-900">{trend.title}</div>
                          <div className="text-[13px] leading-7 text-gray-500">{trend.desc}</div>
                        </div>
                        {trend.momentum && (
                          <span className={cx('rounded px-2 py-0.5 text-[10px] font-bold', meta.cls)}>
                            <span className="inline-flex items-center gap-1">
                              <MomentumIcon size={12} strokeWidth={2.2} />
                              {meta.label}
                            </span>
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Panel>
            )}

            {!clusterFirst && clustersSection}

            {topPicks.length > 1 && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={Target} title={topPicksTitle} />
                <div className="flex flex-col gap-2.5">
                  {topPicks.slice(1).map((pick, index) => <DigestPickRow key={`${pick.title}-${index}`} pick={pick} rank={index + 2} onRead={openReader} />)}
                </div>
              </Panel>
            )}

            {Object.keys(categorySummary).length > 0 && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={BarChart3} title={categoryTitle} />
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {Object.entries(categorySummary).map(([category, info]) => (
                    <div key={category} className="rounded-sm border border-gray-200 bg-gray-50 p-4">
                      <div className="mb-1.5 flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-black text-gray-900">{category}</span>
                        <span className="shrink-0 font-mono text-xs font-black text-primary">{info.count}篇</span>
                      </div>
                      <div className="truncate text-xs text-gray-500">{info.top_title || '-'}</div>
                      {info.avg_score !== undefined && (
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-100">
                            <div className="h-full rounded-full bg-teal" style={{ width: `${Math.min(info.avg_score, 100)}%` }} />
                          </div>
                          <span className="font-mono text-[10px] text-gray-400">{info.avg_score.toFixed(0)}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Panel>
            )}

            {actionItems.length > 0 && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={CheckCircle2} title={actionTitle} />
                <div className="flex flex-col gap-2.5">
                  {actionItems.map((item, index) => (
                    <div key={`${item.title}-${index}`} className={cx('flex items-start gap-3 rounded-sm border p-4', index < 3 ? 'border-primary-border bg-primary-light' : 'border-gray-200 bg-gray-50')}>
                      <div className={cx('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold', index < 3 ? 'bg-white text-primary' : 'bg-gray-100 text-gray-500')}>{index + 1}</div>
                      <div className="flex-1">
                        <div className="mb-1 text-sm font-bold text-gray-900">{item.title}</div>
                        <div className="mb-1.5 text-xs leading-5 text-gray-500">{item.angle}</div>
                        <div className="flex flex-wrap gap-1.5">
                          {item.platform && <span className="rounded bg-teal-light px-2 py-0.5 text-[10px] text-teal">{item.platform}</span>}
                          {item.difficulty && <span className={cx('rounded px-2 py-0.5 text-[10px] font-medium', difficultyClass(item.difficulty))}>{item.difficulty}</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
            )}

            {Object.keys(platformTips).length > 0 && (
              <Panel className="mb-4.5 p-5">
                <ReportSectionTitle icon={Lightbulb} title="平台创作建议" />
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {Object.entries(platformTips).map(([platform, tips]) => (
                    <Panel key={platform} className="p-4.5">
                      <PlatformHeading icon={Smartphone} label={platform} />
                      {(Array.isArray(tips) ? tips : []).map((tip, index) => (
                        <div key={`${platform}-${index}`} className={cx('mb-2 border-l-2 pl-2.5 text-xs leading-6 text-gray-500', index === 0 ? 'border-primary-border' : 'border-gray-200')}>
                          {tip}
                        </div>
                      ))}
                    </Panel>
                  ))}
                </div>
              </Panel>
            )}

            {children}
            <div className="mt-4 flex flex-wrap gap-6 border-t border-gray-200 pt-3.5 text-xs text-gray-400">
              <ReportFooterStat icon={CalendarDays}>{getDigestLabel(digest)}</ReportFooterStat>
              <ReportFooterStat icon={BarChart3}>分析 {digest.analyzed_count} 条内容</ReportFooterStat>
              <ReportFooterStat icon={RadioTower}>来自 {digest.source_count} 个信源</ReportFooterStat>
              <ReportFooterStat icon={Folder}>覆盖 {digest.category_count} 个分类</ReportFooterStat>
            </div>
          </article>
        ) : (
          <ReportStatusPanel icon={Inbox}>{emptyText}</ReportStatusPanel>
        )}
      </main>
    </div>
  );
}
