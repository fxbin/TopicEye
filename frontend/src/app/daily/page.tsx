'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  ChevronRight,
  ChevronDown,
  FileText,
  Inbox,
  ListChecks,
  Loader2,
  RefreshCw,
  RotateCcw,
  Send,
  Smartphone,
  Target,
} from 'lucide-react';
import { cx } from '@/components/ui';
import { useRouter, useSearchParams } from 'next/navigation';
import { createReportLoader } from './_report-loader';
import { useAppContext } from '@/components/ClientLayout';
import { isAdmin } from '@/lib/navigation';
import { dailyReportApi } from '@/lib/api';
import { useReadTracking } from '@/hooks/useReadTracking';
import YesterdayTracking from './_yesterday-tracking';
import SelectedDrawer from './_selected-drawer';
import type { SparklineData } from '@/components/Sparkline';
import {
  PlatformHeading,
  ReportActionButton,
  ReportFooterStat,
  ReportStatusPanel,
} from '@/components/ReportLayout';
import { BriefPickRow } from './_components';
import {
  Masthead,
  LeadIn,
  LeadPickCard,
  SecondPickRow,
  ColophonStrip,
  TrendsOneLiner,
  computeChangeMarkers,
  useWritePick,
} from './_frontpage';
import {
  type DailyReportData,
  type DateSummary,
  type CalendarDay,
  type DailyPick,
  EDITION_LABELS,
  localDateString,
  formatDateTime,
  parseJson,
  pickKey,
  groupByCategory,
  recentReportDates,
  reportLoadError,
  shiftReportDate,
} from './_daily-utils';
import type { YesterdayTrackingData } from '@/types';

export default function DailyReportPage() {
  return <React.Suspense fallback={<ReportStatusPanel icon={FileText}>正在加载日报...</ReportStatusPanel>}><DailyReportContent /></React.Suspense>;
}

