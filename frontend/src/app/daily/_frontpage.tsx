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
import { ArrowRight, BookOpen, Clock, ExternalLink, Flame } from 'lucide-react';
import { cx } from '@/components/ui';
import Sparkline from '@/components/Sparkline';
import type { SparklineData } from '@/components/Sparkline';
import { EDITION_LABELS } from '@/lib/edition-naming';
import {
  type DailyPick,
  type MarkAction,
  LIFECYCLE_META,
  CATEGORY_EN,
  isEnglishTitle,
  displaySourceTitle,
  pickKey,
} from './_daily-utils';


/** 「写这个」：带选题上下文跳创作计划页（与 PickCard 的链接同参）。 */
export function useWritePick() {
  const router = useRouter();
  return (pick: PickForWrite) => {
    const title = encodeURIComponent(pick.source_title_zh || pick.source_title || pick.title || '');
    const url = pick.source_url ? `&url=${encodeURIComponent(pick.source_url)}` : '';
    router.push(`/plan?title=${title}${url}`);
  };
}

interface PickForWrite {
  title?: string;
  source_title?: string;
  source_title_zh?: string;
  source_url?: string;
}

// ── 变化标记（▲新入 / ↑涨 / →稳）：与昨日日报 diff 得出 ──────────────

export type PickChangeMarker = 'new' | 'up' | 'flat';

export function computeChangeMarkers(
  picks: DailyPick[],
  yesterdayPicks: Array<{ source_title: string; old_score: number | null }> | undefined,
): Record<string, PickChangeMarker> {
  const markers: Record<string, PickChangeMarker> = {};
  if (!yesterdayPicks) return markers;
  const yesterday = new Map(yesterdayPicks.map((p) => [p.source_title, p.old_score]));
  for (const pick of picks) {
    const key = pickKey(pick);
    if (!key) continue;
    const oldScore = yesterday.get(key);
    if (oldScore == null) {
      markers[key] = 'new';
    } else if (pick.score != null && pick.score > oldScore + 1) {
      markers[key] = 'up';
    } else {
      markers[key] = 'flat';
    }
  }
  return markers;
}

const CHANGE_META: Record<PickChangeMarker, { label: string; cls: string }> = {
  new: { label: '▲新入', cls: 'text-teal bg-teal-light' },
  up: { label: '↑涨', cls: 'text-amber bg-amber-light' },
  flat: { label: '→稳', cls: 'text-gray-400 bg-gray-100' },
};

export function ChangeMarkerBadge({ marker }: { marker?: PickChangeMarker }) {
  if (!marker) return null;
  const meta = CHANGE_META[marker];
  return <span className={cx('shrink-0 rounded-xs px-1.5 py-0.5 text-[10px] font-black', meta.cls)}>{meta.label}</span>;
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
    <header className="bg-white text-center">
      {/* #132 情报正族：眉题=种属四字裸放，品牌由主标题「选题雷达」承担（圆桌 r3-s2） */}
      <p className="pt-5 text-[11px] font-bold tracking-[0.35em] text-gray-400">{EDITION_LABELS.daily}</p>
      <h1 className="mt-1 font-display text-[34px] font-black leading-tight tracking-[0.6em] text-gray-900 [text-indent:0.6em]">
        选题雷达
      </h1>
      <div className="mx-0 mt-2 border-t-[3px] border-b border-gray-900" />
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 py-1.5 text-[11px] font-bold text-gray-500">
        <span className="text-[12px] font-black text-gray-800">{reportDate} {weekday}</span>
        {editionLabel && <span>· {editionLabel}</span>}
        {issueNumber != null && <span>· 第 {issueNumber} 期</span>}
        <span className="ml-auto hidden items-center gap-1 sm:flex">
          {generatedAt && <>数据截至 {generatedAt}</>}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-b border-gray-200 py-1.5 text-[11px] font-bold text-gray-500">
        {yesterdayLine && <span className="text-gray-600">{yesterdayLine}</span>}
        <span>
          今日 <span className="font-mono text-[13px] font-black text-primary">{pickCount}</span> 题
        </span>
        <span>头版约 1 分钟 · 完整版约 {readMinutes} 分钟</span>
      </div>
    </header>
  );
}

// ── 导语块（takeaway + 主编判断）─────────────────────────────────────

