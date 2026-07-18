'use client';

/**
 * History tab（测评历史记录 + 展开查看单次结果）。
 *
 * 从 app/model-eval/page.tsx 抽出的 28 行组件：
 * - useEffect 拉取最近 30 次测评运行
 * - 每条记录可展开查看所有模型的 status / duration / quality_score / auto_score
 *
 * 状态：runs（EvalRun[]）/ loading / expandedRun（当前展开的 runId）/
 * runDetail（展开的 EvalResult[]）。
 *
 * 5 个 UI 原子（Surface / LoadingState / EmptyState / StatusPill / Button）从
 * _components.tsx 复用。
 */

import React, { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import { EmptyState, LoadingState } from '@/components/StateView';
import { modelsApi } from '@/lib/api';
import type { EvalResult, EvalRun } from '@/lib/api';
import { cx } from '@/components/ui';
import { promptTypeLabel } from './_model-eval-utils';
import { StatusPill, Surface } from './_components';

export function HistoryTab() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<{ results: EvalResult[] } | null>(null);

  useEffect(() => {
    modelsApi.listEvalRuns(30).then((res) => {
      setRuns(res.runs);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const handleExpand = async (runId: string) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      return;
    }
    setExpandedRun(runId);
    const detail = await modelsApi.getEvalRun(runId);
    setRunDetail(detail);
  };

  if (loading) {
    return (
      <Surface title="测评历史" icon={History}>
        <LoadingState minHeight="220px" />
      </Surface>
    );
  }

  if (runs.length === 0) {
    return (
      <Surface title="测评历史" icon={History}>
        <EmptyState panel={false} minHeight="220px" title="暂无测评记录，去 A/B 测评页开始第一次测评" />
      </Surface>
    );
  }

  return (
    <Surface title="测评历史" icon={History} hint={`${runs.length} 条记录`}>
      <div className="flex flex-col gap-2">
        {runs.map((run) => (
          <div key={run.eval_run_id}>
            <button
              type="button"
              onClick={() => handleExpand(run.eval_run_id)}
              className="flex w-full items-center justify-between gap-3 rounded-sm border border-gray-200 bg-white px-4 py-3 text-left transition hover:border-primary-border"
            >
              <div className="min-w-0">
                <span className="text-[13px] font-black text-gray-900">{promptTypeLabel[run.prompt_type] || run.prompt_type}</span>
                <span className="ml-2 text-[11px] text-gray-400">
                  {run.model_count} 个模型 · {run.created_at?.slice(0, 19).replace('T', ' ')}
                </span>
              </div>
              <div className="flex shrink-0 gap-2">
                <StatusPill tone="teal">{run.done_count} 成功</StatusPill>
                {run.fail_count > 0 && <StatusPill tone="red">{run.fail_count} 失败</StatusPill>}
              </div>
            </button>
            {expandedRun === run.eval_run_id && runDetail && (
              <div className="rounded-b-sm border border-t-0 border-gray-200 bg-gray-50 px-4 py-2">
                {runDetail.results.map((r) => (
                  <div key={r.id} className="flex flex-wrap gap-3 border-b border-gray-100 py-2 last:border-b-0">
                    <span className="min-w-20 text-[13px] font-bold text-gray-800">{r.model_name}</span>
                    <span className={cx('text-xs', r.status === 'DONE' ? 'text-teal' : 'text-red')}>
                      {r.status} · {r.duration_ms}ms
                    </span>
                    {r.quality_score && <span className="text-xs text-primary">人工: {r.quality_score}/5</span>}
                    {r.auto_score !== null && <span className="text-xs text-gray-400">自动: {r.auto_score}/5</span>}
                    {r.error_message && <span className="text-[11px] text-red" title={r.error_message}>错误</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Surface>
  );
}