function DailyReportContent() {
  const params = useSearchParams();
  const router = useRouter();
  const [report, setReport] = useState<DailyReportData | null>(null);
  const [dates, setDates] = useState<DateSummary[]>([]);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const reportScope = params.get('scope') === 'mine' ? 'mine' : 'public';
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generatingDate, setGeneratingDate] = useState<string | null>(null);
  const [expandedPick, setExpandedPick] = useState<number | null>(null);
  const [markError, setMarkError] = useState<string | null>(null);
  const navigationSeq = useRef(0);
  const indexSeq = useRef(0);
  const pendingMarks = useRef(new Set<string>());
  const touchedMarks = useRef(new Set<string>());
  const [error, setError] = useState<string | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  // 生成轮询代际：新一轮生成或组件卸载时自增，使旧的 5s 轮询循环
  // 在下一次醒来后直接退出，避免卸载后持续请求 / 交错 setState
  const generateSeqRef = useRef(0);
  // 昨日追踪数据（报头兑现行 + ▲↑↓ 变化标记共用）
  const [yesterdayData, setYesterdayData] = useState<YesterdayTrackingData | null | undefined>(undefined);

  useEffect(() => () => {
    generateSeqRef.current += 1;
  }, []);

  const refreshReportIndexes = useCallback(async () => {
    const seq = ++indexSeq.current;
    const [datesData, calendarData] = await Promise.all([
      reportScope === 'mine' ? dailyReportApi.listMyDates() : dailyReportApi.listDates(),
      reportScope === 'mine' ? Promise.resolve(null) : dailyReportApi.calendar(30),
    ]);
    if (seq !== indexSeq.current) return;
    setDates(datesData.dates || []);
    setCalendarDays(calendarData?.days || []);

  }, [reportScope]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setIndexError(null);
        await refreshReportIndexes();
      } catch {
        if (!cancelled) setIndexError('往期目录加载失败，可重试加载');

      }
    })();
    return () => { cancelled = true; indexSeq.current += 1; };
  }, [refreshReportIndexes]);

  const [sparklines, setSparklines] = useState<Record<string, SparklineData>>({});
  const [pickMarks, setPickMarks] = useState<Record<string, 'write' | 'watch' | 'skip'>>({});

  const reportLoader = useMemo(() => createReportLoader({
    report: async (date) => (date
      ? await (reportScope === 'mine' ? dailyReportApi.getMyByDate(date) : dailyReportApi.getByDate(date))
      : await (reportScope === 'mine' ? dailyReportApi.getMyToday() : dailyReportApi.getToday())) as unknown as DailyReportData,
    marks: dailyReportApi.listPickMarks,
    tracking: reportScope === 'mine' ? dailyReportApi.getMyYesterdayTracking : dailyReportApi.getYesterdayTracking,
    sparkline: (title) => dailyReportApi.sparkline(title, 48, 2),
  }, {
    report: (data) => { setReport(data); setSelectedDate(data.report_date); },
    marks: (data) => setPickMarks((current) => {
      const merged = { ...data };
      for (const key of touchedMarks.current) {
        if (current[key]) merged[key] = current[key];
        else delete merged[key];
      }
      return merged;
    }),
    tracking: setYesterdayData,
    sparkline: (key, data) => setSparklines((prev) => ({ ...prev, [key]: data })),
    loaded: () => setLoading(false),
    error: (err) => {
      setError(reportLoadError(err));
    },
  }), [reportScope]);

  const fetchReport = useCallback((date?: string, knownReport?: DailyReportData) => {
    navigationSeq.current += 1;
    touchedMarks.current.clear();
    generateSeqRef.current += 1;
    setGenerating(false);
    setGeneratingDate(null);
    setLoading(true);
    setError(null);
    setReport(null);
    setSelectedDate(date || localDateString());
    setPickMarks({});
    setSparklines({});
    setYesterdayData(undefined);
    setExpandedPick(null);
    setMarkError(null);
    return reportLoader.load(date, knownReport);
  }, [reportLoader]);

  const dateParam = params.get('date');
  useEffect(() => {
    const validDate = dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam) && dateParam <= localDateString();
    void fetchReport(validDate ? dateParam : undefined);
    return () => { reportLoader.cancel(); generateSeqRef.current += 1; };
  }, [dateParam, fetchReport, reportLoader]);

  // A report may already be generating when the reader opens or reloads the page.
  const pendingReportId = report?.status === 'GENERATING' ? report.id : null;
  useEffect(() => {
    if (pendingReportId == null || generating || error) return;
    let cancelled = false;
    const seq = navigationSeq.current;
    void (async () => {
      for (let attempt = 0; attempt < 24; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        if (cancelled || seq !== navigationSeq.current) return;
        try {
          const data = await dailyReportApi.getVersion(pendingReportId, reportScope) as unknown as DailyReportData;
          if (cancelled || seq !== navigationSeq.current) return;
          if (data.status === 'DONE' || data.status === 'ERROR') {
            void fetchReport(data.report_date, data);
            return;
          }
        } catch { /* transient status read failure: retry within the same bounded poll */ }
      }
      if (!cancelled) setError('日报仍在生成，请稍后重新加载');
    })();
    return () => { cancelled = true; };
  }, [pendingReportId, generating, error, reportScope, fetchReport]);

  const handleDateSelect = useCallback((date: string) => {
    if (date === selectedDate) return;
    const next = new URLSearchParams(params.toString());
    next.set('date', date);
    router.push(`/daily?${next}`, { scroll: false });
  }, [selectedDate, params, router]);

  const generateForDate = async (date: string) => {
    const seq = ++generateSeqRef.current;
    try {
      setGenerating(true);
      setGeneratingDate(date);
      setError(null);
      const today = localDateString();
      // POST 返回 202（后台异步生成），不再等 LLM 完成
      const started = await dailyReportApi.generateVersion({
        target_date: date,
        edition: date < today ? 'final' : 'manual',
        force: true,
      }, reportScope);
      if (seq !== generateSeqRef.current) return;
      const reportId = Number(started.id);
      if (!Number.isFinite(reportId)) throw new Error('生成响应缺少日报编号，请刷新重试');
      setReport((previous) => ({ ...previous, ...started, id: reportId, report_date: date, status: 'GENERATING' }) as DailyReportData);
      // 轮询直到 DONE（最多 120 秒）
      const maxAttempts = 24;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 5000)); // 每 5 秒轮询
        if (seq !== generateSeqRef.current) return; // 已被新一轮生成/卸载取代，放弃旧轮询
        try {
          const data = await dailyReportApi.getVersion(reportId, reportScope);
          if (seq !== generateSeqRef.current) return;
          const reportData = data as unknown as DailyReportData;
          if (reportData.status === 'DONE' || reportData.status === 'ERROR') {
            void fetchReport(date, reportData);
            await refreshReportIndexes().catch(() => setIndexError('往期目录加载失败，可重试加载'));
            return;
          }
          // 还在 GENERATING，继续等
          setReport(reportData);
        } catch {
          // 轮询失败，继续重试
        }
      }
      // 超时
      if (seq === generateSeqRef.current) {
        setError('生成超时，请稍候刷新查看');
      }
    } catch (err: unknown) {
      if (seq === generateSeqRef.current) {
        setError(err instanceof Error ? err.message : '生成失败');
      }
    } finally {
      if (seq === generateSeqRef.current) {
        setGenerating(false);
        setGeneratingDate(null);
      }
    }
  };

  const handleRegenerate = async () => {
    await generateForDate(report?.report_date || selectedDate || localDateString());
  };

  const reloadCurrent = async () => {
    const seq = navigationSeq.current;
    if (report?.status === 'GENERATING') {
      try {
        const data = await dailyReportApi.getVersion(report.id, reportScope) as unknown as DailyReportData;
        if (seq !== navigationSeq.current) return;
        void fetchReport(data.report_date, data);
      } catch (err) {
        if (seq !== navigationSeq.current) return;
        setError(err instanceof Error ? err.message : '加载失败');
      }
    } else {
      void fetchReport(selectedDate || undefined);
    }
  };

  const handleMark = useCallback(
    async (pickTitle: string, action: 'write' | 'watch' | 'skip', category?: string, sourceUrl?: string) => {
      if (!report) return;
      // 记住标记前的状态，用于失败回滚（修掉原静默失败）
      const markDate = report.report_date;
      const markSeq = navigationSeq.current;
      const pendingKey = `${markDate}:${pickTitle}`;
      if (pendingMarks.current.has(pendingKey)) return;
      pendingMarks.current.add(pendingKey);
      touchedMarks.current.add(pickTitle);
      const prevAction = pickMarks[pickTitle];
      const willUnmark = prevAction === action;
      // 乐观更新
      setPickMarks((prev) => {
        const next = { ...prev };
        if (next[pickTitle] === action) {
          delete next[pickTitle]; // toggle: 再点一次取消标记
        } else {
          next[pickTitle] = action;
        }
        return next;
      });
      setMarkError(null);
      try {
        if (willUnmark) {
          await dailyReportApi.unmarkPick(markDate, pickTitle);
        } else {
          await dailyReportApi.markPick({
            report_date: markDate,
            pick_title: pickTitle,
            action,
            pick_category: category,
            pick_source_url: sourceUrl,
          });
        }
      } catch {
        if (markSeq !== navigationSeq.current) return;
        // 失败回滚乐观更新，并给出轻量内联提示（不再静默）
        setPickMarks((prev) => {
          const next = { ...prev };
          if (prevAction) {
            next[pickTitle] = prevAction;
          } else {
            delete next[pickTitle];
          }
          return next;
        });
        setMarkError(willUnmark ? '取消标记失败，已还原' : '标记失败，已还原');
      } finally {
        pendingMarks.current.delete(pendingKey);
      }
    },
    [report, pickMarks],
  );

  const trends = parseJson(report?.trends);
  const platformTips = parseJson(report?.platform_tips);

  // todayStr 用 state 延迟到客户端渲染后计算，避免 SSR/CSR 跨天日期不一致导致 hydration mismatch。
  const [todayStr, setTodayStr] = useState('');
  useEffect(() => {
    setTodayStr(localDateString());
  }, []);
  const isToday = (selectedDate || report?.report_date) === todayStr;
  const generatedAt = formatDateTime(report?.generated_at || report?.updated_at);
  const trendList = Array.isArray(trends) ? trends as Array<{ title: string; desc: string; color?: string; momentum?: string }> : [];
  const pickList = useMemo(() => {
    const picks = parseJson(report?.top_picks);
    return Array.isArray(picks) ? picks as DailyPick[] : [];
  }, [report?.top_picks]);
  const platformTipEntries = platformTips && typeof platformTips === 'object'
    ? Object.entries(platformTips as Record<string, unknown>)
    : [];
  const recoveryDate = selectedDate || report?.report_date || todayStr;
  // 原文标题展示语言：默认中文翻译，可切换英文原文
  const [showOriginalLang, setShowOriginalLang] = useState(false);
  // 今日已选抽屉开关（一期补行动闭环）
  const [drawerOpen, setDrawerOpen] = useState(false);
  // 标记失败的轻量内联提示（修掉原 handleMark 静默失败）
  // 站内阅读：点选题卡片标题旁的 BookOpen 打开全局 ReaderDrawer（挂在 ClientLayout，全站单实例）
  const { openReader, currentUser } = useAppContext();
  const writePick = useWritePick();
  // 手动推送日报到群
  const [pushing, setPushing] = useState(false);
  const [pushMsg, setPushMsg] = useState<string | null>(null);

  const handlePushWebhook = useCallback(async () => {
    if (!report) return;
    setPushing(true);
    setPushMsg(null);
    try {
      const res = await dailyReportApi.pushWebhook(report.report_date, report.edition);
      setPushMsg(res.message);
    } catch (err: unknown) {
      setPushMsg(err instanceof Error ? err.message : '推送失败');
    } finally {
      setPushing(false);
      setTimeout(() => setPushMsg(null), 3000);
    }
  }, [report]);
  // 今日「已选」标记数（action=write），用于工具栏 badge
  const writeCount = useMemo(
    () => Object.values(pickMarks).filter((a) => a === 'write').length,
    [pickMarks],
  );

  // 阅读时长追踪：仅在报告完成（DONE）时计时，生成中/错误状态不计时；
  // 切换日期或离开页面时上报累计停留时长（行为偏好数据）
  useReadTracking(
    'daily_report',
    report?.status === 'DONE' ? report.report_date : undefined,
    report?.status === 'DONE' ? report.id : undefined,
  );

  const recoveryDays = calendarDays.filter((day) => day.status === 'MISSING' || day.status === 'ERROR');

  // ── 晨报头版派生数据 ────────────────────────────────────────────────
  // 日期目录可能分页或缺刊，不能把目录长度当作真实期号。
  // 昨日兑现行 + ▲↑↓ 标记（同一份 yesterday 数据）
  const yesterdaySummary = useMemo(() => {
    if (!yesterdayData?.has_yesterday || yesterdayData.picks.length === 0) return null;
    const s = { confirmed: 0, reversed: 0, persisted: 0, dropped: 0 };
    for (const p of yesterdayData.picks) s[p.status] += 1;
    return { ...s, recommended: yesterdayData.picks.length };
  }, [yesterdayData]);

  const yesterdayLine = yesterdaySummary
    ? `昨日推荐 ${yesterdaySummary.recommended} 题 · 兑现 ${yesterdaySummary.confirmed} · 仍在榜 ${yesterdaySummary.persisted}`
    : undefined;

  const changeMarkers = useMemo(
    () => computeChangeMarkers(pickList, yesterdayData?.picks),
    [pickList, yesterdayData],
  );

  // 头版：头题 = feature 档分数最高的一条；二条 = 其余 feature（跨分类混排）
  const { leadPick, secondPicks } = useMemo(() => {
    const features = pickList
      .filter((p) => !p.tier || p.tier === 'feature')
      .slice()
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    return { leadPick: features[0], secondPicks: features.slice(1) };
  }, [pickList]);

  const briefGroups = useMemo(() => groupByCategory(pickList, 'brief'), [pickList]);
  const hasBrief = briefGroups.length > 0;
  const readMinutes = Math.max(1, Math.ceil(pickList.length * 0.8));

  // 往期条：最近 5 期（不含当前期），复活 dates 数据
  const recentDates = useMemo(() => {
    return recentReportDates(dates, report?.report_date);
  }, [dates, report?.report_date]);

  return (
    <div className="daily-report flex h-full min-h-0 w-full flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-5 gap-y-3 border-b border-gray-200 bg-white px-4 py-3 sm:px-6">
        <nav aria-label="日报范围" className="flex shrink-0 items-center gap-1 whitespace-nowrap text-[13px] font-bold">
          <a href="/daily" aria-current={reportScope === 'public' ? 'page' : undefined} className={cx('rounded-md px-3 py-2 transition-colors', reportScope === 'public' ? 'bg-primary-light text-primary-text' : 'text-gray-600 hover:bg-gray-50')}>公共日报</a>
          <a href="/daily?scope=mine" aria-current={reportScope === 'mine' ? 'page' : undefined} className={cx('rounded-md px-3 py-2 transition-colors', reportScope === 'mine' ? 'bg-primary-light text-primary-text' : 'text-gray-600 hover:bg-gray-50')}>我的日报</a>
          <button type="button" onClick={() => setDrawerOpen(true)} disabled={writeCount === 0} className="ml-1 inline-flex items-center gap-1.5 rounded-md px-2 py-2 text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-40" title={`本期已选 ${writeCount} 个选题`}>
            <ListChecks size={16} /><span>已选 {writeCount}</span>
          </button>
        </nav>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1">
            <button type="button" aria-label="前一天" title="前一天" onClick={() => {
              handleDateSelect(shiftReportDate(selectedDate || todayStr, -1));
            }} className="grid h-9 w-8 shrink-0 place-items-center rounded-md border border-gray-200 text-gray-600 transition-colors hover:bg-gray-50">
              <ChevronRight size={16} className="rotate-180" />
            </button>
            <span className="min-w-[96px] text-center font-mono text-[13px] font-bold text-gray-800" aria-live="polite">{selectedDate || todayStr}</span>
            <button type="button" aria-label="后一天" title="后一天" disabled={isToday} onClick={() => {
              const next = shiftReportDate(selectedDate || todayStr, 1);
              if (next <= todayStr) handleDateSelect(next);
            }} className="grid h-9 w-8 shrink-0 place-items-center rounded-md border border-gray-200 text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-30">
              <ChevronRight size={16} />
            </button>
            <button type="button" onClick={() => {
              const next = new URLSearchParams(params.toString()); next.delete('date');
              if (dateParam) router.push(`/daily?${next}`, { scroll: false });
              else void fetchReport();
            }} className={cx('ml-1 rounded-md px-2 py-2 text-[13px] font-bold transition-colors', isToday ? 'bg-primary-solid text-white' : 'text-gray-600 hover:bg-gray-50')}>今天</button>
          </div>
          <details className="relative">
            <summary className="flex h-9 cursor-pointer list-none items-center gap-1 rounded-md border border-gray-200 px-2 text-[12px] font-semibold text-gray-600 hover:bg-gray-50">{generating ? <Loader2 size={13} className="animate-spin" /> : '更多'}<ChevronDown size={13} /></summary>
            <div className="absolute right-0 top-full z-20 mt-2 flex min-w-[176px] flex-col gap-1 rounded-lg border border-gray-200 bg-white p-2 shadow-lg">
              <button type="button" onClick={reloadCurrent} className="flex items-center gap-2 rounded-md px-3 py-2.5 text-left text-[13px] text-gray-700 hover:bg-gray-50"><RefreshCw size={14} />重新加载</button>
              {report && <button type="button" onClick={handleRegenerate} disabled={generating} className="flex items-center gap-2 rounded-md px-3 py-2.5 text-left text-[13px] text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                {generating ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}{generating ? '生成中' : '重新生成'}
              </button>}
              {reportScope === 'public' && report?.status === 'DONE' && isAdmin(currentUser) && <button type="button" onClick={handlePushWebhook} disabled={pushing} className="flex items-center gap-2 rounded-md px-3 py-2.5 text-left text-[13px] text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                {pushing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}{pushing ? '推送中…' : '推送到群'}
              </button>}
              {reportScope === 'public' && isAdmin(currentUser) && recoveryDays.length > 0 && <span className="px-3 py-2 text-xs text-amber-800">{recoveryDays.length} 天待补</span>}
            </div>
          </details>
          {pushMsg && <span role="status" className="text-xs text-gray-600">{pushMsg}</span>}
        </div>
      </div>

      {/* 主区域（晨报版式：报头 → 导语 → 头版 → 内页分版） */}
      <div className="min-h-0 flex-1 overflow-y-auto bg-page">
        <div className="mx-auto max-w-[960px] px-3 py-3 sm:px-8 sm:py-8">
          {indexError && <div role="status" className="mb-3 flex flex-wrap items-center gap-2 text-sm text-amber-800">{indexError}<button type="button" className="underline" onClick={() => { void refreshReportIndexes().then(() => setIndexError(null)).catch(() => setIndexError('往期目录加载失败，可重试加载')); }}>重试目录</button></div>}
          {markError && <div role="alert" className="mb-3 rounded-md bg-red-light px-4 py-3 text-sm text-red-700">{markError}</div>}
          {loading ? (
            <ReportStatusPanel icon={FileText}>正在加载日报...</ReportStatusPanel>
          ) : error ? (
            <ReportStatusPanel
              icon={AlertTriangle}
              tone="error"
              action={error === '该日期暂无日报' ? (
                <ReportActionButton onClick={() => generateForDate(recoveryDate)} loading={generating} icon={FileText}>生成本期日报</ReportActionButton>
              ) : (
                <ReportActionButton onClick={reloadCurrent} icon={RefreshCw}>重新加载</ReportActionButton>
              )}
            >
              {error}
            </ReportStatusPanel>
          ) : report?.status === 'ERROR' ? (
            <div className="grid min-h-[300px] place-items-center p-8 text-center">
              <div>
                <AlertTriangle size={28} className="mx-auto mb-3 text-red-700" strokeWidth={1.9} />
                <div className="mb-3 text-sm text-gray-500">{report.overview}</div>
                <ReportActionButton
                  onClick={() => generateForDate(report.report_date)}
                  loading={generating && generatingDate === report.report_date}
                  icon={RotateCcw}
                >
                  重试生成
                </ReportActionButton>
              </div>
            </div>
          ) : report?.status === 'GENERATING' ? (
            <ReportStatusPanel icon={Loader2}>日报生成中，请稍候...</ReportStatusPanel>
          ) : report && pickList.length > 0 ? (
            <div className="space-y-0 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
              {/* 报头（刊名/日期行/统计行：期号·昨日兑现·长度合同） */}
              <div className="bg-white">
                <Masthead
                  reportDate={report.report_date}
                  weekday={report.weekday}
                  editionLabel={report.edition ? EDITION_LABELS[report.edition] : undefined}
                  generatedAt={formatDateTime(report.cutoff_at) || generatedAt || undefined}
                  yesterdayLine={yesterdayLine}
                  pickCount={pickList.length}
                  readMinutes={readMinutes}
                />
              </div>

              {/* 导语块（takeaway 衬线导语 + 主编判断） */}
              <LeadIn takeaway={report.takeaway} overview={report.overview} />

              {/* 头版：头题全展 + 二条窄栏（跨分类混排，带 ▲↑↓ 与还热） */}
              {leadPick && (
                <LeadPickCard
                  pick={leadPick}
                  sparklineData={sparklines[pickKey(leadPick)]}
                  markAction={pickMarks[pickKey(leadPick)]}
                  showOriginalLang={showOriginalLang}
                  onToggleLang={() => setShowOriginalLang(!showOriginalLang)}
                  onMark={handleMark}
                  onOpenReader={openReader}
                  onWrite={writePick}
                />
              )}
              {secondPicks.map((pick, j) => {
                const globalIdx = pickList.indexOf(pick);
                const isExpanded = expandedPick === globalIdx;
                const key = pickKey(pick);
                return (
                  <SecondPickRow
                    key={`second-${j}`}
                    pick={pick}
                    rank={j + 2}
                    marker={changeMarkers[key]}
                    expanded={isExpanded}
                    onToggle={() => setExpandedPick(isExpanded ? null : globalIdx)}
                    markAction={pickMarks[key]}
                    onMark={handleMark}
                    onOpenReader={openReader}
                    onWrite={writePick}
                  />
                );
              })}

              {/* 中缝：昨日对账摘要 + 导流 */}
              <ColophonStrip yesterdaySummary={yesterdaySummary} />

              {/* 昨日追踪明细（折叠态：R8 校准后的问责剂量——一行摘要 + 明细可展开） */}
              <details className="bg-white">
                <summary className="cursor-pointer px-5 py-2 text-[12px] font-bold text-gray-500 hover:text-gray-600">
                  昨日追踪明细（24h 热度与兑现）
                </summary>
                <div className="px-5 pb-3">
                  <YesterdayTracking data={yesterdayData ?? null} loading={yesterdayData === undefined} />
                </div>
              </details>

              {/* 内页分版：速览（brief 档按分类分版） */}
              {hasBrief && (
                <div className="mt-4">
                  <div className="mb-2 flex flex-wrap items-center gap-2 px-1">
                    <span className="font-mono text-lg font-black text-gray-500">→</span>
                    <h2 className="text-sm font-black text-gray-700">速览 · 分版</h2>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[12px] font-bold text-gray-600">
                      {briefGroups.reduce((n, [, ps]) => n + ps.length, 0)} 篇
                    </span>
                  </div>
                  {briefGroups.map(([cat, picks], groupIdx) => (
                    <div key={`brief-group-${cat}`} className="mb-3">
                      <div className="mb-1.5 flex items-center gap-2 px-1">
                        <span className="font-mono text-[13px] font-black text-gray-500">
                          {String(groupIdx + 1).padStart(2, '0')}
                        </span>
                        <span className="text-[12px] font-black text-gray-600">{cat}</span>
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[12px] font-bold text-gray-600">{picks.length} 篇</span>
                      </div>
                      <div className="divide-y divide-gray-100 border border-gray-200 bg-white">
                        {picks.map((pick, j) => {
                          const globalIdx = pickList.indexOf(pick);
                          const isExpanded = expandedPick === globalIdx;
                          const key = pickKey(pick);
                          return (
                            <BriefPickRow
                              key={`brief-${cat}-${j}`}
                              pick={pick}
                              globalIdx={globalIdx}
                              isExpanded={isExpanded}
                              onToggleExpand={() => setExpandedPick(isExpanded ? null : globalIdx)}
                              markAction={pickMarks[key]}
                              showOriginalLang={showOriginalLang}
                              onToggleLang={() => setShowOriginalLang(!showOriginalLang)}
                              onMark={handleMark}
                              onOpenReader={openReader}
                            />
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* 趋势一行（增刊归还：缩为一行跳 /trends） */}
              <TrendsOneLiner trends={trendList} />

              {/* 平台建议（折叠态） */}
              {platformTipEntries.length > 0 && (
                <details className="mt-3 bg-white">
                  <summary className="cursor-pointer px-4 py-3 text-[13px] font-bold text-gray-600">
                    平台创作建议
                  </summary>
                  <div className="grid grid-cols-1 gap-3 px-4 pb-4 lg:grid-cols-3">
                    {platformTipEntries.map(([platform, tips]) => (
                      <div key={platform}>
                        <PlatformHeading icon={Smartphone} label={platform} />
                        {(Array.isArray(tips) ? tips : []).map((tip: string, j: number) => (
                          <div key={`${platform}-${j}`} className="mb-1.5 text-[13px] leading-6 text-gray-600">
                            {tip}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {/* 往期条：最近 5 期（每天一格带当日导语） */}
              {recentDates.length > 0 && (
                <div className="mt-4 bg-white px-5 py-3">
                  <div className="mb-2 text-[12px] font-black tracking-widest text-gray-500">往期 · 每天一格</div>
                  <div className="flex flex-wrap gap-2">
                    {recentDates.map((d) => (
                      <button
                        key={d.report_date}
                        type="button"
                        onClick={() => handleDateSelect(d.report_date)}
                        className="flex min-w-[170px] flex-1 flex-col gap-0.5 rounded-xs border border-gray-200 px-3 py-2 text-left hover:border-primary"
                        title={d.takeaway || undefined}
                      >
                        <span className="font-mono text-[12px] font-bold text-gray-500">{d.report_date} {d.weekday}</span>
                        <span className="truncate text-[12px] font-bold text-gray-700">
                          {d.takeaway || '查看当日日报'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 底部统计 + 报脚 */}
              <div className="mt-4 flex flex-wrap gap-4 border-t border-gray-200 px-5 pt-4 text-[13px] text-gray-500">
                <ReportFooterStat icon={BarChart3}>分析 {report.analyzed_count || 0} 条</ReportFooterStat>
                <ReportFooterStat icon={Target}>推荐 {pickList.length} 个选题</ReportFooterStat>
                {generatedAt && <ReportFooterStat icon={CalendarDays}>{generatedAt}</ReportFooterStat>}
              </div>
              <footer className="mt-3 border-t border-gray-100 px-5 py-4 text-center text-[13px] leading-6 text-gray-500">
                TopicEye 编辑台 · 编辑判断供选题参考，请结合原文核实
              </footer>
            </div>
          ) : report ? (
            <ReportStatusPanel icon={Inbox}>
              {report.overview || '今日暂未形成可推荐精选。'}
            </ReportStatusPanel>
          ) : (
            <ReportStatusPanel
              icon={Inbox}
              action={(
                <ReportActionButton
                  onClick={() => generateForDate(recoveryDate)}
                  loading={generating && generatingDate === recoveryDate}
                  icon={FileText}
                >
                  生成日报
                </ReportActionButton>
              )}
            >
              暂无日报数据
            </ReportStatusPanel>
          )}
        </div>
      </div>

      {/* 今日已选抽屉（一期补行动闭环）：fixed 定位，挂在根容器内即可 */}
      {report && (
        <SelectedDrawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          picks={pickList}
          pickMarks={pickMarks}
        />
      )}
    </div>
  );
}