export function LeadIn({ takeaway, overview }: { takeaway?: string | null; overview?: string | null }) {
  if (!takeaway && !overview) return null;
  return (
    <section className="bg-white px-5 py-4">
      {(takeaway || overview) && (
        <p className="font-display text-[17px] font-black leading-8 text-gray-900">
          {takeaway || overview?.slice(0, 60)}
        </p>
      )}
      {overview && takeaway && (
        <div className="mt-2.5 border-l-[3px] border-primary pl-3 text-[13px] leading-7 text-gray-600">
          <span className="mr-1.5 text-[10px] font-black tracking-widest text-primary">主编判断</span>
          {overview}
        </div>
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
    <article className="border-l-[4px] border-primary bg-white px-5 py-4">
      {/* 引题行 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-black tracking-widest text-primary">
          {pick.category || '精选选题'}
        </span>
        {pick.score != null && (
          <span className="font-mono text-[11px] font-black text-gray-400">综合 {pick.score}</span>
        )}
        {lifecycleMeta && (
          <span className={cx('rounded-xs px-1.5 py-0.5 text-[10px] font-bold', lifecycleMeta.color, lifecycleMeta.bg)}>
            {lifecycleMeta.label}
          </span>
        )}
      </div>

      {/* 大标题 + 副题（主判） */}
      <h2 className="mt-1.5 font-display text-[24px] font-black leading-snug text-gray-900">
        {pick.editorial_title || pick.title}
      </h2>
      <p className="mt-1.5 text-[13.5px] leading-7 text-gray-600">{pick.reason}</p>

      {/* 证据行：原文 + 热度曲线 + 还热判断 */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-dashed border-gray-200 pt-2.5 text-[11px] text-gray-500">
        {sourceTitle && (
          <button
            type="button"
            className="flex min-w-0 items-center gap-1 hover:text-primary"
            onClick={() => (pick.content_id ? onOpenReader(pick.content_id) : window.open(pick.source_url, '_blank'))}
            title={isEnglishTitle(pick.source_title) ? '切换中/EN 显示' : undefined}
          >
            {pick.content_id ? <BookOpen size={11} className="shrink-0" /> : <ExternalLink size={11} className="shrink-0" />}
            <span className="max-w-[320px] truncate font-bold">{sourceTitle}</span>
          </button>
        )}
        {sparklineData && sparklineData.points.length > 0 && (
          <Sparkline data={sparklineData} />
        )}
        {cool && (
          <span className="flex items-center gap-1 font-bold text-amber">
            <Clock size={11} />
            这题什么时候凉：{cool}
          </span>
        )}
        <button
          type="button"
          onClick={onToggleLang}
          className="ml-auto shrink-0 text-[10px] font-bold text-teal hover:text-primary"
        >
          中/EN
        </button>
      </div>

      {/* 可写角度 */}
      {pick.angles && pick.angles.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-black tracking-widest text-gray-400">可写角度</span>
          {pick.angles.map((angle, i) => (
            <span key={`angle-${i}`} className="rounded-xs bg-primary-light px-2 py-0.5 text-[12px] font-bold text-primary">
              {angle}
            </span>
          ))}
        </div>
      )}

      {/* 避坑提示 */}
      {pick.pitfall && (
        <div className="mt-2.5 rounded-xs border-l-[3px] border-amber bg-amber-light px-3 py-1.5 text-[12px] font-bold leading-5 text-amber">
          ⚠ {pick.pitfall}
        </div>
      )}

      {/* 动作带 */}
      <div className="mt-3 flex items-center gap-2 border-t border-dashed border-gray-200 pt-2.5">
        <button
          type="button"
          onClick={() => onWrite(pick)}
          className="flex items-center gap-1 rounded-xs bg-primary px-3.5 py-1.5 text-[12px] font-black text-white hover:brightness-95"
        >
          写这个 <ArrowRight size={12} />
        </button>
        <button
          type="button"
          onClick={() => onMark(key, 'watch', pick.category, pick.source_url)}
          aria-pressed={markAction === 'watch'}
          className={cx(
            'rounded-xs border px-3 py-1.5 text-[12px] font-black',
            markAction === 'watch' ? 'border-teal-border bg-teal-light text-teal' : 'border-gray-200 text-gray-400 hover:text-gray-600',
          )}
        >
          {markAction === 'watch' ? '✓ 已记着' : '先记着'}
        </button>
        <button
          type="button"
          onClick={() => onMark(key, 'skip', pick.category, pick.source_url)}
          aria-pressed={markAction === 'skip'}
          className={cx(
            'rounded-xs border px-3 py-1.5 text-[12px] font-black',
            markAction === 'skip' ? 'border-gray-400 bg-gray-100 text-gray-600' : 'border-gray-200 text-gray-400 hover:text-gray-600',
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
        className="flex w-full flex-wrap items-baseline gap-x-2.5 gap-y-1 border-b border-dashed border-gray-100 px-5 py-2.5 text-left hover:bg-gray-50"
      >
        <span className="w-6 shrink-0 font-mono text-[13px] font-bold text-gray-300">
          {String(rank).padStart(2, '0')}
        </span>
        <span className="shrink-0 text-[10px] font-black tracking-wide text-gray-400">
          {pick.category || '精选'}
        </span>
        <ChangeMarkerBadge marker={marker} />
        <span className="min-w-0 flex-1 truncate text-[14px] font-black text-gray-900">
          {pick.editorial_title || pick.title}
        </span>
        {pick.score != null && (
          <span className="shrink-0 font-mono text-[11px] font-bold text-gray-400">{pick.score}</span>
        )}
        {cool && <span className="shrink-0 text-[10px] font-bold text-amber">{cool}</span>}
        <span className={cx('shrink-0 text-[10px] text-gray-400 transition-transform', expanded && 'rotate-90')}>▸</span>
      </button>

      {expanded && (
        <div className="border-b border-dashed border-gray-100 bg-gray-50/60 px-5 py-3">
          <p className="text-[12.5px] leading-7 text-gray-600">{pick.reason}</p>
          {pick.angles && pick.angles.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-black tracking-widest text-gray-400">可写角度</span>
              {pick.angles.map((angle, i) => (
                <span key={`s-angle-${i}`} className="rounded-xs bg-primary-light px-2 py-0.5 text-[11.5px] font-bold text-primary">
                  {angle}
                </span>
              ))}
            </div>
          )}
          {pick.pitfall && (
            <div className="mt-2 rounded-xs border-l-[3px] border-amber bg-amber-light px-3 py-1.5 text-[11.5px] font-bold leading-5 text-amber">
              ⚠ {pick.pitfall}
            </div>
          )}
          {pick.source_title && (
            <button
              type="button"
              className="mt-2 flex items-center gap-1 text-[11px] font-bold text-gray-400 hover:text-primary"
              onClick={() => (pick.content_id ? onOpenReader(pick.content_id) : window.open(pick.source_url, '_blank'))}
            >
              {pick.content_id ? <BookOpen size={11} /> : <ExternalLink size={11} />}
              {pick.source_title_zh || pick.source_title}
            </button>
          )}
          <div className="mt-2.5 flex items-center gap-2">
            <button
              type="button"
              onClick={() => onWrite(pick)}
              className="flex items-center gap-1 rounded-xs bg-primary px-3 py-1 text-[11.5px] font-black text-white hover:brightness-95"
            >
              写这个 <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => onMark(key, 'watch', pick.category, pick.source_url)}
              aria-pressed={markAction === 'watch'}
              className={cx(
                'rounded-xs border px-2.5 py-1 text-[11.5px] font-black',
                markAction === 'watch' ? 'border-teal-border bg-teal-light text-teal' : 'border-gray-200 text-gray-400',
              )}
            >
              {markAction === 'watch' ? '✓ 已记着' : '先记着'}
            </button>
            <button
              type="button"
              onClick={() => onMark(key, 'skip', pick.category, pick.source_url)}
              className={cx(
                'rounded-xs border px-2.5 py-1 text-[11.5px] font-black',
                markAction === 'skip' ? 'border-gray-400 bg-gray-100 text-gray-600' : 'border-gray-200 text-gray-400',
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
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-b border-gray-200 px-4 py-2 text-[11px] font-bold text-gray-500">
      {yesterdaySummary ? (
        <span>
          昨日对账：
          <span className="text-teal">兑现 {yesterdaySummary.confirmed}</span> ·
          <span className="text-amber"> 反转 {yesterdaySummary.reversed}</span> ·
          <span className="text-primary"> 仍在榜 {yesterdaySummary.persisted}</span> ·
          <span className="text-gray-400"> 掉出 {yesterdaySummary.dropped}</span>
        </span>
      ) : (
        <span>昨日对账：首期或数据不足</span>
      )}
      <span className="text-gray-300">｜</span>
      <a href="/trends" className="hover:text-primary">趋势实验室 →</a>
      <a href="/today-picks" className="hover:text-primary">今日精选 →</a>
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
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-white px-5 py-2 text-[11px] text-gray-500">
      <Flame size={12} className="shrink-0 text-primary" />
      <span className="font-black text-gray-700">趋势信号</span>
      {trends.slice(0, 3).map((t, i) => (
        <span key={`t-${i}`} className="flex items-center gap-1">
          <span className={cx('font-bold', t.momentum === 'up' ? 'text-teal' : t.momentum === 'down' ? 'text-gray-400' : 'text-amber')}>
            {t.momentum === 'up' ? '↑' : t.momentum === 'down' ? '↓' : '→'}
          </span>
          {t.title}
        </span>
      ))}
      <a href="/trends" className="ml-auto font-bold text-teal hover:text-primary">趋势实验室 →</a>
    </div>
  );
}
