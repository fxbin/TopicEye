'use client';

/**
 * 晨报头版组件（issue #119 日报改版 v1）。
 *
 * 报纸语法的头版结构（R1-R8 圆桌定案、demo 验证后落地）：
 * - Masthead：刊名 + 双细线 + 日期行（期号/版次/出刊时刻）+ 统计行（昨日兑现/长度合同）
 * - 导语块：takeaway（衬线导语）+ overview（主编判断，左边线）
 * - LeadPickCard：头题全展（引题/大标题/主判/证据行/还热行/角度/避坑/动作）
 * - SecondPickRow：二条窄栏（分类/▲↑↓/标题/一行理由/还热，点击展开）
 * - ColophonStrip：中缝（昨日对账摘要 + 导流）
 *
 * 问责按 R8 校准做轻量：一行昨日兑现、「这题什么时候凉」随题走、▲↑↓ 变化标记。
 */

import React from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, ChevronDown, Clock, ExternalLink, Flame } from 'lucide-react';
import { cx } from '@/components/ui';
import Sparkline from '@/components/Sparkline';
import type { SparklineData } from '@/components/Sparkline';
import { dailyEditionLabel } from '@/lib/edition-naming';
import {
  type DailyPick,
  type MarkAction,
  LIFECYCLE_META,
  isEnglishTitle,
  displaySourceTitle,
  pickKey,
  creationPlanHref,
} from './_daily-utils';


/** 「写这个」：带选题上下文跳创作计划页（与 PickCard 的链接同参）。 */
export function useWritePick() {
  const router = useRouter();
  return (pick: Partial<DailyPick>) => router.push(creationPlanHref(pick));
}

// ── 变化标记（▲新入 / ↑涨 / →稳）：与昨日日报 diff 得出 ──────────────

export type PickChangeMarker = 'new' | 'up' | 'down' | 'flat';

export function computeChangeMarkers(
  picks: DailyPick[],
  yesterdayPicks: Array<{ source_title: string; title?: string; old_score: number | null }> | undefined,
): Record<string, PickChangeMarker> {
  const markers: Record<string, PickChangeMarker> = {};
  if (!yesterdayPicks) return markers;
  const yesterday = new Map(yesterdayPicks.map((p) => [pickKey(p), p.old_score]));
  for (const pick of picks) {
    const key = pickKey(pick);
    if (!key) continue;
    const oldScore = yesterday.get(key);
    if (!yesterday.has(key)) {
      markers[key] = 'new';
    } else if (oldScore == null) {
      continue;
    } else if (pick.score != null && pick.score > oldScore + 1) {
      markers[key] = 'up';
    } else if (pick.score != null && pick.score < oldScore - 1) {
      markers[key] = 'down';
    } else {
      markers[key] = 'flat';
    }
  }
  return markers;
}

const CHANGE_META: Record<PickChangeMarker, { label: string; cls: string }> = {
  new: { label: '▲新入', cls: 'text-teal-text bg-teal-light' },
  up: { label: '↑涨', cls: 'text-amber-800 bg-amber-light' },
  down: { label: '↓降', cls: 'text-gray-600 bg-gray-100' },
  flat: { label: '→稳', cls: 'text-gray-500 bg-gray-100' },
};

export function ChangeMarkerBadge({ marker }: { marker?: PickChangeMarker }) {
  if (!marker) return null;
  const meta = CHANGE_META[marker];
  return <span className={cx('shrink-0 rounded-xs px-1.5 py-0.5 text-[12px] font-black', meta.cls)}>{meta.label}</span>;
}

// ── 「这题什么时候凉」：lifecycle + time_window 的创作者翻译 ──────────

export function coolDownText(pick: PickLifecycle & { time_window?: string }): string {
  const tw = pick.time_window?.trim();
  switch (pick.lifecycle) {
    case '上升期':
      return tw ? `还在升温，${tw}` : '还在升温，建议尽快进场';
    case '见顶':
      return tw ? `热度见顶，${tw}` : '热度见顶，建议收尾';
    case '退潮':
      return '正在退潮，不建议新进场';
    default:
      return tw || '';
  }
}

