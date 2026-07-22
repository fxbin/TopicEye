'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Circle,
  ExternalLink,
  FileText,
  Inbox,
  KeyRound,
  Lightbulb,
  ListChecks,
  Loader2,
  Newspaper,
  Pin,
  RefreshCw,
  RotateCcw,
  Smartphone,
  Target,
  TrendingUp,
} from 'lucide-react';
import { Panel, cx } from '@/components/ui';
import { ReaderDrawer } from '@/components/ReaderDrawer';
import { dailyReportApi } from '@/lib/api';
import YesterdayTracking from './_yesterday-tracking';
import SelectedDrawer from './_selected-drawer';
import Sparkline, { SparklineData } from '@/components/Sparkline';
import { AutoLink } from '@/components/AutoLink';
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

interface DailyReportData {
  id: number;
  report_date: string;
  weekday: string;
  edition?: string;
  generated_at?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  cutoff_at?: string | null;
  source_scope?: string;
  source_item_ids?: number[] | null;
  updated_at?: string | null;
  overview: string | null;
  takeaway: string | null;
  keywords: string[] | null;
  trends: Array<{ title: string; desc: string; color: string; momentum?: string }> | null;
  top_picks: Array<{
    title: string;
    reason: string;
    score: number;
    platforms: string[];
    source_url?: string;
    angles?: string[];
    pitfall?: string;
    lifecycle?: string;
    time_window?: string;
    category?: string;
    source_idx?: number;
    source_title?: string;
    source_title_zh?: string;
    editorial_title?: string;
    tier?: 'feature' | 'brief';
    content_id?: number;
  }> | null;
  platform_tips: Record<string, string[]> | null;
  topic_count: number;
  content_count: number;
  analyzed_count: number;
  status: string;
}

interface DateSummary {
  report_date: string;
  weekday: string;
  takeaway: string | null;
  status: string;
  edition?: string;
  generated_at?: string | null;
  cutoff_at?: string | null;
}

interface CalendarDay {
  report_date: string;
  weekday: string;
  status: string;
  edition: string | null;
  generated_at: string | null;
  cutoff_at: string | null;
  takeaway: string | null;
  content_count: number;
  analyzed_count: number;
  topic_count: number;
  has_report: boolean;
  can_generate: boolean;
  is_today: boolean;
}

const EDITION_LABELS: Record<string, string> = {
  noon: '午间快照',
  evening: '晚间快照',
  snapshot: '实时快照',
  manual: '手动快照',
  final: '完整复盘',
  legacy: '历史日报',
};

const CALENDAR_STATUS_META: Record<string, { label: string; text: string; bg: string; border: string; active: string }> = {
  DONE: { label: '已完成', text: 'text-teal', bg: 'bg-teal-light', border: 'border-teal-border', active: 'bg-teal text-white border-teal' },
  ERROR: { label: '失败', text: 'text-red', bg: 'bg-red-light', border: 'border-red-light', active: 'bg-red text-white border-red' },
  MISSING: { label: '缺失', text: 'text-amber', bg: 'bg-amber-light', border: 'border-amber-border', active: 'bg-amber text-white border-amber' },
  GENERATING: { label: '生成中', text: 'text-primary', bg: 'bg-primary-light', border: 'border-primary-border', active: 'bg-primary text-white border-primary' },
};

function localDateString(date = new Date()) {
  return date.toLocaleDateString('en-CA');
}

function formatDateTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace('T', ' ');
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatTimeOnly(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 16);
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function parseJson(val: unknown) {
  if (typeof val === 'string') {
    try {
      return JSON.parse(val);
    } catch {
      return null;
    }
  }
  return val;
}

/**
 * 选题稳定键：优先 source_title（原文标题，跨版本稳定），无则回退 title。
 * 用于 sparkline 关键词查询、PickMark 标记 —— 这两处依赖标题，观点化标题每次生成都变会导致标记/趋势丢失。
 */
function pickKey(pick: { source_title?: string; title?: string }): string {
  return pick.source_title || pick.title || '';
}

/**
 * 判断原文标题是否主要为英文（含 CJK 字符少、Latin 字母多）。
 * 用于决定是否展示"中/英"切换按钮。
 */
function isEnglishTitle(title?: string): boolean {
  if (!title) return false;
  const cjk = (title.match(/[\u4e00-\u9fff]/g) || []).length;
  const latin = (title.match(/[a-zA-Z]/g) || []).length;
  return latin > 0 && cjk < latin * 0.3;
}

