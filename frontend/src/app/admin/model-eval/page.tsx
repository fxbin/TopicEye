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
import { AdminPageShell, AdminPageHeader } from '@/components/admin-ui';
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
import { UsageTab } from './UsageTab';
import { HistoryTab } from './HistoryTab';

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
    <AdminPageShell maxWidth={1480}>
      {/* Header */}
      <Panel className="overflow-hidden p-5 sm:p-6">
        <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <AdminPageHeader
              title="AI 引擎工作台"
              icon={BrainCircuit}
              description="管理内容分析、日报、周刊和分类任务使用的模型，定期做 A/B 测评，保留人工评分作为模型选择依据。"
            />
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
    </AdminPageShell>
  );
}


