'use client';

import { useEffect, useRef, useState } from 'react';
import { Compass, Lightbulb, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import { angleRefHref, createEventAngleAnalysisController } from '@/lib/event-angle-analysis';
import type { AngleAnalysisState } from '@/lib/event-angle-analysis';

/**
 * 事件切面稀缺度分析（AI 角度缺口建议）。
 *
 * 挂在 EventCoverage 展开区尾部；每次点击重新请求（「刷新即重算」），
 * 不落任何本地持久化。错误显式展示并支持重试，不安静吞错。
 */
export default function EventAngleAnalysis({ contentId }: { contentId: number }) {
  const [state, setState] = useState<AngleAnalysisState>({ analysis: null, loading: false, error: null });
  const controller = useRef<ReturnType<typeof createEventAngleAnalysisController> | null>(null);

  useEffect(() => {
    const current = createEventAngleAnalysisController(contentId, contentsApi.analyzeEventAngles, setState);
    controller.current = current;
    return () => {
      current.cancel();
      controller.current = null;
    };
  }, [contentId]);

  const analysis = state.analysis;
  const hasResult = analysis !== null;

  return (
    <div className="border-t border-gray-100 px-3 py-2.5" onClick={event => event.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={state.loading}
          onClick={() => void controller.current?.run()}
          className="inline-flex min-h-8 items-center gap-1.5 rounded-xs border border-amber-border bg-amber-light px-2.5 py-1 text-xs font-semibold text-amber transition hover:border-amber disabled:opacity-60"
        >
          {state.loading ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Compass size={13} className="shrink-0" aria-hidden="true" />}
          {state.loading ? '分析中…' : hasResult ? '重新分析' : '切面分析'}
        </button>
        {!state.loading && !hasResult && <span className="text-[11px] text-gray-500">AI 找出这个事件还没人写的角度</span>}
        {!state.loading && hasResult && analysis?.status === 'ok' && (
          <span className="text-[11px] text-gray-500">
            基于该事件 {analysis.analyzed_count} 篇报道{analysis.truncated ? '（超 30 篇，已取最新 30 篇）' : ''}
          </span>
        )}
      </div>

      {state.error && (
        <p className="mt-1.5 text-xs text-red" role="alert">
          {state.error}
          <button
            type="button"
            disabled={state.loading}
            onClick={() => void controller.current?.run()}
            className="ml-1.5 inline-flex items-center gap-1 font-semibold hover:underline"
          >
            <RefreshCw size={11} aria-hidden="true" /> 重试
          </button>
        </p>
      )}

      {hasResult && analysis?.status === 'no_event' && (
        <p className="mt-1.5 text-xs text-gray-600">该报道没有已归并的同事件报道，暂无法做切面分析。</p>
      )}

      {hasResult && analysis?.status === 'ok' && (
        <div className="mt-2 space-y-2.5" aria-label="切面稀缺度分析结果">
          {analysis.covered_angles.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold text-gray-500">已覆盖角度</div>
              <div className="flex flex-wrap gap-1">
                {analysis.covered_angles.map(angle => (
                  <span key={angle} className="rounded-xs bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
                    {angle}
                  </span>
                ))}
              </div>
            </div>
          )}

          {analysis.scarce_angles.length > 0 ? (
            <div>
              <div className="mb-1 text-[11px] font-semibold text-teal-text">稀缺角度（值得写）</div>
              <div className="space-y-1.5">
                {analysis.scarce_angles.map(item => (
                  <div key={item.angle} className="rounded-xs bg-teal/5 px-2.5 py-1.5">
                    <div className="text-xs font-semibold text-teal-text">{item.angle}</div>
                    {item.reason && <p className="mt-0.5 text-[11px] leading-5 text-gray-600">{item.reason}</p>}
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {item.refs.map(ref => (
                        <a
                          key={ref.content_id}
                          href={angleRefHref(ref)}
                          className="min-h-6 rounded-xs border border-gray-200 bg-white px-1.5 py-0.5 text-[11px] text-gray-700 no-underline transition hover:border-primary-border hover:text-primary-text"
                        >
                          {ref.title}
                        </a>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-[11px] text-gray-500">模型没有找到有把握的稀缺角度。</p>
          )}

          {analysis.audience_questions.length > 0 && (
            <div>
              <div className="mb-1 inline-flex items-center gap-1 text-[11px] font-semibold text-amber-700">
                <Lightbulb size={12} aria-hidden="true" /> 受众还想问
              </div>
              <ul className="list-inside list-disc space-y-0.5 text-[11px] leading-5 text-gray-600">
                {analysis.audience_questions.map(question => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </div>
          )}

          <p className="inline-flex items-center gap-1 text-[10px] text-gray-400">
            <Sparkles size={11} aria-hidden="true" /> AI 生成，角度与引用仅供参考
          </p>
        </div>
      )}
    </div>
  );
}
