'use client';

/**
 * 文稿检测的高亮渲染（从 page.tsx 拆出便于测试）。
 *
 * 偏移口径（与后端 sensitive_word_service 一致，改动两边一起改）：
 * 后端 start/end 是 Unicode codepoint 偏移（Python len 口径），而 JS 字符串
 * 下标是 UTF-16 code unit——emoji 等增补平面字符两者会错位。因此这里必须
 * 用 Array.from 按 codepoint 切分后再按偏移取段，不能直接 text.slice。
 */

import React from 'react';
import { cx } from '@/components/ui';
import {
  SENSITIVE_CATEGORY_META,
  SENSITIVE_SEVERITY_LABELS,
  type SensitiveHit,
  type SensitiveSeverity,
} from '@/types/content-check';

export interface HighlightSegment {
  text: string;
  /** 命中段携带完整 hit；纯文本段为 undefined。 */
  hit?: SensitiveHit;
}

/** 把原文切成纯文本/命中交替的段（后端保证命中区间有序且不重叠，此处仍防御排序与夹取）。 */
export function buildHighlightSegments(text: string, hits: SensitiveHit[]): HighlightSegment[] {
  const chars = Array.from(text);
  const ordered = [...hits].sort((a, b) => a.start - b.start || b.end - a.end);
  const segments: HighlightSegment[] = [];
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

/** hover 提示：命中词 + 分类/严重度 + 替换建议（原生 title，无 JS 态也可达）。 */
export function buildHoverTitle(hit: SensitiveHit): string {
  const meta = SENSITIVE_CATEGORY_META[hit.category];
  const head = `「${hit.word}」${meta?.label ?? hit.category} · ${SENSITIVE_SEVERITY_LABELS[hit.severity]}`;
  const advice = hit.suggestion ? `建议：${hit.suggestion}` : '建议：删除或改写';
  return `${head}\n${advice}`;
}

export function HighlightText({ text, hits }: { text: string; hits: SensitiveHit[] }) {
  const segments = buildHighlightSegments(text, hits);
  return (
    <p className="whitespace-pre-wrap break-words text-[14px] leading-7 text-gray-800">
      {segments.map((seg, i) =>
        seg.hit ? (
          <mark
            key={i}
            data-sensitive-word={seg.hit.word}
            data-sensitive-severity={seg.hit.severity}
            title={buildHoverTitle(seg.hit)}
            className={cx('rounded-sm px-0.5 font-bold underline decoration-2 underline-offset-4', SEVERITY_MARK_CLS[seg.hit.severity])}
          >
            {seg.text}
          </mark>
        ) : (
          <React.Fragment key={i}>{seg.text}</React.Fragment>
        ),
      )}
    </p>
  );
}
