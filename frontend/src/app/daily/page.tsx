'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Circle,
  ExternalLink,
  FileText,
  Inbox,
  KeyRound,
  Lightbulb,
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
import { dailyReportApi } from '@/lib/api';
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

  const fetchReport = useCallback(async (date?: string) => {
    try {
      setLoading(true);
      setError(null);
      const data: DailyReportData = date
        ? ((reportScope === 'mine' ? await dailyReportApi.getMyByDate(date) : await dailyReportApi.getByDate(date)) as unknown as DailyReportData)
        : ((reportScope === 'mine' ? await dailyReportApi.getMyToday() : await dailyReportApi.getToday()) as unknown as DailyReportData);
      setReport(data);
      setSelectedDate(data.report_date);
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
      const data = await dailyReportApi.generateVersion({
        target_date: date,
        edition: date < today ? 'final' : 'manual',
        force: true,
      });
      setReport(data as unknown as DailyReportData);
      setSelectedDate((data as unknown as DailyReportData).report_date || date);
      await refreshReportIndexes();
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

  const todayStr = localDateString();
  const isToday = report?.report_date === todayStr;
  const generatedAt = formatDateTime(report?.generated_at || report?.updated_at);
  const keywordList = Array.isArray(keywords) ? keywords as string[] : [];
  const trendList = Array.isArray(trends) ? trends as Array<{ title: string; desc: string; color?: string; momentum?: string }> : [];
  const pickList = Array.isArray(topPicks)
    ? topPicks as Array<{
      title: string; reason: string; score?: number; platforms?: string[];
      source_url?: string; angles?: string[]; pitfall?: string;
      lifecycle?: string; time_window?: string;
    }>
    : [];
  const platformTipEntries = platformTips && typeof platformTips === 'object'
    ? Object.entries(platformTips as Record<string, unknown>)
    : [];
  const recoveryDate = report?.report_date || selectedDate || todayStr;
  const [expandedPick, setExpandedPick] = useState<number | null>(0);

  const LIFECYCLE_META: Record<string, { label: string; color: string; bg: string }> = {
    '上升期': { label: '↑ 上升期', color: 'text-teal', bg: 'bg-teal-light' },
    '见顶': { label: '→ 见顶', color: 'text-amber', bg: 'bg-amber-light' },
    '退潮': { label: '↓ 退潮', color: 'text-gray-400', bg: 'bg-gray-100' },
  };

  const generatedDates = useMemo(() => dates.filter((d) => d.report_date !== todayStr), [dates, todayStr]);
  const recoveryDays = calendarDays.filter((day) => day.status === 'MISSING' || day.status === 'ERROR');

  return (
    <div className="h-full w-full overflow-hidden">
      {/* 顶栏：scope 切换 + 日期选择 */}
      <div className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-2">
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
              {/* 头部摘要行：日期 + takeaway + 关键统计 */}
              <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2 text-[11px] font-black text-gray-400">
                      <span>{report.report_date} {report.weekday}</span>
                      {generatedAt && <span>· 更新于 {generatedAt}</span>}
                      {report.content_count ? <span>· 基于 {report.content_count} 条</span> : null}
                    </div>
                    <p className="text-sm font-bold leading-6 text-gray-800">
                      {report.takeaway || report.overview?.slice(0, 80) || '今日内容已完成分析。'}
                    </p>
                  </div>
                </div>
              </div>

              {/* 选题决策列表 */}
              <div className="space-y-2">
                {pickList.map((pick, i) => {
                  const isExpanded = expandedPick === i;
                  const lc = pick.lifecycle ? LIFECYCLE_META[pick.lifecycle] || LIFECYCLE_META['上升期'] : null;
                  return (
                    <div
                      key={`pick-${i}`}
                      className={cx(
                        'rounded-lg border bg-white shadow-sm transition',
                        isExpanded ? 'border-primary-border shadow-md' : 'border-gray-200',
                      )}
                    >
                      {/* 选题一行摘要（可扫描层） */}
                      <button
                        type="button"
                        onClick={() => setExpandedPick(isExpanded ? null : i)}
                        className="flex w-full items-start gap-3 p-3 text-left sm:p-4"
                      >
                        {/* 排名 + 评分 */}
                        <div className="flex shrink-0 flex-col items-center gap-0.5">
                          <div className={cx(
                            'grid h-9 w-9 place-items-center rounded-lg font-mono text-lg font-black',
                            i === 0 ? 'bg-primary text-white' : 'bg-gray-100 text-gray-600',
                          )}>
                            {i + 1}
                          </div>
                          <div className="text-[10px] font-bold text-primary">{pick.score || '-'}</div>
                        </div>

                        {/* 标题 + 元数据 */}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start gap-2">
                            <h3 className="flex-1 text-sm font-bold leading-6 text-gray-900 sm:text-[15px]">{pick.title}</h3>
                            {pick.source_url && (
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
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            {lc && (
                              <span className={cx('rounded-full px-2 py-0.5 text-[10px] font-bold', lc.bg, lc.color)}>
                                {lc.label}
                              </span>
                            )}
                            {(pick.platforms ?? []).slice(0, 3).map((p, j) => (
                              <span key={`${p}-${j}`} className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] text-gray-500">
                                {p}
                              </span>
                            ))}
                            {pick.time_window && (
                              <span className="text-[10px] text-gray-400">· {pick.time_window}</span>
                            )}
                          </div>
                        </div>

                        {/* 展开指示 */}
                        <div className={cx('mt-1 shrink-0 text-gray-300 transition', isExpanded && 'rotate-90')}>
                          <ChevronRight size={16} />
                        </div>
                      </button>

                      {/* 展开后的决策卡 */}
                      {isExpanded && (
                        <div className="border-t border-gray-100 px-3 pb-3 pt-2 sm:px-4">
                          {/* 推荐理由 */}
                          <div className="mb-3 text-[13px] leading-6 text-gray-600">{pick.reason}</div>

                          {/* 创作角度 */}
                          {pick.angles && pick.angles.length > 0 && (
                            <div className="mb-3">
                              <div className="mb-1.5 flex items-center gap-1 text-[11px] font-black text-gray-500">
                                <Lightbulb size={12} className="text-primary" /> 推荐角度
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {pick.angles.map((angle, j) => (
                                  <span key={`angle-${j}`} className="rounded-md border border-primary-border bg-primary-light px-2.5 py-1 text-[12px] font-medium text-gray-700">
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
                              <span className="text-[12px] leading-5 text-gray-600">{pick.pitfall}</span>
                            </div>
                          )}

                          {/* 操作按钮 */}
                          <div className="flex items-center gap-2">
                            <a
                              href={`/plan?title=${encodeURIComponent(pick.title)}${pick.source_url ? `&url=${encodeURIComponent(pick.source_url)}` : ''}`}
                              className="flex items-center gap-1 rounded-md bg-primary px-4 py-2 text-xs font-bold text-white hover:opacity-90"
                            >
                              <FileText size={13} /> 写这个
                            </a>
                            <button
                              type="button"
                              className="flex items-center gap-1 rounded-md border border-gray-200 px-3 py-2 text-xs font-bold text-gray-500 hover:text-gray-700"
                            >
                              <Inbox size={13} /> 观察
                            </button>
                            <button
                              type="button"
                              className="flex items-center gap-1 rounded-md border border-gray-200 px-3 py-2 text-xs font-bold text-gray-400 hover:text-gray-600"
                            >
                              跳过
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

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
            <ReportStatusPanel
              icon={Inbox}
              action={(
                <ReportActionButton
                  onClick={() => generateForDate(recoveryDate)}
                  loading={generating && generatingDate === recoveryDate}
                  icon={FileText}
                >
                  生成 {recoveryDate}
                </ReportActionButton>
              )}
            >
              今日暂无精选选题，点击生成
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
    </div>
  );
}
