'use client';

/**
 * 文稿检测的高亮渲染（从 page.tsx 拆出便于测试）。
 *
 * 偏移口径（与后端 sensitive_word_service / ai_trace_service 一致，改动两边一起改）：
 * 后端 start/end 是 Unicode codepoint 偏移（Python len 口径），而 JS 字符串
 * 下标是 UTF-16 code unit——emoji 等增补平面字符两者会错位。因此这里必须
 * 用 Array.from 按 codepoint 切分后再按偏移取段，不能直接 text.slice。
 */

import React from 'react';
import { cx } from '@/components/ui';
import {
  AI_TRACE_WORD_DIMENSION_LABELS,
  SENSITIVE_CATEGORY_META,
  SENSITIVE_SEVERITY_LABELS,
  type AiTraceWordHit,
  type SensitiveHit,
  type SensitiveSeverity,
} from '@/types/content-check';

/** 高亮命中：风险命中（敏感词）或写作建议命中（AI 痕迹词），共用 codepoint 偏移合同。 */
export type HighlightHit = SensitiveHit | AiTraceWordHit;

export interface HighlightSegment<T extends HighlightHit = HighlightHit> {
  text: string;
  /** 命中段携带完整 hit；纯文本段为 undefined。 */
  hit?: T;
}

/** 把原文切成纯文本/命中交替的段（后端保证命中区间有序且不重叠，此处仍防御排序与夹取）。 */
export function buildHighlightSegments<T extends HighlightHit>(text: string, hits: T[]): HighlightSegment<T>[] {
  const chars = Array.from(text);
  // 同 start 长词优先；完全同区间时风险命中（sensitive）先于写作建议（ai_traces）
  const kindRank = (h: HighlightHit): number => ('severity' in h ? 0 : 1);
  const ordered = [...hits].sort((a, b) => a.start - b.start || b.end - a.end || kindRank(a) - kindRank(b));
  const segments: HighlightSegment<T>[] = [];
  let cursor = 0;
  for (const hit of ordered) {
    const start = Math.max(hit.start, cursor);
    const end = Math.min(hit.end, chars.length);
    if (start >= end) continue; // 越界或与已渲染段重叠的脏数据，宁可不高亮也不错位
    if (start > cursor) segments.push({ text: chars.slice(cursor, start).join('') });
    segments.push({ text: chars.slice(start, end).join(''), hit });
    cursor = end;
  }
  if (cursor < chars.length) segments.push({ text: chars.slice(cursor).join('') });
  return segments;
}

const SEVERITY_MARK_CLS: Record<SensitiveSeverity, string> = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-yellow-50 text-yellow-700',
};

/** AI 痕迹命中统一紫色系（设计系统 --color-purple），与风险红/黄明确区分。 */
const AI_TRACE_MARK_CLS = 'bg-purple-light text-purple';

/** 风险命中 hover 提示：命中词 + 分类/严重度 + 替换建议（原生 title，无 JS 态也可达）。 */
export function buildHoverTitle(hit: SensitiveHit): string {
  const meta = SENSITIVE_CATEGORY_META[hit.category];
  const head = `「${hit.word}」${meta?.label ?? hit.category} · ${SENSITIVE_SEVERITY_LABELS[hit.severity]}`;
  const advice = hit.suggestion ? `建议：${hit.suggestion}` : '建议：删除或改写';
  return `${head}\n${advice}`;
}

/** AI 痕迹命中 hover：词条 + 词维度，明示启发式统计口径（不暗示模型检测）。 */
export function buildAiTraceHoverTitle(hit: AiTraceWordHit): string {
  const label = AI_TRACE_WORD_DIMENSION_LABELS[hit.dimension] ?? hit.dimension;
  return `「${hit.word}」${label} · 启发式统计\n建议：换成具体动作、数字或事例`;
}

export function HighlightText({ text, hits }: { text: string; hits: HighlightHit[] }) {
  const segments = buildHighlightSegments(text, hits);
  return (
    <p className="whitespace-pre-wrap break-words text-[14px] leading-7 text-gray-800">
      {segments.map((seg, i) => {
        if (!seg.hit) return <React.Fragment key={i}>{seg.text}</React.Fragment>;
        const hit = seg.hit;
        if ('severity' in hit) {
          return (
            <mark
              key={i}
              data-sensitive-word={hit.word}
              data-sensitive-severity={hit.severity}
              title={buildHoverTitle(hit)}
              className={cx('rounded-sm px-0.5 font-bold underline decoration-2 underline-offset-4', SEVERITY_MARK_CLS[hit.severity])}
            >
              {seg.text}
            </mark>
          );
        }
        return (
          <mark
            key={i}
            data-ai-trace-word={hit.word}
            data-ai-trace-dimension={hit.dimension}
            title={buildAiTraceHoverTitle(hit)}
            className={cx('rounded-sm px-0.5 font-bold underline decoration-2 underline-offset-4', AI_TRACE_MARK_CLS)}
          >
            {seg.text}
          </mark>
        );
      })}
    </p>
  );
}