/**
 * 返回展示用的原文标题：默认中文翻译，可切换英文原文。
 * - showOriginal=true → 英文原文
 * - showOriginal=false → 中文翻译（无翻译时回退原文）
 */
function displaySourceTitle(pick: { source_title?: string; source_title_zh?: string }, showOriginal: boolean): string {
  if (showOriginal) return pick.source_title || '';
  return pick.source_title_zh || pick.source_title || '';
}

type MarkAction = 'write' | 'watch' | 'skip';
function marksMapFromResp(marks: Array<{ pick_title: string; action: string }>): Record<string, MarkAction> {
  const map: Record<string, MarkAction> = {};
  for (const m of marks) {
    map[m.pick_title] = m.action as MarkAction;
  }
  return map;
}

function StatBox({ label, value, tone = 'neutral' }: { label: string; value: React.ReactNode; tone?: 'primary' | 'red' | 'neutral' }) {
  return (
    <div className={cx(
      'rounded-sm border px-3 py-2.5',
      tone === 'primary' && 'border-primary-border bg-primary-light',
      tone === 'red' && 'border-red-light bg-red-light',
      tone === 'neutral' && 'border-gray-200 bg-gray-50',
    )}>
      <div className="mb-1 text-[10px] text-gray-500">{label}</div>
      <div className={cx(
        'font-mono text-xl font-black',
        tone === 'primary' && 'text-primary',
        tone === 'red' && 'text-red',
        tone === 'neutral' && 'text-gray-900',
      )}>
        {value}
      </div>
    </div>
  );
}

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

  const fetchReport = useCallback(async (date?: string) => {
    try {
      setLoading(true);
      setError(null);
      const data: DailyReportData = date
        ? ((reportScope === 'mine' ? await dailyReportApi.getMyByDate(date) : await dailyReportApi.getByDate(date)) as unknown as DailyReportData)
        : ((reportScope === 'mine' ? await dailyReportApi.getMyToday() : await dailyReportApi.getToday()) as unknown as DailyReportData);
      setReport(data);
      setSelectedDate(data.report_date);

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
  }, [reportScope]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  // T2: 当 scope 切换时刷新主报告
  useEffect(() => {
    fetchReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportScope]);

  const handleDateSelect = useCallback((date: string) => {
    if (date === selectedDate) return;
    fetchReport(date);
  }, [selectedDate, fetchReport]);

  const generateForDate = useCallback(async (date: string) => {
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
        try {
          const data = date < today
            ? await dailyReportApi.getByDate(date)
            : await dailyReportApi.getToday();
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
      setError('生成超时，请稍后刷新查看');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setGenerating(false);
      setGeneratingDate(null);
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

  const handleCalendarDayClick = (day: CalendarDay) => {
    setSelectedDate(day.report_date);
    if (day.has_report) {
      fetchReport(day.report_date);
      return;
    }
    setReport(null);
    setError(`${day.report_date} 暂无日报，可手动补生成`);
  };

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
    ? topPicks as Array<{
      title: string; reason: string; score?: number; platforms?: string[];
      source_url?: string; angles?: string[]; pitfall?: string;
      lifecycle?: string; time_window?: string; category?: string;
      source_idx?: number; source_title?: string; source_title_zh?: string; editorial_title?: string;
      tier?: 'feature' | 'brief'; content_id?: number;
    }>
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
  // 站内阅读：点选题卡片标题旁的 BookOpen 打开 ReaderDrawer（与 today-picks 一致）
  const [readerContentId, setReaderContentId] = useState<number | null>(null);
  // 今日「已选」标记数（action=write），用于工具栏 badge
  const writeCount = useMemo(
    () => Object.values(pickMarks).filter((a) => a === 'write').length,
    [pickMarks],
  );


  const LIFECYCLE_META: Record<string, { label: string; color: string; bg: string }> = {
    '上升期': { label: '↑ 上升期', color: 'text-teal', bg: 'bg-teal-light' },
    '见顶': { label: '→ 见顶', color: 'text-amber', bg: 'bg-amber-light' },
    '退潮': { label: '↓ 退潮', color: 'text-gray-400', bg: 'bg-gray-100' },
  };

  const generatedDates = useMemo(() => dates.filter((d) => d.report_date !== todayStr), [dates, todayStr]);
  const recoveryDays = calendarDays.filter((day) => day.status === 'MISSING' || day.status === 'ERROR');

  // 选题按 category 分组（无 category 的归到"精选选题"）
  const CATEGORY_ORDER = ['模型发布', '产品更新', '行业动态', '技巧观点', '科研论文', '开源项目'];
  const CATEGORY_EN: Record<string, string> = {
    '模型发布': 'Model Releases',
    '产品更新': 'Product Updates',
    '行业动态': 'Industry',
    '技巧观点': 'Tips & Takes',
    '科研论文': 'Research',
    '开源项目': 'Open Source',
  };
  // 按 tier 分区，区内再按 category 分组。feature 优先展示（深度精讲），brief 次之（速览）。
  // 兼容历史数据：无 tier 字段视为 feature。
  const featureGroups = useMemo(() => {
    const groups: Record<string, typeof pickList> = {};
    for (const pick of pickList) {
      if (pick.tier && pick.tier !== 'feature') continue;
      const cat = pick.category || '精选选题';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(pick);
    }
    return Object.entries(groups).sort(([a], [b]) => {
      const ia = CATEGORY_ORDER.indexOf(a);
      const ib = CATEGORY_ORDER.indexOf(b);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
  }, [pickList]);
  const briefGroups = useMemo(() => {
    const groups: Record<string, typeof pickList> = {};
    for (const pick of pickList) {
      if (pick.tier !== 'brief') continue;
      const cat = pick.category || '精选选题';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(pick);
    }
    return Object.entries(groups).sort(([a], [b]) => {
      const ia = CATEGORY_ORDER.indexOf(a);
      const ib = CATEGORY_ORDER.indexOf(b);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
  }, [pickList]);
  const hasBrief = briefGroups.length > 0;
  const readMinutes = Math.max(1, Math.ceil(pickList.length * 0.8));

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
          {/* 简洁日期选择器（替代 30 天日历） */}
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
        </div>
      </div>

      {/* 主区域 */}
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
            <div className="space-y-3">
              {/* 主编判断：先给出日报主线，再进入分层选题。 */}
              <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2 text-[11px] font-black text-gray-400">
                      <span>{report.report_date} {report.weekday}</span>
                      {/* 版本标签（复活死代码 EDITION_LABELS，区分午间快照/完整复盘） */}
                      {report.edition && EDITION_LABELS[report.edition] && (
                        <span className="rounded-xs border border-primary-border bg-primary-light px-1.5 py-0.5 text-[10px] font-bold text-primary">
                          {EDITION_LABELS[report.edition]}
                        </span>
                      )}
                      {generatedAt && <span>· 更新于 {generatedAt}</span>}
                      <span>· {pickList.length} 个选题 · 约 {readMinutes} 分钟</span>
                    </div>
                    <p className="text-sm font-bold leading-6 text-gray-800">
                      {report.takeaway || report.overview?.slice(0, 80) || '今日内容已完成分析。'}
                    </p>
                    {report.overview && (
                      <div className="mt-2.5 border-l-2 border-primary pl-3 text-[13px] leading-6 text-gray-600">
                        <span className="mr-1.5 text-[11px] font-black text-primary">主编判断</span>
                        {report.overview}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* 昨日追踪卡（一期补连续性闭环）：昨日 top picks 的 24h 热度 delta + lifecycle 验证 */}
              <YesterdayTracking scope={reportScope} reportDate={report.report_date} />

              {/* 今日看点 TOC（可点击跳转，仅深度精讲） */}
              {featureGroups.length > 1 && (
                <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
                  <div className="mb-2 text-[11px] font-black text-gray-400">今日看点</div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                    {featureGroups.map(([cat, picks]) => (
                      <a
                        key={`toc-${cat}`}
                        href={`#cat-${cat}`}
                        className="flex items-center gap-1.5 text-[12px] font-bold text-gray-500 hover:text-primary"
                      >
                        <span className="text-primary">{picks.length}</span>
                        <span>{cat}</span>
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* 深度精讲（feature：全字段卡片） */}
              {featureGroups.length > 0 && (
                <div className="space-y-4">
                  {featureGroups.map(([cat, picks], groupIdx) => (
                    <div key={`group-${cat}`} id={`cat-${cat}`}>
                      {/* 分组标题 */}
                      <div className="mb-2 flex items-center gap-2 px-1">
                      <span className="font-mono text-lg font-black text-primary">
                        {String(groupIdx + 1).padStart(2, '0')}
                      </span>
                      <h2 className="text-sm font-black text-gray-900">{cat}</h2>
                      {CATEGORY_EN[cat] && (
                        <span className="text-[11px] font-bold text-gray-300">{CATEGORY_EN[cat]}</span>
                      )}
                      <span className="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-500">{picks.length} 篇</span>
                    </div>

                    {/* 组内选题列表 */}
                    <div className="space-y-2">
                      {picks.map((pick, j) => {
                        const globalIdx = pickList.indexOf(pick);
                        const isExpanded = expandedPick === globalIdx;
                        const lc = pick.lifecycle ? LIFECYCLE_META[pick.lifecycle] || LIFECYCLE_META['上升期'] : null;
                        const key = pickKey(pick);
                        return (
                          <div
                            key={`pick-${cat}-${j}`}
                            className={cx(
                              'rounded-lg border bg-white shadow-sm transition',
                              isExpanded ? 'border-primary-border shadow-md' : 'border-gray-200',
                            )}
                          >
                            {/* 选题一行摘要（可扫描层）*/}
                            <div
                              role="button"
                              tabIndex={0}
                              onClick={() => setExpandedPick(isExpanded ? null : globalIdx)}
                              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpandedPick(isExpanded ? null : globalIdx); } }}
                              className="flex w-full cursor-pointer items-start gap-3 p-3 text-left sm:p-4"
                            >
                              {/* 评分 */}
                              <div className="flex shrink-0 flex-col items-center gap-0.5">
                                <div className={cx(
                                  'grid h-11 w-11 place-items-center rounded-lg font-mono text-lg font-black',
                                  globalIdx === 0 ? 'bg-primary text-white' : 'bg-gray-100 text-gray-600',
                                )}>
                                  {pick.score ? (typeof pick.score === 'number' ? pick.score : parseFloat(String(pick.score)) || '-') : '-'}
                                </div>
                              </div>

                              {/* 标题 + 元数据 */}
                              <div className="min-w-0 flex-1">
                                <div className="flex items-start gap-2">
                                  <h3 className="min-w-0 flex-1 break-words text-sm font-bold leading-6 text-gray-900 sm:text-[15px]">{pick.title}</h3>
                                  {/* 站内阅读：有 content_id 时点开 ReaderDrawer；历史数据无 content_id 回退外链 */}
                                  {pick.content_id ? (
                                    <button
                                      type="button"
                                      onClick={(e) => { e.stopPropagation(); setReaderContentId(pick.content_id!); }}
                                      className="mt-0.5 shrink-0 text-gray-300 hover:text-primary"
                                      title="站内阅读"
                                    >
                                      <BookOpen size={14} />
                                    </button>
                                  ) : pick.source_url && (
                                    <a
                                      href={pick.source_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => e.stopPropagation()}
                                      className="mt-0.5 shrink-0 text-gray-300 hover:text-primary"
                                      title="查看原文"
                                    >
                                      <ExternalLink size={14} />
                                    </a>
                                  )}
                                </div>
                                {/* 原文标题（默认中文翻译，可切换英文原文） */}
                                {pick.source_title && pick.source_title !== pick.title && (
                                  <div className="mt-0.5 flex items-center gap-1 text-[11px] text-gray-400">
                                    <span className="truncate">原文：<AutoLink text={displaySourceTitle(pick, showOriginalLang)} className="text-gray-400 underline-offset-2 hover:underline" /></span>
                                    {isEnglishTitle(pick.source_title) && pick.source_title_zh && (
                                      <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); setShowOriginalLang(!showOriginalLang); }}
                                        className="shrink-0 rounded border border-gray-200 px-1 text-[10px] text-gray-400 hover:text-gray-600"
                                      >
                                        {showOriginalLang ? '中' : 'EN'}
                                      </button>
                                    )}
                                  </div>
                                )}
                                {/* 元数据行：lifecycle + 平台 + 时窗（不挤 sparkline） */}
                                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                  {lc && (
                                    <span className={cx('rounded-full px-2 py-0.5 text-[10px] font-bold', lc.bg, lc.color)}>
                                      {lc.label}
                                    </span>
                                  )}
                                  {(pick.platforms ?? []).slice(0, 3).map((p, k) => (
                                    <span key={`${p}-${k}`} className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] text-gray-500">
                                      {p}
                                    </span>
                                  ))}
                                  {pick.time_window && (
                                    <span className="text-[10px] text-gray-400">· {pick.time_window}</span>
                                  )}
                                </div>
                                {/* 24h 内容热度趋势 sparkline 独立一行（"内容热度"非"流量热度"） */}
                                <div className="mt-1.5 flex justify-end">
                                  <Sparkline
                                    data={sparklines[key]}
                                    loading={!sparklines[key]?.points}
                                  />
                                </div>
                              </div>

                              {/* 展开指示 */}
                              <div className={cx('mt-1 shrink-0 text-gray-300 transition', isExpanded && 'rotate-90')}>
                                <ChevronRight size={16} />
                              </div>
                              </div>

                            {/* 展开后的决策卡 */}
                            {isExpanded && (
                              <div className="border-t border-gray-100 px-3 pb-3 pt-2 sm:px-4">
                                {/* 原文标题（展开态补回，让创作者决定写不写时能核对原文） */}
                                {pick.source_title && pick.source_title !== pick.title && (
                                  <div className="mb-2 flex items-center gap-1 text-[11px] text-gray-400">
                                    <span className="break-all">原文：<AutoLink text={displaySourceTitle(pick, showOriginalLang)} className="text-gray-400 underline-offset-2 hover:underline" /></span>
                                    {isEnglishTitle(pick.source_title) && pick.source_title_zh && (
                                      <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); setShowOriginalLang(!showOriginalLang); }}
                                        className="shrink-0 rounded border border-gray-200 px-1 text-[10px] text-gray-400 hover:text-gray-600"
                                      >
                                        {showOriginalLang ? '中' : 'EN'}
                                      </button>
                                    )}
                                  </div>
                                )}
                                {/* 推荐理由 */}
                                <div className="mb-3 text-[13px] leading-6 text-gray-600"><AutoLink text={pick.reason} /></div>

                                {/* 创作角度 */}
                                {pick.angles && pick.angles.length > 0 && (
                                  <div className="mb-3">
                                    <div className="mb-1.5 flex items-center gap-1 text-[11px] font-black text-gray-500">
                                      <Lightbulb size={12} className="text-primary" /> 推荐角度
                                    </div>
                                    <div className="flex flex-wrap gap-1.5">
                                      {pick.angles.map((angle, k) => (
                                        <span key={`angle-${k}`} className="rounded-md border border-primary-border bg-primary-light px-2.5 py-1 text-[12px] font-medium text-gray-700">
                                          {angle}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* 避坑提示 */}
                                {pick.pitfall && (
                                  <div className="mb-3 flex items-start gap-2 rounded-md bg-amber-light px-3 py-2">
                                    <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber" />
                                    <span className="text-[12px] leading-5 text-gray-600"><AutoLink text={pick.pitfall} /></span>
                                  </div>
                                )}

                                {/* 操作按钮 */}
                                <div className="flex items-center gap-2">
                                  <a
                                    href={`/plan?title=${encodeURIComponent(displaySourceTitle(pick, false))}${pick.source_url ? `&url=${encodeURIComponent(pick.source_url)}` : ''}`}
                                    className="flex items-center gap-1 rounded-md bg-primary px-4 py-2 text-xs font-bold text-white hover:opacity-90"
                                  >
                                    <FileText size={13} /> 写这个
                                  </a>
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); handleMark(key, 'write', pick.category, pick.source_url); }}
                                    className={cx(
                                      'flex items-center gap-1 rounded-md border px-3 py-2 text-xs font-bold transition',
                                      pickMarks[key] === 'write'
                                        ? 'border-primary bg-primary-light text-primary'
                                        : 'border-gray-200 text-gray-500 hover:text-gray-700',
                                    )}
                                  >
                                    <CheckCircle2 size={13} /> 已选
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); handleMark(key, 'watch', pick.category, pick.source_url); }}
                                    className={cx(
                                      'flex items-center gap-1 rounded-md border px-3 py-2 text-xs font-bold transition',
                                      pickMarks[key] === 'watch'
                                        ? 'border-amber bg-amber-light text-amber'
                                        : 'border-gray-200 text-gray-500 hover:text-gray-700',
                                    )}
                                  >
                                    <Inbox size={13} /> 观察
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); handleMark(key, 'skip', pick.category, pick.source_url); }}
                                    className={cx(
                                      'flex items-center gap-1 rounded-md border px-3 py-2 text-xs font-bold transition',
                                      pickMarks[key] === 'skip'
                                        ? 'border-gray-400 bg-gray-100 text-gray-500'
                                        : 'border-gray-200 text-gray-400 hover:text-gray-600',
                                    )}
                                  >
                                    跳过
                                  </button>
                                  {/* 去原站（次要入口）：标题已主推站内阅读，此处保留外链给需要看原页面的场景 */}
                                  {pick.source_url && (
                                    <a
                                      href={pick.source_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => e.stopPropagation()}
                                      className="ml-auto flex items-center gap-1 text-[11px] font-bold text-gray-400 hover:text-primary"
                                      title="在新标签打开原文站点"
                                    >
                                      <ExternalLink size={12} /> 去原站
                                    </a>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  ))}
                </div>
              )}
              {hasBrief && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 px-1">
                    <span className="font-mono text-lg font-black text-gray-400">→</span>
                    <h2 className="text-sm font-black text-gray-700">速览</h2>
                    <span className="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-500">
                      {briefGroups.reduce((n, [, ps]) => n + ps.length, 0)} 篇
                    </span>
                  </div>
                  <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white shadow-sm">
                    {briefGroups.map(([cat, picks]) => (
                      picks.map((pick, j) => {
                        const globalIdx = pickList.indexOf(pick);
                        const isExpanded = expandedPick === globalIdx;
                        const key = pickKey(pick);
                        return (
                          <div key={`brief-${cat}-${j}`}>
                            <div
                              role="button"
                              tabIndex={0}
                              onClick={() => setExpandedPick(isExpanded ? null : globalIdx)}
                              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpandedPick(isExpanded ? null : globalIdx); } }}
                              className="flex w-full cursor-pointer items-start gap-2.5 px-3 py-2.5 text-left sm:px-4"
                            >
                              <span className="mt-0.5 shrink-0 font-mono text-[11px] font-bold text-gray-300">{String(globalIdx + 1).padStart(2, '0')}</span>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-start gap-2">
                                  <h3 className="min-w-0 flex-1 break-words text-[13px] font-bold leading-5 text-gray-800">{pick.title}</h3>
                                  {/* 站内阅读：有 content_id 时点开 ReaderDrawer；历史数据无 content_id 回退外链 */}
                                  {pick.content_id ? (
                                    <button
                                      type="button"
                                      onClick={(e) => { e.stopPropagation(); setReaderContentId(pick.content_id!); }}
                                      className="mt-0.5 shrink-0 text-gray-300 hover:text-primary"
                                      title="站内阅读"
                                    >
                                      <BookOpen size={13} />
                                    </button>
                                  ) : pick.source_url && (
                                    <a
                                      href={pick.source_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => e.stopPropagation()}
                                      className="mt-0.5 shrink-0 text-gray-300 hover:text-primary"
                                      title="查看原文"
                                    >
                                      <ExternalLink size={13} />
                                    </a>
                                  )}
                                </div>
                                <div className="mt-0.5 text-[11px] text-gray-500"><AutoLink text={pick.reason} /></div>
                                {/* 原文标题（英文时默认中文翻译，可切换） */}
                                {pick.source_title && pick.source_title !== pick.title && isEnglishTitle(pick.source_title) && (
                                  <div className="mt-0.5 flex items-center gap-1 text-[10px] text-gray-400">
                                    <span className="truncate">原文：<AutoLink text={displaySourceTitle(pick, showOriginalLang)} className="text-gray-400 underline-offset-2 hover:underline" /></span>
                                    {pick.source_title_zh && (
                                      <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); setShowOriginalLang(!showOriginalLang); }}
                                        className="shrink-0 rounded border border-gray-200 px-1 text-[9px] text-gray-400 hover:text-gray-600"
                                      >
                                        {showOriginalLang ? '中' : 'EN'}
                                      </button>
                                    )}
                                  </div>
                                )}
                                {(pick.platforms ?? []).length > 0 && (
                                  <div className="mt-1 flex flex-wrap items-center gap-1">
                                    {(pick.platforms ?? []).slice(0, 3).map((p, k) => (
                                      <span key={`${p}-${k}`} className="rounded-full border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-400">{p}</span>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <div className={cx('mt-0.5 shrink-0 text-gray-300 transition', isExpanded && 'rotate-90')}>
                                <ChevronRight size={14} />
                              </div>
                            </div>
                            {isExpanded && (
                              <div className="flex items-center gap-2 border-t border-gray-100 px-3 py-2 sm:px-4">
                                <a
                                  href={`/plan?title=${encodeURIComponent(displaySourceTitle(pick, false))}${pick.source_url ? `&url=${encodeURIComponent(pick.source_url)}` : ''}`}
                                  className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-[11px] font-bold text-white hover:opacity-90"
                                >
                                  <FileText size={12} /> 写这个
                                </a>
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); handleMark(key, 'write', pick.category, pick.source_url); }}
                                  className={cx(
                                    'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold transition',
                                    pickMarks[key] === 'write'
                                      ? 'border-primary bg-primary-light text-primary'
                                      : 'border-gray-200 text-gray-500 hover:text-gray-700',
                                  )}
                                >
                                  <CheckCircle2 size={12} /> 已选
                                </button>
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); handleMark(key, 'watch', pick.category, pick.source_url); }}
                                  className={cx(
                                    'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold transition',
                                    pickMarks[key] === 'watch'
                                      ? 'border-amber bg-amber-light text-amber'
                                      : 'border-gray-200 text-gray-500 hover:text-gray-700',
                                  )}
                                >
                                  <Inbox size={12} /> 观察
                                </button>
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); handleMark(key, 'skip', pick.category, pick.source_url); }}
                                  className={cx(
                                    'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold transition',
                                    pickMarks[key] === 'skip'
                                      ? 'border-gray-400 bg-gray-100 text-gray-500'
                                      : 'border-gray-200 text-gray-400 hover:text-gray-600',
                                  )}
                                >
                                  跳过
                                </button>
                              </div>
                            )}
                          </div>
                        );
                      })
                    ))}
                  </div>
                </div>
              )}

              {/* 背景层：趋势 + 关键词 + 平台建议 */}
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {/* 趋势 */}
                {trendList.length > 0 && (
                  <Panel className="p-4">
                    <ReportSectionTitle icon={TrendingUp} title="趋势信号" />
                    <div className="space-y-2">
                      {trendList.map((trend, i) => (
                        <div key={`trend-${i}`} className="flex items-start gap-2">
                          <span className={cx(
                            'mt-0.5 shrink-0 text-[11px] font-black',
                            trend.momentum === 'up' ? 'text-teal' : trend.momentum === 'down' ? 'text-gray-400' : 'text-amber',
                          )}>
                            {trend.momentum === 'up' ? '↑' : trend.momentum === 'down' ? '↓' : '→'}
                          </span>
                          <div className="min-w-0">
                            <span className="text-[13px] font-bold text-gray-800">{trend.title}</span>
                            <span className="ml-1.5 text-[11px] text-gray-400">{trend.desc}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Panel>
                )}

                {/* 关键词 */}
                {keywordList.length > 0 && (
                  <Panel className="p-4">
                    <ReportSectionTitle icon={KeyRound} title="高频关键词" />
                    <div className="flex flex-wrap gap-1.5">
                      {keywordList.map((kw, i) => (
                        <span
                          key={`kw-${i}`}
                          className={cx(
                            'rounded-full border px-2.5 py-1 text-xs font-bold',
                            i === 0 ? 'border-primary-border bg-primary-light text-gray-700' : 'border-gray-200 bg-gray-50 text-gray-600',
                          )}
                        >
                          {kw}
                        </span>
                      ))}
                    </div>
                  </Panel>
                )}
              </div>

              {/* 平台建议（折叠态） */}
              {platformTipEntries.length > 0 && (
                <details className="rounded-lg border border-gray-200 bg-white">
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

              {/* 底部统计 */}
              <div className="flex flex-wrap gap-4 border-t border-gray-200 pt-3 text-[11px] text-gray-400">
                <ReportFooterStat icon={BarChart3}>分析 {report.analyzed_count || 0} 条</ReportFooterStat>
                <ReportFooterStat icon={Target}>推荐 {pickList.length} 个选题</ReportFooterStat>
                {generatedAt && <ReportFooterStat icon={CalendarDays}>{generatedAt}</ReportFooterStat>}
              </div>
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

      {/* 站内阅读抽屉：复用 ReaderDrawer，按 content_id 取正文（与 today-picks 一致） */}
      <ReaderDrawer contentId={readerContentId} onClose={() => setReaderContentId(null)} />
    </div>
  );
}