interface PickLifecycle {
  lifecycle?: string;
}

// ── 报头（Masthead）──────────────────────────────────────────────────

export function Masthead({
  reportDate,
  weekday,
  editionLabel,
  issueNumber,
  generatedAt,
  yesterdayLine,
  pickCount,
  readMinutes,
}: {
  reportDate: string;
  weekday: string;
  editionLabel?: string;
  issueNumber?: number;
  generatedAt?: string;
  yesterdayLine?: string;
  pickCount: number;
  readMinutes: number;
}) {
  return (
    <header className="bg-white px-5 pt-2 text-center sm:px-8">
      <p className="pt-3 text-[12px] font-semibold tracking-[0.16em] text-gray-500">{dailyEditionLabel(reportDate)}</p>
      <h1 className="mt-1 font-serif-display text-[30px] font-black leading-tight tracking-[0.3em] text-gray-900 [text-indent:0.3em] sm:text-[38px] sm:tracking-[0.5em] sm:[text-indent:0.5em]">
        选题雷达
      </h1>
      <div className="mx-0 mt-3 border-t-[3px] border-b border-gray-900" />
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 py-3 text-[12px] font-medium text-gray-600">
        <span className="text-[12px] font-black text-gray-800">{reportDate} {weekday}</span>
        {editionLabel && <span>· {editionLabel}</span>}
        {issueNumber != null && <span>· 第 {issueNumber} 期</span>}
        <span className="basis-full text-center text-[12px] text-gray-500 sm:ml-auto sm:basis-auto">
          {generatedAt && <>数据截至 {generatedAt}</>}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-b border-gray-200 py-2.5 text-[12px] font-medium text-gray-600">
        {yesterdayLine && <span className="hidden text-gray-600 sm:inline">{yesterdayLine}</span>}
        <span>
          本期 <span className="font-mono text-[13px] font-black text-primary-text">{pickCount}</span> 题
        </span>
        <span>约 {readMinutes} 分钟读完</span>
      </div>
    </header>
  );
}

// ── 导语块（takeaway + 主编判断）─────────────────────────────────────

export function LeadIn({ takeaway, overview }: { takeaway?: string | null; overview?: string | null }) {
  if (!takeaway && !overview) return null;
  return (
    <section className="bg-white px-5 py-5 sm:px-8 sm:py-6">
      {(takeaway || overview) && (
        <p className="font-serif-display text-[18px] font-bold leading-8 text-gray-900 sm:text-[21px]">
          {takeaway || overview}
        </p>
      )}
      {overview && takeaway && (
        <>
          <div className="mt-3 hidden max-w-[48em] text-[14px] leading-7 text-gray-600 sm:block">
            <span className="mr-2 text-[12px] font-bold text-gray-800">主编判断</span>{overview}
          </div>
          <details className="mt-2 text-[14px] leading-7 text-gray-600 sm:hidden">
            <summary className="cursor-pointer py-1 text-[13px] font-semibold text-gray-600">主编判断</summary>
            <p className="pt-1">{overview}</p>
          </details>
        </>
      )}
    </section>
  );
}

// ── 头题卡（头版全展）────────────────────────────────────────────────

