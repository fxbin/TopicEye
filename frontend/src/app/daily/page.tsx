'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  ChevronRight,
  FileText,
  Inbox,
  ListChecks,
  Loader2,
  RefreshCw,
  RotateCcw,
  Send,
  Smartphone,
  Target,
  KeyRound,
} from 'lucide-react';
import { cx } from '@/components/ui';
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
  ReportSectionTitle,
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
  type MarkAction,
  type DailyPick,
  SNAPSHOT_EDITION_LABELS,
  CATEGORY_ORDER,
  CATEGORY_EN,
  localDateString,
  formatDateTime,
  parseJson,
  pickKey,
  marksMapFromResp,
  groupByCategory,
} from './_daily-utils';
import type { YesterdayTrackingData } from '@/types';

export default function DailyReportPage() {
  const [report, setReport] = useState<DailyReportData | null>(null);
  const [dates, setDates] = useState<DateSummary[]>([]);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [calendarStats, setCalendarStats] = useState({ done: 0, error: 0, missing: 0, generating: 0 });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  // T2: 'public' (default) | 'mine' — query-string controlled to keep diff small
  const [reportScope] = useState<'public' | 'mine'>(() => {
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search).get('scope');
      if (p === 'mine') return 'mine';
    }
    return 'public';
  });
  const [loading, setLoading] = useState(true);
  const [datesLoading, setDatesLoading] = useState(true);
  const [calendarLoading, setCalendarLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generatingDate, setGeneratingDate] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 生成轮询代际：新一轮生成或组件卸载时自增，使旧的 5s 轮询循环
  // 在下一次醒来后直接退出，避免卸载后持续请求 / 交错 setState
  const generateSeqRef = useRef(0);
  // 昨日追踪数据（报头兑现行 + ▲↑↓ 变化标记共用）
  const [yesterdayData, setYesterdayData] = useState<YesterdayTrackingData | null>(null);

  useEffect(() => () => {
    generateSeqRef.current += 1;
  }, []);

  const refreshReportIndexes = useCallback(async () => {
    const [datesData, calendarData] = await Promise.all([
      reportScope === 'mine' ? dailyReportApi.listMyDates() : dailyReportApi.listDates(),
      dailyReportApi.calendar(30),
    ]);
    setDates(datesData.dates || []);
    setCalendarDays(calendarData.days || []);
    setCalendarStats({
      done: calendarData.done_count || 0,
      error: calendarData.error_count || 0,
      missing: calendarData.missing_count || 0,
      generating: calendarData.generating_count || 0,
    });
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setDatesLoading(true);
        setCalendarLoading(true);
        await refreshReportIndexes();
      } finally {
        setDatesLoading(false);
        setCalendarLoading(false);
      }
    })();
  }, [refreshReportIndexes]);

  const [sparklines, setSparklines] = useState<Record<string, SparklineData>>({});
  const [pickMarks, setPickMarks] = useState<Record<string, 'write' | 'watch' | 'skip'>>({});

  // 昨日追踪：报头兑现行与 ▲↑↓ 的数据源（与 YesterdayTracking 组件同一端点，
  // 页面持有一份供头版消费；错开主报告并发）
  const fetchYesterday = useCallback((reportDate: string) => {
    const fetcher =
      reportScope === 'mine'
        ? dailyReportApi.getMyYesterdayTracking
        : dailyReportApi.getYesterdayTracking;
    const timer = setTimeout(() => {
      fetcher(reportDate)
        .then(setYesterdayData)
        .catch(() => setYesterdayData(null));
    }, 800);
    return () => clearTimeout(timer);
  }, [reportScope]);

  const fetchReport = useCallback(async (date?: string) => {
    try {
      setLoading(true);
      setError(null);
      const data: DailyReportData = date
        ? ((reportScope === 'mine' ? await dailyReportApi.getMyByDate(date) : await dailyReportApi.getByDate(date)) as unknown as DailyReportData)
        : ((reportScope === 'mine' ? await dailyReportApi.getMyToday() : await dailyReportApi.getToday()) as unknown as DailyReportData);
      setReport(data);
      setSelectedDate(data.report_date);
      setYesterdayData(null);
      fetchYesterday(data.report_date);

      // 加载用户已标记的选题（恢复操作状态，刷新不丢失）
      // 标记键优先用 source_title（稳定）；历史日报无该字段时回退 title。
      try {
        const marksResp = await dailyReportApi.listPickMarks(data.report_date);
        setPickMarks(marksMapFromResp(marksResp.marks));
      } catch {
        // 静默失败（游客无 token 等），标记功能不可用不影响阅读
      }

      // 异步批量预加载所有选题的 sparkline 趋势（不阻塞主 UI）
      // sparkline 关键词从 source_title 提取（原文标题信号更纯）；无则回退 title。
      const topPicks = parseJson(data.top_picks) as Array<{ title: string; source_title?: string }> | null;
      if (topPicks && topPicks.length > 0) {
        const initial: Record<string, SparklineData> = {};
        for (const pick of topPicks) {
          const key = pick.source_title || pick.title;
          if (key) initial[key] = { points: [], keywords: [], total: 0, window_hours: 48 };
        }
        setSparklines(initial);
        await Promise.all(
          topPicks
            .map((pick) => pick.source_title || pick.title)
            .filter(Boolean)
            .map(async (key) => {
              try {
                const sp = await dailyReportApi.sparkline(key, 48, 2);
                setSparklines((prev) => ({ ...prev, [key]: sp }));
              } catch {
                // 静默失败：保持空点（组件会显示 "no data"）
              }
            }),
        );
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '加载失败';
      if (errMsg.includes('404') || errMsg.includes('not found')) {
        setReport(null);
        if (date) setSelectedDate(date);
        setError(date ? `${date} 暂无日报` : '暂无日报数据');
      } else {
        setError(errMsg);
      }
    } finally {
      setLoading(false);
    }
  }, [reportScope, fetchYesterday]);

  useEffect(() => {
    // 支持 /daily?date=YYYY-MM-DD 直达历史期（往期深链）；无参默认今天
    const params = new URLSearchParams(window.location.search);
    const dateParam = params.get('date');
    if (dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam) && dateParam <= localDateString()) {
      fetchReport(dateParam);
    } else {
      fetchReport();
    }
  }, [fetchReport]);

  const handleDateSelect = useCallback((date: string) => {
    if (date === selectedDate) return;
    fetchReport(date);
  }, [selectedDate, fetchReport]);

  const generateForDate = useCallback(async (date: string) => {
    const seq = ++generateSeqRef.current;
    try {
      setGenerating(true);
      setGeneratingDate(date);
      setError(null);
      const today = localDateString();
      // POST 返回 202（后台异步生成），不再等 LLM 完成
      await dailyReportApi.generateVersion({
        target_date: date,
        edition: date < today ? 'final' : 'manual',
        force: true,
      });
      // 轮询直到 DONE（最多 120 秒）
      const maxAttempts = 24;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 5000)); // 每 5 秒轮询
        if (seq !== generateSeqRef.current) return; // 已被新一轮生成/卸载取代，放弃旧轮询
        try {
          const data = date < today
            ? await dailyReportApi.getByDate(date)
            : await dailyReportApi.getToday();
          if (seq !== generateSeqRef.current) return;
          const reportData = data as unknown as DailyReportData;
          if (reportData.status === 'DONE' || reportData.status === 'ERROR') {
            setReport(reportData);
            setSelectedDate(reportData.report_date || date);
            if (reportData.status === 'ERROR') {
              setError(reportData.overview || '生成失败');
            }
            await refreshReportIndexes();
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
  }, [refreshReportIndexes]);

  const handleRegenerate = async () => {
    await generateForDate(report?.report_date || selectedDate || localDateString());
  };

  const handleMark = useCallback(
    async (pickTitle: string, action: 'write' | 'watch' | 'skip', category?: string, sourceUrl?: string) => {
      if (!report) return;
      // 记住标记前的状态，用于失败回滚（修掉原静默失败）
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
          await dailyReportApi.unmarkPick(report.report_date, pickTitle);
        } else {
          await dailyReportApi.markPick({
            report_date: report.report_date,
            pick_title: pickTitle,
            action,
            pick_category: category,
            pick_source_url: sourceUrl,
          });
        }
      } catch {
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
      }
    },
    [report, pickMarks],
  );

  const keywords = parseJson(report?.keywords);
  const trends = parseJson(report?.trends);
  const topPicks = parseJson(report?.top_picks);
  const platformTips = parseJson(report?.platform_tips);

  // todayStr 用 state 延迟到客户端渲染后计算，避免 SSR/CSR 跨天日期不一致导致 hydration mismatch。
  const [todayStr, setTodayStr] = useState('');
  useEffect(() => {
    setTodayStr(localDateString());
  }, []);
  const isToday = report?.report_date === todayStr;
  const generatedAt = formatDateTime(report?.generated_at || report?.updated_at);
  const keywordList = Array.isArray(keywords) ? keywords as string[] : [];
  const trendList = Array.isArray(trends) ? trends as Array<{ title: string; desc: string; color?: string; momentum?: string }> : [];
  const pickList = Array.isArray(topPicks)
    ? topPicks as DailyPick[]
    : [];
  const platformTipEntries = platformTips && typeof platformTips === 'object'
    ? Object.entries(platformTips as Record<string, unknown>)
    : [];
  const recoveryDate = report?.report_date || selectedDate || todayStr;
  const [expandedPick, setExpandedPick] = useState<number | null>(null);
  // 原文标题展示语言：默认中文翻译，可切换英文原文
  const [showOriginalLang, setShowOriginalLang] = useState(false);
  // 今日已选抽屉开关（一期补行动闭环）
  const [drawerOpen, setDrawerOpen] = useState(false);
  // 标记失败的轻量内联提示（修掉原 handleMark 静默失败）
  const [markError, setMarkError] = useState<string | null>(null);
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
  // 期号 = 已出刊日报天数（listDates 含今日）
  const issueNumber = useMemo(
    () => (datesLoading ? undefined : dates.length || undefined),
    [dates, datesLoading],
  );

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
    const others = dates.filter((d) => d.report_date !== report?.report_date);
    return others.slice(-5).reverse();
  }, [dates, report?.report_date]);

  return (
    <div className="h-full w-full overflow-hidden">
      {/* 工具栏：scope + 日期选择 */}
      <div className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-2">
        {/* scope 切换 */}
        <div className="flex items-center gap-1 text-[11px] font-black text-gray-500">
          <a
            href="/daily"
            className={cx("rounded px-2.5 py-1", reportScope === 'public' ? "bg-teal-light text-teal" : "text-gray-500 hover:text-gray-700")}
          >
            公共日报
          </a>
          <a
            href="/daily?scope=mine"
            className={cx("rounded px-2.5 py-1", reportScope === 'mine' ? "bg-teal-light text-teal" : "text-gray-500 hover:text-gray-700")}
          >
            我的日报
          </a>
          {/* 今日已选入口（一期补行动闭环）：点击打开抽屉 */}
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            disabled={writeCount === 0}
            className={cx(
              'ml-2 inline-flex items-center gap-1 rounded px-2 py-1 transition',
              writeCount > 0
                ? 'bg-primary-light text-primary hover:bg-primary/15'
                : 'text-gray-300',
            )}
            title={writeCount > 0 ? `今日已选 ${writeCount} 个选题` : '今日还未选选题'}
          >
            <ListChecks size={12} />
            <span className="tabular-nums">{writeCount}</span>
            <span className="hidden sm:inline">已选</span>
          </button>
          {markError && (
            <span className="text-[10px] font-bold text-red" title={markError}>
              ⚠
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 简洁日期选择器 */}
          <button
            type="button"
            onClick={() => {
              if (report) {
                const d = new Date(report.report_date);
                d.setDate(d.getDate() - 1);
                fetchReport(localDateString(d));
              }
            }}
            className="grid h-7 w-7 place-items-center rounded-xs border border-gray-200 text-gray-400 hover:text-gray-700"
            title="前一天"
          >
            <ChevronRight size={14} className="rotate-180" />
          </button>
          <span className="min-w-[100px] text-center text-xs font-bold text-gray-700">
            {report?.report_date || todayStr}
          </span>
          <button
            type="button"
            onClick={() => {
              if (report) {
                const d = new Date(report.report_date);
                d.setDate(d.getDate() + 1);
                if (localDateString(d) <= todayStr) fetchReport(localDateString(d));
              }
            }}
            disabled={isToday}
            className="grid h-7 w-7 place-items-center rounded-xs border border-gray-200 text-gray-400 hover:text-gray-700 disabled:opacity-30"
            title="后一天"
          >
            <ChevronRight size={14} />
          </button>
          <button
            type="button"
            onClick={() => fetchReport()}
            className={cx('ml-1 rounded-xs px-2 py-1 text-[11px] font-bold', isToday ? 'bg-primary text-white' : 'text-gray-500 hover:bg-gray-50')}
          >
            今天
          </button>

          {/* 管理入口（折叠隐藏的补录中心入口） */}
          {recoveryDays.length > 0 && (
            <span className="ml-2 rounded-full bg-amber-light px-2 py-0.5 text-[10px] font-bold text-amber" title={`${recoveryDays.length} 天待补录`}>
              {recoveryDays.length} 待补
            </span>
          )}
          {report && (
            <button
              type="button"
              onClick={handleRegenerate}
              disabled={generating}
              className="ml-1 flex items-center gap-1 rounded-xs border border-gray-200 px-2 py-1 text-[11px] font-bold text-gray-500 hover:text-primary disabled:opacity-50"
            >
              {generating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              刷新
            </button>
          )}
          {report?.status === 'DONE' && isAdmin(currentUser) && (
            <button
              type="button"
              onClick={handlePushWebhook}
              disabled={pushing}
              title="将当前日报推送到已配置的飞书/钉钉/Slack 群机器人"
              className="ml-1 flex items-center gap-1 rounded-xs border border-gray-200 px-2 py-1 text-[11px] font-bold text-gray-500 hover:text-primary disabled:opacity-50"
            >
              {pushing ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
              {pushing ? '推送中…' : '推送到群'}
            </button>
          )}
          {pushMsg && (
            <span className={cx('ml-1 text-[10px] font-bold', pushMsg.includes('失败') || pushMsg.includes('未配置') ? 'text-red' : 'text-teal')}>
              {pushMsg}
            </span>
          )}
        </div>
      </div>

      {/* 主区域（晨报版式：报头 → 导语 → 头版 → 内页分版） */}
      <div className="h-[calc(100%-40px)] overflow-y-auto bg-[linear-gradient(180deg,#F8FAFC_0%,#F4F6F8_44%,#EEF2F5_100%)]">
        <div className="mx-auto max-w-[920px] px-4 py-4 sm:px-6">
          {loading ? (
            <ReportStatusPanel icon={FileText}>正在加载日报...</ReportStatusPanel>
          ) : error ? (
            <ReportStatusPanel
              icon={AlertTriangle}
              tone="error"
              action={(
                <ReportActionButton
                  onClick={() => generateForDate(recoveryDate)}
                  loading={generating && generatingDate === recoveryDate}
                  icon={RotateCcw}
                >
                  生成 {recoveryDate}
                </ReportActionButton>
              )}
            >
              {error}
            </ReportStatusPanel>
          ) : report?.status === 'ERROR' ? (
            <div className="grid min-h-[300px] place-items-center p-8 text-center">
              <div>
                <AlertTriangle size={28} className="mx-auto mb-3 text-red" strokeWidth={1.9} />
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
            <div className="space-y-0">
              {/* 报头（刊名/日期行/统计行：期号·昨日兑现·长度合同） */}
              <div className="bg-white">
                <Masthead
                  reportDate={report.report_date}
                  weekday={report.weekday}
                  editionLabel={report.edition ? SNAPSHOT_EDITION_LABELS[report.edition] : undefined}
                  issueNumber={issueNumber}
                  generatedAt={generatedAt || undefined}
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
                <summary className="cursor-pointer px-5 py-2 text-[11px] font-bold text-gray-400 hover:text-gray-600">
                  昨日追踪明细（24h 热度与兑现）
                </summary>
                <div className="px-5 pb-3">
                  <YesterdayTracking scope={reportScope} reportDate={report.report_date} />
                </div>
              </details>

              {/* 内页分版：速览（brief 档按分类分版） */}
              {hasBrief && (
                <div className="mt-4">
                  <div className="mb-2 flex flex-wrap items-center gap-2 px-1">
                    <span className="font-mono text-lg font-black text-gray-400">→</span>
                    <h2 className="text-sm font-black text-gray-700">速览 · 分版</h2>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-500">
                      {briefGroups.reduce((n, [, ps]) => n + ps.length, 0)} 篇
                    </span>
                  </div>
                  {briefGroups.map(([cat, picks], groupIdx) => (
                    <div key={`brief-group-${cat}`} className="mb-3">
                      <div className="mb-1.5 flex items-center gap-2 px-1">
                        <span className="font-mono text-[13px] font-black text-gray-300">
                          {String(groupIdx + 1).padStart(2, '0')}
                        </span>
                        <span className="text-[12px] font-black text-gray-600">{cat}</span>
                        {CATEGORY_EN[cat] && (
                          <span className="text-[10px] font-bold text-gray-300">{CATEGORY_EN[cat]}</span>
                        )}
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-400">{picks.length} 篇</span>
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
                          <div key={`${platform}-${j}`} className="mb-1.5 border-l-2 border-primary-border pl-2.5 text-[12px] leading-5 text-gray-500">
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
                  <div className="mb-2 text-[10px] font-black tracking-widest text-gray-400">往期 · 每天一格</div>
                  <div className="flex flex-wrap gap-2">
                    {recentDates.map((d) => (
                      <button
                        key={d.report_date}
                        type="button"
                        onClick={() => handleDateSelect(d.report_date)}
                        className="flex min-w-[170px] flex-1 flex-col gap-0.5 rounded-xs border border-gray-200 px-3 py-2 text-left hover:border-primary"
                        title={d.takeaway || undefined}
                      >
                        <span className="font-mono text-[10px] font-bold text-gray-400">{d.report_date} {d.weekday}</span>
                        <span className="truncate text-[11.5px] font-bold text-gray-700">
                          {d.takeaway || '查看当日日报'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 底部统计 + 报脚 */}
              <div className="mt-4 flex flex-wrap gap-4 border-t border-gray-200 pt-3 text-[11px] text-gray-400">
                <ReportFooterStat icon={BarChart3}>分析 {report.analyzed_count || 0} 条</ReportFooterStat>
                <ReportFooterStat icon={Target}>推荐 {pickList.length} 个选题</ReportFooterStat>
                {generatedAt && <ReportFooterStat icon={CalendarDays}>{generatedAt}</ReportFooterStat>}
              </div>
              <footer className="mt-2 border-t border-gray-200 py-2.5 text-center text-[10px] tracking-wide text-gray-400">
                版面编辑：TopicEye 编辑台 · 热点不认行业，角度认赛道 · 每条可溯原文{issueNumber ? ` · 总第 ${issueNumber} 期` : ''}
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
