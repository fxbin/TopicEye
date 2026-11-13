'use client';

/**
 * 「去 AI 味」改写建议面板（从 page.tsx 拆出便于测试，模式同 _highlight）。
 *
 * 口径红线（owning note 2026-11-04-content-check-ai-traces.md）：改写建议是
 * 「写作建议」，文案保持启发式统计口径，禁止「AI 率 / AI 概率 / 检测模型」
 * 类表述。徽标沿用 AI 痕迹的紫色系语义，与风险红/黄分开。
 */

import React from 'react';
import { ArrowRight, Loader2, PenLine, Sparkles } from 'lucide-react';
import { Badge, Button, Panel } from '@/components/ui';
import type { HumanizeRewriteSuggestion } from '@/types/content-check';

export function HumanizeRewritePanel({
  suggestions,
  loading,
  error,
  canGenerate,
  onGenerate,
}: {
  /** 已生成的建议；null 表示尚未生成（首屏不展示建议区）。 */
  suggestions: HumanizeRewriteSuggestion[] | null;
  loading: boolean;
  /** 独立的生成失败提示（inline 展示，不复用检测的 ErrorState 重试语义）。 */
  error: string | null;
  /** 只有检测结果 current 且存在 AI 痕迹命中时才可生成。 */
  canGenerate: boolean;
  onGenerate: () => void;
}) {
  return (
    <Panel className="p-4">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-sm font-black text-gray-900">
          <Sparkles size={14} className="text-purple" />
          改写建议
        </span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-gray-500">
        对 AI 痕迹命中最密集的句子生成保留原意的口语化改写（最多 3 句），仅供改稿参考，
        发布前请自行核对事实与数字。
      </p>
      <Button
        variant="secondary"
        onClick={onGenerate}
        disabled={!canGenerate || loading}
        className="mt-3 w-full"
        data-generate-rewrite
      >
        <span className="flex items-center justify-center gap-1.5">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <PenLine size={14} />}
          {loading ? '生成中…' : '生成改写建议'}
        </span>
      </Button>
      {!canGenerate && !loading && !suggestions && !error && (
        <p className="mt-2 text-xs leading-5 text-gray-400">
          当前文稿没有命中 AI 高频词或套话连接词，暂无可改写的句子。
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs leading-5 text-red-600">
          {error}
        </p>
      )}
      {suggestions !== null && suggestions.length === 0 && !error && (
        <p className="mt-2 text-xs leading-5 text-gray-400">本次未生成可用的改写建议，可稍后再试。</p>
      )}
      {suggestions && suggestions.length > 0 && (
        <ul className="mt-3 grid gap-2.5">
          {suggestions.map((suggestion, index) => (
            <SuggestionItem key={`${index}-${suggestion.original}`} suggestion={suggestion} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** 一条建议：命中词徽标（紫色系，词来自服务端真实命中）+ 原句 → 改写句对照。 */
function SuggestionItem({ suggestion }: { suggestion: HumanizeRewriteSuggestion }) {
  return (
    <li className="rounded-sm border border-gray-100 bg-gray-50 p-2.5" data-humanize-suggestion>
      {suggestion.hit_words.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {suggestion.hit_words.map((word) => (
            <Badge key={word} tone="purple" className="rounded-sm">
              {word}
            </Badge>
          ))}
        </div>
      )}
      <p className="mt-1.5 text-xs leading-5 text-gray-500" data-humanize-original>
        {suggestion.original}
      </p>
      <p className="mt-1 flex items-start gap-1 text-[13px] font-bold leading-6 text-gray-900" data-humanize-rewritten>
        <ArrowRight size={14} className="mt-1 shrink-0 text-teal" />
        {suggestion.rewritten}
      </p>
    </li>
  );
}