export function LeadPickCard({
  pick,
  sparklineData,
  markAction,
  showOriginalLang,
  onToggleLang,
  onMark,
  onOpenReader,
  onWrite,
}: {
  pick: DailyPick;
  sparklineData?: SparklineData;
  markAction?: MarkAction;
  showOriginalLang: boolean;
  onToggleLang: () => void;
  onMark: (title: string, action: MarkAction, category?: string, sourceUrl?: string) => void;
  onOpenReader: (contentId: number, url?: string) => void;
  onWrite: (pick: DailyPick) => void;
}) {
  const key = pickKey(pick);
  const lifecycleMeta = pick.lifecycle ? LIFECYCLE_META[pick.lifecycle] : undefined;
  const sourceTitle = displaySourceTitle(pick, showOriginalLang);
  const cool = coolDownText(pick);

  return (
    <article className="border-t border-gray-200 bg-white px-5 py-6 sm:px-8">
      {/* 引题行 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-bold tracking-wide text-primary-text">
          {pick.category || '精选选题'}
        </span>
        {pick.score != null && (
          <span className="font-mono text-[12px] font-semibold text-gray-500">综合 {pick.score}</span>
        )}
        {lifecycleMeta && (
          <span className={cx('rounded-xs px-1.5 py-0.5 text-[12px] font-bold', lifecycleMeta.color, lifecycleMeta.bg)}>
            {lifecycleMeta.label}
          </span>
        )}
      </div>

      {/* 大标题 + 副题（主判） */}
      <h2 className="mt-3 font-serif-display text-[24px] font-bold leading-snug text-gray-900 sm:text-[30px]">
        {pick.editorial_title || pick.title}
      </h2>
      <p className="mt-3 max-w-[46em] text-[15px] leading-7 text-gray-600">{pick.reason}</p>

      {/* 证据行：原文 + 热度曲线 + 还热判断 */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-gray-100 pt-3 text-[13px] text-gray-600">
        {sourceTitle && (pick.content_id || pick.source_url) && (
          <button
            type="button"
            className="flex min-w-0 max-w-full items-center gap-1.5 text-left hover:text-primary-text"
            onClick={() => (pick.content_id ? onOpenReader(pick.content_id) : window.open(pick.source_url, '_blank'))}
            title={pick.content_id ? '站内阅读原文' : '打开原文'}
          >
            {pick.content_id ? <BookOpen size={11} className="shrink-0" /> : <ExternalLink size={11} className="shrink-0" />}
            <span className="min-w-0 break-words font-medium">{sourceTitle}</span>
          </button>
        )}
        {sparklineData && sparklineData.points.length > 0 && (
          <Sparkline data={sparklineData} />
        )}
        {cool && (
          <span className="flex items-start gap-1.5 text-[12px] font-medium leading-6 text-amber-800">
            <Clock size={11} />
            选题时机：{cool}
          </span>
        )}
        {isEnglishTitle(pick.source_title) && <button
          type="button"
          onClick={onToggleLang}
          className="ml-auto shrink-0 text-[12px] font-bold text-teal-text hover:text-primary-text"
        >
          {showOriginalLang ? '显示中文' : '显示原文'}
        </button>}
      </div>

      {/* 可写角度 */}
      {pick.angles && pick.angles.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[12px] font-bold text-gray-500">可写角度</span>
          {pick.angles.map((angle, i) => (
            <span key={`angle-${i}`} className="rounded-md bg-gray-50 px-2.5 py-1 text-[13px] font-medium leading-6 text-gray-700">
              {angle}
            </span>
          ))}
        </div>
      )}

      {/* 避坑提示 */}
      {pick.pitfall && (
        <div className="mt-3 flex items-start gap-2 rounded-md bg-amber-light px-3 py-2.5 text-[13px] leading-6 text-gray-700">
          <AlertTriangle size={14} className="mt-1 shrink-0 text-amber-800" /> {pick.pitfall}
        </div>
      )}

      {/* 动作带 */}
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-4">
        <button
          type="button"
          onClick={() => onWrite(pick)}
          className="flex min-h-10 items-center gap-2 rounded-md bg-primary-solid px-4 py-2 text-[13px] font-bold text-white transition-colors hover:bg-primary-text active:scale-[0.98] motion-reduce:transform-none"
        >
          写这个 <ArrowRight size={12} />
        </button>
        <button
          type="button"
          onClick={() => onMark(key, 'write', pick.category, pick.source_url)}
          aria-pressed={markAction === 'write'}
          className={cx('inline-flex min-h-10 items-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-semibold transition-colors', markAction === 'write' ? 'border-primary-border bg-primary-light text-primary-text' : 'border-gray-200 text-gray-600 hover:bg-gray-50')}
        >
          <CheckCircle2 size={14} />{markAction === 'write' ? '已选' : '加入已选'}
        </button>
        <button
          type="button"
          onClick={() => onMark(key, 'watch', pick.category, pick.source_url)}
          aria-pressed={markAction === 'watch'}
          className={cx(
            'min-h-10 rounded-md border px-3 py-2 text-[13px] font-semibold transition-colors',
            markAction === 'watch' ? 'border-teal-border bg-teal-light text-teal-text' : 'border-gray-200 text-gray-600 hover:bg-gray-50',
          )}
        >
          {markAction === 'watch' ? '✓ 已记着' : '先记着'}
        </button>
        <button
          type="button"
          onClick={() => onMark(key, 'skip', pick.category, pick.source_url)}
          aria-pressed={markAction === 'skip'}
          className={cx(
            'min-h-10 rounded-md border px-3 py-2 text-[13px] font-semibold transition-colors',
            markAction === 'skip' ? 'border-gray-400 bg-gray-100 text-gray-600' : 'border-gray-200 text-gray-600 hover:bg-gray-50',
          )}
        >
          {markAction === 'skip' ? '✓ 已跳过' : '跳过'}
        </button>
      </div>
    </article>
  );
}

