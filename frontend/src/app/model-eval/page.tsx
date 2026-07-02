'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  Beaker,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Coins,
  FlaskConical,
  Gauge,
  History,
  KeyRound,
  Layers3,
  Loader2,
  Play,
  Plus,
  Power,
  RefreshCw,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import { EmptyState, LoadingState } from '@/components/StateView';
import { modelsApi } from '@/lib/api';
import type {
  EvalResult,
  EvalRun,
  LlmModelItem,
  LlmModelPresetCatalog,
  LlmModelPresetItem,
  ModelUsageSummary,
} from '@/lib/api';
import {
  type Tab,
  type Tone,
  PROVIDER_PRESETS,
  promptTypeLabel,
  toneClasses,
  deepSeekPricingForModel,
  pricingForProviderModel,
  formatNumber,
  formatTokens,
  formatCurrency,
  formatPerMillion,
  formatPresetValue,
  presetRequires,
  presetNumberDefault,
  parameterMeta,
  parameterChangeHint,
  parseOptionalNumber,
} from './_model-eval-utils';
import {
  FieldLabel,
  InfoCell,
  SelectInput,
  StatTile,
  StatusPill,
  Surface,
  TextInput,
} from './_components';
import { ModelEditForm } from './ModelEditForm';
import { ModelsTab } from './ModelsTab';
import { EvaluateTab } from './EvaluateTab';

export default function ModelEvalPage() {
  const [tab, setTab] = useState<Tab>('models');
  const [models, setModels] = useState<LlmModelItem[]>([]);
  const [usage, setUsage] = useState<ModelUsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(true);

  const fetchModels = useCallback(async () => {
    try {
      const res = await modelsApi.list();
      setModels(res.models);
    } catch (e) {
      console.error('fetchModels', e);
    }
    setLoading(false);
  }, []);

  const fetchUsage = useCallback(async () => {
    try {
      setUsageLoading(true);
      const res = await modelsApi.usageSummary(30);
      setUsage(res);
    } catch (e) {
      console.error('fetchUsage', e);
    }
    setUsageLoading(false);
  }, []);

  const refreshAll = useCallback(() => {
    void fetchModels();
    void fetchUsage();
  }, [fetchModels, fetchUsage]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const enabledCount = models.filter((m) => m.enabled).length;
  const runnableCount = models.filter((m) => m.enabled && (m.api_key_set || !m.api_base)).length;
  const routeGroups = new Set(models.map((m) => m.routing_group || 'default')).size;
  const firstRouteModel = [...models]
    .filter((m) => m.enabled)
    .sort((a, b) => (a.routing_group || 'default').localeCompare(b.routing_group || 'default') || a.routing_priority - b.routing_priority || a.id - b.id)[0];

  const tabs: Array<{ key: Tab; label: string; desc: string; icon: LucideIcon }> = [
    { key: 'models', label: '模型配置', desc: '路由链、密钥和限流参数', icon: Settings2 },
    { key: 'evaluate', label: 'A/B 测评', desc: '多模型同题测试并人工评分', icon: FlaskConical },
    { key: 'usage', label: '用量统计', desc: 'Token 消耗和费用预估', icon: BarChart3 },
    { key: 'history', label: '测评历史', desc: '查看历史运行与评分记录', icon: History },
  ];

  return (
    <div className="mx-auto max-w-[1480px] px-4 py-6 pb-16 sm:px-6 lg:px-10">
      <Panel className="relative mb-4 overflow-hidden p-5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] sm:p-6">
        <div className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,var(--color-primary),var(--color-teal))]" />
        <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2.5">
              <Badge tone="primary" className="gap-1.5 font-mono">
                <BrainCircuit size={13} strokeWidth={2.4} />
                AI ENGINE
              </Badge>
              <span className="text-xs font-bold text-gray-500">模型配置与测评</span>
            </div>
            <h1 className="m-0 text-[28px] font-black leading-tight text-gray-900">AI 引擎工作台</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-7 text-gray-500">
              管理内容分析、日报、周刊和分类任务使用的模型，定期做 A/B 测评，保留人工评分作为模型选择依据。
            </p>
          </div>
          <Button type="button" variant="secondary" onClick={refreshAll} className="w-fit whitespace-nowrap">
            <RefreshCw size={14} strokeWidth={2.2} />
            刷新数据
          </Button>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
          <StatTile icon={Layers3} label="模型配置" value={models.length} hint={`${enabledCount} 个启用`} tone="primary" />
          <StatTile icon={KeyRound} label="可测模型" value={runnableCount} hint="具备调用条件" tone="teal" />
          <StatTile icon={ShieldCheck} label="路由组" value={routeGroups} hint="按组独立排序" tone="amber" />
          <StatTile icon={Clock3} label="首选路由" value={firstRouteModel ? `#${firstRouteModel.routing_priority}` : '-'} hint={firstRouteModel?.name || '未设置'} />
          <StatTile icon={Gauge} label="30日 Token" value={usage ? formatTokens(usage.total.tokens_total) : '-'} hint={`输入 ${formatTokens(usage?.total.tokens_input || 0)} · 输出 ${formatTokens(usage?.total.tokens_output || 0)}`} tone="purple" />
          <StatTile icon={Coins} label="费用预估" value={usage ? formatCurrency(usage.total.estimated_cost) : '-'} hint={`${usage?.total.calls || 0} 次模型调用`} tone="primary" />
        </div>
      </Panel>

      <div className="mb-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        {tabs.map((item) => {
          const Icon = item.icon;
          const active = tab === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={cx(
                'rounded-md border p-3.5 text-left transition',
                active ? 'border-primary-border bg-primary-light' : 'border-gray-200 bg-white hover:border-primary-border',
              )}
            >
              <div className="mb-1.5 flex items-center gap-2">
                <Icon size={15} className={active ? 'text-primary' : 'text-gray-500'} strokeWidth={2.2} />
                <span className={cx('text-[13px] font-black', active ? 'text-primary' : 'text-gray-800')}>{item.label}</span>
              </div>
              <div className="text-[11px] leading-4 text-gray-500">{item.desc}</div>
            </button>
          );
        })}
      </div>

      {loading ? (
        <Surface title="加载状态" icon={Beaker}>
          <LoadingState minHeight="220px" />
        </Surface>
      ) : (
        <>
          {tab === 'models' && <ModelsTab models={models} onRefresh={refreshAll} />}
          {tab === 'evaluate' && <EvaluateTab models={models} />}
          {tab === 'usage' && <UsageTab usage={usage} loading={usageLoading} onRefresh={fetchUsage} />}
          {tab === 'history' && <HistoryTab />}
        </>
      )}
    </div>
  );
}


function UsageTab({
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

function HistoryTab() {
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
