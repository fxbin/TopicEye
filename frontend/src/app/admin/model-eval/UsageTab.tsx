'use client';

/**
 * Usage tab（30 日用量统计 + 按模型/任务类型拆分）。
 *
 * 从 app/model-eval/page.tsx 抽出的 106 行组件，包含：
 * - 5 项总览 StatTile（Token/费用/缓存/调用/耗时）
 * - 刷新按钮
 * - 按模型拆分（带进度条 + InfoCell）
 * - 按任务类型拆分（按 estimated_cost 进度条）
 *
 * 状态由 page.tsx 传入：usage（ModelUsageSummary）/ loading（loading 中）。
 *
 * 7 个 UI 原子（Surface / Panel / Button / EmptyState / StatTile / InfoCell /
 * Toolbar）从 _components.tsx 复用。
 */

import React from 'react';
import {
  BarChart3,
  Clock3,
  Coins,
  FlaskConical,
  Gauge,
  KeyRound,
  Layers3,
  RefreshCw,
  SlidersHorizontal,
} from 'lucide-react';
import { EmptyState, LoadingState } from '@/components/StateView';
import { Button, Panel } from '@/components/ui';
import type { ModelUsageSummary } from '@/lib/api';
import {
  formatCurrency,
  formatTokens,
  promptTypeLabel,
} from './_model-eval-utils';
import { InfoCell, StatTile, Surface } from './_components';

export function UsageTab({
  usage,
  loading,
  onRefresh,
}: {
  usage: ModelUsageSummary | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  if (loading) {
    return (
      <Surface title="用量统计" icon={BarChart3}>
        <LoadingState minHeight="220px" />
      </Surface>
    );
  }

  if (!usage) {
    return (
      <Surface title="用量统计" icon={BarChart3}>
        <EmptyState panel={false} minHeight="220px" title="暂无用量数据" />
      </Surface>
    );
  }

  const maxModelTokens = Math.max(...usage.by_model.map((item) => item.tokens_input + item.tokens_output), 1);
  const maxPromptCost = Math.max(...usage.by_prompt.map((item) => item.estimated_cost), 0.000001);

  return (
    <div className="flex flex-col gap-3.5">
      <Surface title="30 日用量概览" icon={BarChart3} hint={`自 ${usage.since.slice(0, 10)} 起`}>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-5">
          <StatTile icon={Gauge} label="总 Token" value={formatTokens(usage.total.tokens_total)} hint={`输入 ${formatTokens(usage.total.tokens_input)} · 输出 ${formatTokens(usage.total.tokens_output)}`} tone="purple" />
          <StatTile icon={Coins} label="费用预估" value={formatCurrency(usage.total.estimated_cost)} hint="按模型配置单价估算" tone="primary" />
          <StatTile icon={KeyRound} label="缓存命中" value={formatTokens(usage.total.cache_read_tokens)} hint={`实际输入 ${formatTokens(usage.total.billable_input_tokens)}`} />
          <StatTile icon={FlaskConical} label="调用次数" value={usage.total.calls} hint={`${usage.total.success_calls} 成功 · ${usage.total.failed_calls} 失败`} tone="teal" />
          <StatTile icon={Clock3} label="平均耗时" value={`${usage.total.avg_duration_ms}ms`} hint={`成功率 ${(usage.total.success_rate * 100).toFixed(1)}%`} tone="amber" />
        </div>
        <div className="mt-3.5 flex justify-end">
          <Button type="button" variant="secondary" onClick={onRefresh} className="text-primary">
            <RefreshCw size={12} strokeWidth={2.2} />
            刷新用量
          </Button>
        </div>
      </Surface>

      <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-2">
        <Surface title="按模型拆分" icon={Layers3} hint={`${usage.by_model.length} 个模型`}>
          <div className="flex flex-col gap-2.5">
            {usage.by_model.length === 0 && <EmptyState panel={false} minHeight="220px" title="暂无模型调用记录" />}
            {usage.by_model.map((item) => {
              const totalTokens = item.tokens_input + item.tokens_output;
              const width = Math.max(4, Math.round((totalTokens / maxModelTokens) * 100));
              return (
                <Panel key={item.model_id ?? item.model_name} className="p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-black text-gray-900">{item.model_name}</div>
                      <div className="mt-1 text-[11px] text-gray-400">{item.provider || 'unknown'} · {item.calls} 次调用 · 平均 {item.avg_duration_ms}ms</div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="font-mono text-[13px] font-black text-primary">{formatCurrency(item.estimated_cost)}</div>
                      <div className="mt-1 text-[10px] text-gray-400">{formatTokens(totalTokens)} tokens</div>
                    </div>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-gray-100">
                    <div className="h-full rounded-full bg-[linear-gradient(90deg,var(--color-primary),var(--color-teal))]" style={{ width: `${width}%` }} />
                  </div>
                  <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <InfoCell label="输入" value={formatTokens(item.tokens_input)} />
                    <InfoCell label="输出" value={formatTokens(item.tokens_output)} />
                    <InfoCell label="成功" value={item.success_calls} />
                    <InfoCell label="失败" value={item.failed_calls} />
                  </div>
                </Panel>
              );
            })}
          </div>
        </Surface>

        <Surface title="按任务类型" icon={SlidersHorizontal} hint={`${usage.by_prompt.length} 类任务`}>
          <div className="flex flex-col gap-2.5">
            {usage.by_prompt.length === 0 && <EmptyState panel={false} minHeight="220px" title="暂无任务统计" />}
            {usage.by_prompt.map((item) => {
              const width = Math.max(4, Math.round((item.estimated_cost / maxPromptCost) * 100));
              return (
                <div key={item.prompt_type} className="border-b border-gray-100 pb-2.5 last:border-b-0">
                  <div className="flex justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-black text-gray-900">{promptTypeLabel[item.prompt_type] || item.prompt_type}</div>
                      <div className="mt-1 text-[11px] text-gray-400">{item.calls} 次 · {formatTokens(item.tokens_input + item.tokens_output)} tokens</div>
                    </div>
                    <div className="shrink-0 font-mono text-[13px] font-black text-primary">{formatCurrency(item.estimated_cost)}</div>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </Surface>
      </div>
    </div>
  );
}