'use client';

/**
 * 日报页面提取的子组件。
 *
 * 从 page.tsx 提取，保持行为完全等价。
 */

import React from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  FileText,
  Inbox,
  Lightbulb,
} from 'lucide-react';
import { cx } from '@/components/ui';
import { AutoLink } from '@/components/AutoLink';
import Sparkline, { SparklineData } from '@/components/Sparkline';
import {
  type DailyPick,
  type MarkAction,
  LIFECYCLE_META,
  pickKey,
  isEnglishTitle,
  displaySourceTitle,
} from './_daily-utils';

// ── StatBox ──────────────────────────────────────────────────────────

export function StatBox({ label, value, tone = 'neutral' }: { label: string; value: React.ReactNode; tone?: 'primary' | 'red' | 'neutral' }) {
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

// ── PickCard (feature tier) ──────────────────────────────────────────

export interface PickCardProps {
  pick: DailyPick;
  globalIdx: number;
  isExpanded: boolean;
  onToggleExpand: () => void;
  sparklineData?: SparklineData;
  markAction?: MarkAction;
  showOriginalLang: boolean;
  onToggleLang: () => void;
  onMark: (key: string, action: MarkAction, category?: string, sourceUrl?: string) => void;
  onOpenReader: (contentId: number) => void;
}

export function PickCard({
  pick,
  globalIdx,
  isExpanded,
  onToggleExpand,
  sparklineData,
  markAction,
  showOriginalLang,
  onToggleLang,
  onMark,
  onOpenReader,
}: PickCardProps) {
  const lc = pick.lifecycle ? LIFECYCLE_META[pick.lifecycle] || LIFECYCLE_META['上升期'] : null;
  const key = pickKey(pick);

  return (
    <div
      className={cx(
        'rounded-lg border bg-white shadow-sm transition',
        isExpanded ? 'border-primary-border shadow-md' : 'border-gray-200',
      )}
    >
      {/* 选题一行摘要（可扫描层）*/}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggleExpand}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggleExpand(); } }}
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
                onClick={(e) => { e.stopPropagation(); onOpenReader(pick.content_id!); }}
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
                  onClick={(e) => { e.stopPropagation(); onToggleLang(); }}
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
              data={sparklineData}
              loading={!sparklineData?.points}
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
                  onClick={(e) => { e.stopPropagation(); onToggleLang(); }}
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
              onClick={(e) => { e.stopPropagation(); onMark(key, 'write', pick.category, pick.source_url); }}
              className={cx(
                'flex items-center gap-1 rounded-md border px-3 py-2 text-xs font-bold transition',
                markAction === 'write'
                  ? 'border-primary bg-primary-light text-primary'
                  : 'border-gray-200 text-gray-500 hover:text-gray-700',
              )}
            >
              <CheckCircle2 size={13} /> 已选
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onMark(key, 'watch', pick.category, pick.source_url); }}
              className={cx(
                'flex items-center gap-1 rounded-md border px-3 py-2 text-xs font-bold transition',
                markAction === 'watch'
                  ? 'border-amber bg-amber-light text-amber'
                  : 'border-gray-200 text-gray-500 hover:text-gray-700',
              )}
            >
              <Inbox size={13} /> 观察
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onMark(key, 'skip', pick.category, pick.source_url); }}
              className={cx(
                'flex items-center gap-1 rounded-md border px-3 py-2 text-xs font-bold transition',
                markAction === 'skip'
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
}

// ── BriefPickRow (brief tier) ─────────────────────────────────────────

export interface BriefPickRowProps {
  pick: DailyPick;
  globalIdx: number;
  isExpanded: boolean;
  onToggleExpand: () => void;
  markAction?: MarkAction;
  showOriginalLang: boolean;
  onToggleLang: () => void;
  onMark: (key: string, action: MarkAction, category?: string, sourceUrl?: string) => void;
  onOpenReader: (contentId: number) => void;
}

export function BriefPickRow({
  pick,
  globalIdx,
  isExpanded,
  onToggleExpand,
  markAction,
  showOriginalLang,
  onToggleLang,
  onMark,
  onOpenReader,
}: BriefPickRowProps) {
  const key = pickKey(pick);

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={onToggleExpand}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggleExpand(); } }}
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
                onClick={(e) => { e.stopPropagation(); onOpenReader(pick.content_id!); }}
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
                  onClick={(e) => { e.stopPropagation(); onToggleLang(); }}
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
            onClick={(e) => { e.stopPropagation(); onMark(key, 'write', pick.category, pick.source_url); }}
            className={cx(
              'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold transition',
              markAction === 'write'
                ? 'border-primary bg-primary-light text-primary'
                : 'border-gray-200 text-gray-500 hover:text-gray-700',
            )}
          >
            <CheckCircle2 size={12} /> 已选
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onMark(key, 'watch', pick.category, pick.source_url); }}
            className={cx(
              'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold transition',
              markAction === 'watch'
                ? 'border-amber bg-amber-light text-amber'
                : 'border-gray-200 text-gray-500 hover:text-gray-700',
            )}
          >
            <Inbox size={12} /> 观察
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onMark(key, 'skip', pick.category, pick.source_url); }}
            className={cx(
              'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold transition',
              markAction === 'skip'
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
}