// ── 二条窄栏（点击展开）──────────────────────────────────────────────

export function SecondPickRow({
  pick,
  rank,
  marker,
  expanded,
  onToggle,
  markAction,
  onMark,
  onOpenReader,
  onWrite,
}: {
  pick: DailyPick;
  rank: number;
  marker?: PickChangeMarker;
  expanded: boolean;
  onToggle: () => void;
  markAction?: MarkAction;
  onMark: (title: string, action: MarkAction, category?: string, sourceUrl?: string) => void;
  onOpenReader: (contentId: number, url?: string) => void;
  onWrite: (pick: DailyPick) => void;
}) {
  const key = pickKey(pick);
  const cool = coolDownText(pick);

  return (
    <div className="bg-white">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="grid w-full grid-cols-[28px_minmax(0,1fr)_18px] items-start gap-3 border-t border-gray-200 px-5 py-5 text-left transition-colors hover:bg-gray-50 sm:px-8"
      >
        <span className="pt-0.5 font-mono text-[16px] font-medium text-gray-500">{String(rank).padStart(2, '0')}</span>
        <span className="min-w-0">
          <span className="mb-1.5 flex flex-wrap items-center gap-2 text-[12px] font-medium text-gray-500">
            <span>{pick.category || '精选'}</span><ChangeMarkerBadge marker={marker} />
            {pick.score != null && <span className="ml-auto font-mono">综合 {pick.score}</span>}
          </span>
          <span className="block text-[17px] font-bold leading-7 text-gray-900">{pick.editorial_title || pick.title}</span>
          {!expanded && <span className="mt-1.5 line-clamp-2 block text-[14px] leading-6 text-gray-600">{pick.reason}</span>}
          {cool && <span className="mt-2 block text-[12px] font-medium leading-5 text-amber-800">{cool}</span>}
        </span>
        <ChevronDown size={16} className={cx('mt-1 text-gray-500 transition-transform duration-200 motion-reduce:transition-none', expanded && 'rotate-180')} />
      </button>

      {expanded && (
        <div className="border-b border-gray-100 bg-gray-50/60 px-5 pb-5 pt-1 sm:px-8">
          <p className="text-[14px] leading-7 text-gray-600">{pick.reason}</p>
          {pick.angles && pick.angles.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[12px] font-bold text-gray-500">可写角度</span>
              {pick.angles.map((angle, i) => (
                <span key={`s-angle-${i}`} className="rounded-xs bg-primary-light px-2 py-0.5 text-[12px] font-bold text-primary-text">
                  {angle}
                </span>
              ))}
            </div>
          )}
          {pick.pitfall && (
            <div className="mt-2 rounded-xs border-l-[3px] border-amber bg-amber-light px-3 py-1.5 text-[12px] font-bold leading-5 text-amber-800">
              ⚠ {pick.pitfall}
            </div>
          )}
          {pick.source_title && (pick.content_id || pick.source_url) && (
            <button
              type="button"
              className="mt-2 flex min-w-0 items-center gap-1 text-left text-[13px] font-medium text-gray-600 hover:text-primary-text"
              onClick={() => (pick.content_id ? onOpenReader(pick.content_id) : window.open(pick.source_url, '_blank'))}
            >
              {pick.content_id ? <BookOpen size={11} /> : <ExternalLink size={11} />}
              {pick.source_title_zh || pick.source_title}
            </button>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onWrite(pick)}
              className="flex items-center gap-1 min-h-10 rounded-md bg-primary-solid px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-primary-text"
            >
              写这个 <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => onMark(key, 'write', pick.category, pick.source_url)}
              aria-pressed={markAction === 'write'}
              className={cx('inline-flex min-h-10 items-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-semibold transition-colors', markAction === 'write' ? 'border-primary-border bg-primary-light text-primary-text' : 'border-gray-200 text-gray-600 hover:bg-gray-50')}
            >
              <CheckCircle2 size={14} />{markAction === 'write' ? '已选' : '加入已选'}
            </button>
            <button
              type="button"
              onClick={() => onMark(key, 'watch', pick.category, pick.source_url)}
              aria-pressed={markAction === 'watch'}
              className={cx(
                'min-h-10 rounded-md border px-3 py-2 text-[13px] font-semibold transition-colors',
                markAction === 'watch' ? 'border-teal-border bg-teal-light text-teal-text' : 'border-gray-200 text-gray-500',
              )}
            >
              {markAction === 'watch' ? '✓ 已记着' : '先记着'}
            </button>
            <button
              type="button"
              onClick={() => onMark(key, 'skip', pick.category, pick.source_url)}
              className={cx(
                'min-h-10 rounded-md border px-3 py-2 text-[13px] font-semibold transition-colors',
                markAction === 'skip' ? 'border-gray-400 bg-gray-100 text-gray-600' : 'border-gray-200 text-gray-500',
              )}
            >
              跳过
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 中缝（昨日对账 + 导流）───────────────────────────────────────────

export function ColophonStrip({
  yesterdaySummary,
}: {
  yesterdaySummary?: { confirmed: number; reversed: number; persisted: number; dropped: number } | null;
}) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-b border-gray-200 px-4 py-2 text-[12px] font-medium text-gray-600">
      {yesterdaySummary ? (
        <span>
          昨日对账：
          <span className="text-teal-text">兑现 {yesterdaySummary.confirmed}</span> ·
          <span className="text-amber-800"> 反转 {yesterdaySummary.reversed}</span> ·
          <span className="text-primary-text"> 仍在榜 {yesterdaySummary.persisted}</span> ·
          <span className="text-gray-500"> 掉出 {yesterdaySummary.dropped}</span>
        </span>
      ) : (
        <span>昨日对账：首期或数据不足</span>
      )}
      <span className="text-gray-500">｜</span>
      <a href="/trends" className="hover:text-primary-text">趋势实验室 →</a>
      <a href="/today-picks" className="hover:text-primary-text">今日精选 →</a>
    </div>
  );
}

// ── 趋势一行（增刊归还：缩为一行跳 /trends）─────────────────────────

export function TrendsOneLiner({
  trends,
}: {
  trends: Array<{ title: string; momentum?: string }>;
}) {
  if (trends.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-gray-100 bg-white px-5 py-4 text-[13px] text-gray-600 sm:px-8">
      <Flame size={12} className="shrink-0 text-primary-text" />
      <span className="font-black text-gray-700">趋势信号</span>
      {trends.slice(0, 3).map((t, i) => (
        <span key={`t-${i}`} className="flex items-center gap-1">
          <span className={cx('font-bold', t.momentum === 'up' ? 'text-teal-text' : t.momentum === 'down' ? 'text-gray-500' : 'text-amber-800')}>
            {t.momentum === 'up' ? '↑' : t.momentum === 'down' ? '↓' : '→'}
          </span>
          {t.title}
        </span>
      ))}
      <a href="/trends" className="ml-auto font-bold text-teal-text hover:text-primary-text">趋势实验室 →</a>
    </div>
  );
}
