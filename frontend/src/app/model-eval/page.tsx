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

function ModelsTab({ models, onRefresh }: { models: LlmModelItem[]; onRefresh: () => void }) {
  const [editing, setEditing] = useState<LlmModelItem | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<Record<number, { status: string; response?: string; error?: string; duration_ms: number }>>({});
  const [showAdd, setShowAdd] = useState(false);

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      const res = await modelsApi.test(id);
      setTestResult((prev) => ({ ...prev, [id]: res }));
    } catch (e: unknown) {
      setTestResult((prev) => ({ ...prev, [id]: { status: 'failed', error: String(e), duration_ms: 0 } }));
    }
    setTesting(null);
  };

  const handleToggle = async (m: LlmModelItem) => {
    await modelsApi.update(m.id, { enabled: !m.enabled });
    onRefresh();
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除该模型配置？')) return;
    await modelsApi.delete(id);
    onRefresh();
  };

  const enabledCount = models.filter((m) => m.enabled).length;
  const keyedCount = models.filter((m) => m.api_key_set || !m.api_base).length;

  return (
    <div className="flex flex-col gap-3.5">
      <Surface title="模型配置" icon={Settings2} hint={`${models.length} 个模型 · ${enabledCount} 个启用 · ${keyedCount} 个可调用`}>
        <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
          <div className="text-[13px] leading-7 text-gray-500">
            维护运行时路由链、渠道分组和可参与测评的候选模型。禁用模型不会参与自动任务和 A/B 测评。
          </div>
          <Button type="button" variant="primary" onClick={() => setShowAdd(true)} className="w-fit whitespace-nowrap">
            <Plus size={14} strokeWidth={2.2} />
            添加模型
          </Button>
        </div>
      </Surface>

      {showAdd && <ModelEditForm onClose={() => { setShowAdd(false); onRefresh(); }} />}
      {editing && <ModelEditForm model={editing} onClose={() => { setEditing(null); onRefresh(); }} />}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {models.map((m) => (
          <Panel
            key={m.id}
            className={cx(
              'flex flex-col gap-3.5 p-4.5 transition',
              !m.enabled && 'opacity-60',
              m.enabled && m.routing_priority <= 10 && 'border-primary-border shadow-[0_12px_28px_rgba(255,107,53,0.08)]',
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  <StatusPill tone="neutral">#{m.routing_priority}</StatusPill>
                  {!m.enabled && <StatusPill>已禁用</StatusPill>}
                  {!m.api_key_set && m.api_base && <StatusPill tone="amber"><KeyRound size={11} />缺 Key</StatusPill>}
                </div>
                <div className="text-base font-black leading-5 text-gray-900">{m.name}</div>
                <div className="mt-1 truncate font-mono text-[11px] text-gray-400">{m.model_id}</div>
                {m.resolved_model !== m.model_id && (
                  <div className="mt-1 truncate font-mono text-[11px] text-primary">
                    实际请求 {m.resolved_model}
                  </div>
                )}
              </div>
              <StatusPill tone={m.enabled ? 'teal' : 'neutral'}>
                <Power size={11} />
                {m.enabled ? '启用' : '停用'}
              </StatusPill>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <InfoCell label="Provider" value={m.provider} />
              <InfoCell label="路由组" value={m.routing_group || 'default'} />
              <InfoCell label="模型族" value={m.model_family || '-'} muted={!m.model_family} />
              <InfoCell label="渠道" value={m.channel_name || '-'} muted={!m.channel_name} />
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <InfoCell label="稳定度" value={m.temperature} />
              <InfoCell label="输出长度" value={m.max_tokens} />
              <InfoCell label="请求/分" value={m.requests_per_minute} />
              <InfoCell label="冷却" value={`${m.cooldown_seconds}s`} />
            </div>

            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <InfoCell label="输入未命中" value={formatPerMillion(m.cost_per_1m_input)} muted={m.cost_per_1m_input === null || m.cost_per_1m_input === undefined} />
              <InfoCell label="输出单价" value={formatPerMillion(m.cost_per_1m_output)} muted={m.cost_per_1m_output === null || m.cost_per_1m_output === undefined} />
            </div>

            {m.cost_per_1m_input_cache_hit !== null && m.cost_per_1m_input_cache_hit !== undefined && (
              <div className="flex items-center justify-between gap-3 rounded-xs border border-teal-border bg-teal-light px-2.5 py-2 text-[11px]">
                <span className="font-black text-gray-500">输入缓存命中</span>
                <span className="font-mono font-black text-teal">{formatPerMillion(m.cost_per_1m_input_cache_hit)}</span>
              </div>
            )}

            {m.description && <div className="text-xs leading-5 text-gray-500">{m.description}</div>}

            {testResult[m.id] && (
              <div
                className={cx(
                  'truncate rounded-xs border px-2.5 py-2 text-[11px]',
                  testResult[m.id].status === 'success'
                    ? 'border-teal-border bg-teal-light text-teal'
                    : 'border-red-light bg-red-light text-red',
                )}
              >
                {testResult[m.id].status === 'success'
                  ? `${testResult[m.id].duration_ms}ms: ${(testResult[m.id].response || '').slice(0, 40)}...`
                  : `失败: ${(testResult[m.id].error || '').slice(0, 30)}`}
              </div>
            )}

            <Toolbar className="border-t border-gray-100 pt-3">
              <Button type="button" variant="secondary" onClick={() => handleToggle(m)}>{m.enabled ? '禁用' : '启用'}</Button>
              <Button type="button" variant="secondary" onClick={() => handleTest(m.id)} disabled={testing === m.id} className="text-primary">
                {testing === m.id ? '测试中...' : '测试'}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setEditing(m)}>编辑</Button>
              <Button type="button" variant="danger" onClick={() => handleDelete(m.id)}>
                <Trash2 size={12} strokeWidth={2.2} />
                删除
              </Button>
            </Toolbar>
          </Panel>
        ))}
      </div>

      {models.length === 0 && (
        <Surface title="空模型库" icon={Settings2}>
          <EmptyState panel={false} minHeight="220px" title="还没有配置任何模型，点击“添加模型”开始" />
        </Surface>
      )}
    </div>
  );
}

function ModelEditForm({ model, onClose }: { model?: LlmModelItem | null; onClose: () => void }) {
  const isEdit = !!model;
  const initialPreset = PROVIDER_PRESETS[model?.provider || 'openai'] || PROVIDER_PRESETS.openai;
  const [catalog, setCatalog] = useState<LlmModelPresetCatalog | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [presetKey, setPresetKey] = useState('deepseek_balanced');
  const [showAdvanced, setShowAdvanced] = useState(isEdit);
  const [form, setForm] = useState({
    name: model?.name || '',
    provider: model?.provider || '',
    model_id: model?.model_id || '',
    api_key: '',
    api_base: model?.api_base || '',
    routing_group: model?.routing_group || 'default',
    model_family: model?.model_family || '',
    channel_name: model?.channel_name || '',
    routing_priority: model?.routing_priority ?? 100,
    cooldown_seconds: model?.cooldown_seconds ?? 300,
    temperature: model?.temperature ?? 0.3,
    max_tokens: model?.max_tokens ?? 2000,
    requests_per_minute: model?.requests_per_minute ?? 30,
    description: model?.description || '',
    enabled: model?.enabled ?? true,
    cost_per_1m_input: model?.cost_per_1m_input?.toString() ?? initialPreset.costPer1MInput?.toString() ?? '',
    cost_per_1m_input_cache_hit: model?.cost_per_1m_input_cache_hit?.toString() ?? initialPreset.costPer1MInputCacheHit?.toString() ?? '',
    cost_per_1m_output: model?.cost_per_1m_output?.toString() ?? initialPreset.costPer1MOutput?.toString() ?? '',
  });
  const [saving, setSaving] = useState(false);
  const selectedPreset = useMemo(
    () => catalog?.presets.find((item) => item.key === presetKey),
    [catalog, presetKey],
  );
  const currentPreset = PROVIDER_PRESETS[form.provider] || PROVIDER_PRESETS.custom;
  const needsModelId = isEdit || presetRequires(selectedPreset, 'model_id') || presetKey === 'custom';
  const needsApiBase = presetRequires(selectedPreset, 'api_base') || presetKey === 'openai_compatible';
  const presetDefaultRows = useMemo(() => ([
    {
      label: '稳定度',
      field: 'temperature',
      value: selectedPreset?.defaults.temperature ?? catalog?.defaults.temperature ?? form.temperature,
    },
    {
      label: '输出长度',
      field: 'max_tokens',
      value: selectedPreset?.defaults.max_tokens ?? catalog?.defaults.max_tokens ?? form.max_tokens,
    },
    {
      label: '请求上限',
      field: 'requests_per_minute',
      value: selectedPreset?.defaults.requests_per_minute ?? catalog?.defaults.requests_per_minute ?? form.requests_per_minute,
    },
    {
      label: '失败冷却',
      field: 'cooldown_seconds',
      value: selectedPreset?.defaults.cooldown_seconds ?? catalog?.defaults.cooldown_seconds ?? form.cooldown_seconds,
    },
  ]), [catalog, form.cooldown_seconds, form.max_tokens, form.requests_per_minute, form.temperature, selectedPreset]);

  const applyPreset = useCallback((nextKey: string, nextCatalog: LlmModelPresetCatalog | null) => {
    const preset = nextCatalog?.presets.find((item) => item.key === nextKey);
    if (!preset) return;
    const defaults = preset.defaults || {};
    setPresetKey(nextKey);
    setForm((prev) => ({
      ...prev,
      name: '',
      provider: preset.provider,
      model_id: preset.model_id || '',
      api_base: preset.api_base || '',
      routing_group: String(defaults.routing_group || 'default'),
      model_family: preset.model_family || '',
      channel_name: preset.channel_name || '',
      routing_priority: presetNumberDefault(preset, nextCatalog, 'routing_priority', 100),
      cooldown_seconds: presetNumberDefault(preset, nextCatalog, 'cooldown_seconds', 300),
      temperature: presetNumberDefault(preset, nextCatalog, 'temperature', 0.3),
      max_tokens: presetNumberDefault(preset, nextCatalog, 'max_tokens', 2000),
      requests_per_minute: presetNumberDefault(preset, nextCatalog, 'requests_per_minute', 30),
      description: preset.description || '',
      enabled: true,
      cost_per_1m_input: defaults.cost_per_1m_input !== undefined && defaults.cost_per_1m_input !== null ? String(defaults.cost_per_1m_input) : '',
      cost_per_1m_input_cache_hit: defaults.cost_per_1m_input_cache_hit !== undefined && defaults.cost_per_1m_input_cache_hit !== null ? String(defaults.cost_per_1m_input_cache_hit) : '',
      cost_per_1m_output: defaults.cost_per_1m_output !== undefined && defaults.cost_per_1m_output !== null ? String(defaults.cost_per_1m_output) : '',
    }));
  }, []);

  const restoreRecommendedDefaults = useCallback(() => {
    setForm((prev) => ({
      ...prev,
      routing_priority: presetNumberDefault(selectedPreset, catalog, 'routing_priority', 100),
      cooldown_seconds: presetNumberDefault(selectedPreset, catalog, 'cooldown_seconds', 300),
      temperature: presetNumberDefault(selectedPreset, catalog, 'temperature', 0.3),
      max_tokens: presetNumberDefault(selectedPreset, catalog, 'max_tokens', 2000),
      requests_per_minute: presetNumberDefault(selectedPreset, catalog, 'requests_per_minute', 30),
    }));
  }, [catalog, selectedPreset]);

  useEffect(() => {
    let cancelled = false;
    setLoadingCatalog(true);
    modelsApi.presets()
      .then((res) => {
        if (cancelled) return;
        setCatalog(res);
        if (isEdit) return;
        const nextKey = res.presets.some((item) => item.key === presetKey) ? presetKey : res.presets[0]?.key || 'custom';
        applyPreset(nextKey, res);
      })
      .catch((e) => {
        console.error('fetchModelPresets', e);
        if (!cancelled && !isEdit) {
          setForm((prev) => ({
            ...prev,
            provider: prev.provider || 'openai',
            api_base: prev.api_base || PROVIDER_PRESETS.openai.baseUrl,
            requests_per_minute: prev.requests_per_minute || 30,
          }));
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingCatalog(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyPreset, isEdit]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = { ...form };
      if (!isEdit) payload.preset_key = presetKey;
      payload.cost_per_1m_input = parseOptionalNumber(form.cost_per_1m_input);
      payload.cost_per_1m_input_cache_hit = parseOptionalNumber(form.cost_per_1m_input_cache_hit);
      payload.cost_per_1m_output = parseOptionalNumber(form.cost_per_1m_output);
      if (!payload.name) delete payload.name;
      if (!payload.api_key) delete payload.api_key;
      if (!payload.api_base) delete payload.api_base;
      if (!payload.model_family) delete payload.model_family;
      if (!payload.channel_name) delete payload.channel_name;
      if (!payload.description) delete payload.description;
      if (isEdit && model) {
        await modelsApi.update(model.id, payload);
      } else {
        await modelsApi.create(payload);
      }
      onClose();
    } catch (e) {
      alert('保存失败: ' + String(e));
    }
    setSaving(false);
  };

  const handleProviderChange = (provider: string) => {
    const preset = PROVIDER_PRESETS[provider] || PROVIDER_PRESETS.custom;
    const pricing = pricingForProviderModel(provider, form.model_id);
    setForm((f) => ({
      ...f,
      provider,
      api_base: preset.baseUrl,
      cost_per_1m_input: pricing?.input?.toString() ?? f.cost_per_1m_input,
      cost_per_1m_input_cache_hit: pricing?.cacheHit?.toString() ?? f.cost_per_1m_input_cache_hit,
      cost_per_1m_output: pricing?.output?.toString() ?? f.cost_per_1m_output,
    }));
  };

  const handleModelIdChange = (modelId: string) => {
    const pricing = pricingForProviderModel(form.provider, modelId);
    setForm((f) => ({
      ...f,
      model_id: modelId,
      ...(pricing ? {
        cost_per_1m_input: pricing.input?.toString() ?? f.cost_per_1m_input,
        cost_per_1m_input_cache_hit: pricing.cacheHit?.toString() ?? f.cost_per_1m_input_cache_hit,
        cost_per_1m_output: pricing.output?.toString() ?? f.cost_per_1m_output,
      } : {}),
    }));
  };

  const saveDisabled = saving
    || loadingCatalog
    || (isEdit && (!form.name || !form.provider || !form.model_id))
    || (!isEdit && (!form.provider || !form.model_id || (needsModelId && !form.model_id)));

  return (
    <Panel className="border-primary-border p-5 shadow-[0_12px_28px_rgba(255,107,53,0.08)]">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2">
            <Settings2 size={15} className="text-primary" strokeWidth={2.2} />
            <h3 className="m-0 text-sm font-black text-gray-900">{isEdit ? '编辑模型' : '添加模型'}</h3>
          </div>
          <div className="text-xs leading-5 text-gray-500">
            {isEdit ? '修改已有模型配置。API Key 留空时不会覆盖原密钥。' : '推荐先选预设，只填写 API Key；参数默认值已经内置。'}
          </div>
        </div>
        {!isEdit && catalog?.help.beginner_tip && (
          <div className="max-w-[420px] rounded-xs border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal">
            {catalog.help.beginner_tip}
          </div>
        )}
      </div>

      {!isEdit && (
        <div className="mb-4">
          {loadingCatalog ? (
            <div className="flex min-h-[112px] items-center justify-center gap-2 rounded-sm border border-gray-200 bg-gray-50 text-sm font-bold text-gray-500">
              <Loader2 size={15} className="animate-spin" />
              正在加载模型预设
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {catalog?.presets.map((preset) => {
                const active = preset.key === presetKey;
                return (
                  <button
                    key={preset.key}
                    type="button"
                    onClick={() => applyPreset(preset.key, catalog)}
                    className={cx(
                      'min-h-[126px] rounded-sm border bg-white p-3 text-left transition',
                      active ? 'border-primary-border bg-primary-light' : 'border-gray-200 hover:border-primary-border',
                    )}
                  >
                    <div className="mb-2 flex items-start justify-between gap-2">
                      <div className={cx('text-sm font-black', active ? 'text-primary' : 'text-gray-900')}>{preset.label}</div>
                      {active && <CheckCircle2 size={16} className="shrink-0 text-primary" />}
                    </div>
                    <div className="text-xs leading-5 text-gray-500">{preset.description}</div>
                    <div className="mt-2 grid grid-cols-2 gap-1.5">
                      {['temperature', 'max_tokens'].map((field) => (
                        <span key={field} className="rounded-xs bg-white px-2 py-1 text-[10px] font-black text-gray-500">
                          {catalog?.parameter_help?.[field]?.label || field} {formatPresetValue(preset.defaults[field] ?? catalog?.defaults[field])}
                        </span>
                      ))}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {preset.recommended_for.slice(0, 3).map((item) => (
                        <span key={item} className="rounded-full bg-white px-2 py-0.5 text-[10px] font-black text-gray-500">
                          {item}
                        </span>
                      ))}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {selectedPreset && (
        <div className="mb-4 grid gap-3 rounded-sm border border-gray-200 bg-gray-50 p-3 md:grid-cols-[minmax(0,1.15fr)_minmax(0,2fr)]">
          <div className="min-w-0">
            <div className="mb-1 text-xs font-black text-gray-500">推荐配置</div>
            <div className="truncate text-sm font-black text-gray-900">{selectedPreset.label}</div>
            <div className="mt-1 text-xs leading-5 text-gray-500">
              {catalog?.help.defaults_tip || '不理解参数时先保持默认，系统会自动使用推荐值。'}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {presetDefaultRows.map((item) => (
              <div key={item.field} className="rounded-xs border border-gray-200 bg-white px-2.5 py-2">
                <div className="mb-1 text-[10px] font-black text-gray-400">{item.label}</div>
                <div className="font-mono text-sm font-black text-gray-900">{formatPresetValue(item.value)}</div>
                <div className="mt-1 truncate text-[10px] text-gray-400">
                  {catalog?.parameter_help?.[item.field]?.beginner || '默认即可'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div>
          <FieldLabel>API Key {isEdit ? '(留空不修改)' : ''}</FieldLabel>
          <TextInput type="password" value={form.api_key} onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="粘贴供应商 API Key" autoComplete="off" />
        </div>
        <div>
          <FieldLabel>{isEdit ? '显示名称 *' : '显示名称'}</FieldLabel>
          <TextInput value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder={selectedPreset?.defaults.name ? String(selectedPreset.defaults.name) : '不填则使用预设名称'} />
        </div>
        {(needsModelId || showAdvanced) && (
          <div>
            <FieldLabel>Model ID {needsModelId ? '*' : ''}</FieldLabel>
            <TextInput value={form.model_id} onChange={(e) => handleModelIdChange(e.target.value)} placeholder={selectedPreset?.model_id || selectedPreset?.model_id_placeholder || `如 ${currentPreset.modelPlaceholder}`} />
            <div className="mt-1 text-[10px] leading-4 text-gray-400">可填裸模型名，也可直接填完整 LiteLLM 路由。</div>
          </div>
        )}
        {(needsApiBase || showAdvanced) && (
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <FieldLabel>API Base URL {needsApiBase ? '*' : ''}</FieldLabel>
              {currentPreset.baseUrl && (
                <button
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, api_base: currentPreset.baseUrl }))}
                  className="rounded-full border border-primary-border bg-primary-light px-2 py-0.5 text-[10px] font-black text-primary"
                >
                  使用内置
                </button>
              )}
            </div>
            <TextInput value={form.api_base} onChange={(e) => setForm((f) => ({ ...f, api_base: e.target.value }))} placeholder={selectedPreset?.api_base_placeholder || 'https://api.example.com/v1'} />
            {currentPreset.baseUrl && <div className="mt-1 text-[10px] leading-4 text-gray-400">内置默认：{currentPreset.baseUrl}</div>}
            {!currentPreset.baseUrl && <div className="mt-1 text-[10px] leading-4 text-gray-400">OpenAI 兼容网关通常填写 /v1 结尾的地址。</div>}
          </div>
        )}
        <div>
          <FieldLabel>描述</FieldLabel>
          <TextInput value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} placeholder="可选备注" />
        </div>
        <div className="grid grid-cols-3 gap-2 rounded-xs border border-gray-200 bg-gray-50 p-2.5">
          <InfoCell label="稳定度" value={formatPresetValue(form.temperature)} />
          <InfoCell label="输出长度" value={formatPresetValue(form.max_tokens)} />
          <InfoCell label="请求/分" value={formatPresetValue(form.requests_per_minute)} />
        </div>
      </div>

      <div className="mt-3">
        <button
          type="button"
          onClick={() => setShowAdvanced((value) => !value)}
          className="inline-flex items-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-600 transition hover:border-primary-border hover:text-primary"
        >
          <SlidersHorizontal size={14} />
          {showAdvanced ? '收起专家参数' : '专家参数'}
        </button>
        <button
          type="button"
          onClick={restoreRecommendedDefaults}
          className="inline-flex items-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-600 transition hover:border-primary-border hover:text-primary"
        >
          <RefreshCw size={14} />
          恢复推荐默认
        </button>
        {selectedPreset?.help && !showAdvanced && (
          <span className="ml-2 align-middle text-xs font-bold text-gray-500">{selectedPreset.help}</span>
        )}
        {!showAdvanced && (
          <span className="ml-2 align-middle text-xs font-bold text-teal">
            保持收起时使用推荐默认参数。
          </span>
        )}
      </div>

      {showAdvanced && (
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
          <div className="rounded-xs border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal lg:col-span-2">
            {catalog?.help.advanced_tip || '这些参数只在你明确知道要调整模型行为时再改；不确定时点“恢复推荐默认”。'}
          </div>
          <div>
            <FieldLabel>Provider *</FieldLabel>
            <SelectInput value={form.provider || 'openai'} onChange={(e) => handleProviderChange(e.target.value)}>
              {Object.entries(PROVIDER_PRESETS).map(([value, preset]) => (
                <option key={value} value={value}>{preset.label}</option>
              ))}
            </SelectInput>
          </div>
          <div>
            <FieldLabel>路由组</FieldLabel>
            <TextInput value={form.routing_group} onChange={(e) => setForm((f) => ({ ...f, routing_group: e.target.value || 'default' }))} placeholder="default" />
          </div>
          <div>
            <FieldLabel>路由优先级</FieldLabel>
            <TextInput type="number" value={form.routing_priority} onChange={(e) => setForm((f) => ({ ...f, routing_priority: parseInt(e.target.value, 10) || 100 }))} />
          </div>
          <div>
            <FieldLabel>失败冷却秒数</FieldLabel>
            <TextInput type="number" value={form.cooldown_seconds} onChange={(e) => setForm((f) => ({ ...f, cooldown_seconds: parseInt(e.target.value, 10) || 300 }))} />
            <div className="mt-1 text-[10px] leading-4 text-gray-400">
              <span className="font-bold text-gray-500">{parameterMeta(catalog, 'cooldown_seconds')}</span>
              <br />
              {catalog?.parameter_help?.cooldown_seconds?.plain || catalog?.help.cooldown_tip || '失败后暂停一段时间再重试。'}
              {parameterChangeHint(catalog, 'cooldown_seconds') && (
                <>
                  <br />
                  {parameterChangeHint(catalog, 'cooldown_seconds')}
                </>
              )}
            </div>
          </div>
          <div>
            <FieldLabel>模型家族</FieldLabel>
            <TextInput value={form.model_family} onChange={(e) => setForm((f) => ({ ...f, model_family: e.target.value }))} placeholder="如 deepseek / qwen / glm" />
          </div>
          <div>
            <FieldLabel>渠道名</FieldLabel>
            <TextInput value={form.channel_name} onChange={(e) => setForm((f) => ({ ...f, channel_name: e.target.value }))} placeholder="如 official / opencode / openrouter" />
          </div>
          <div>
            <FieldLabel>稳定度</FieldLabel>
            <TextInput type="number" step="0.1" value={form.temperature} onChange={(e) => setForm((f) => ({ ...f, temperature: parseFloat(e.target.value) || 0.3 }))} />
            <div className="mt-1 text-[10px] leading-4 text-gray-400">
              <span className="font-bold text-gray-500">{parameterMeta(catalog, 'temperature')}</span>
              <br />
              {catalog?.parameter_help?.temperature?.plain || catalog?.help.temperature_tip || '越低越稳定，分析和摘要通常用 0.2-0.4。'}
              {parameterChangeHint(catalog, 'temperature') && (
                <>
                  <br />
                  {parameterChangeHint(catalog, 'temperature')}
                </>
              )}
            </div>
          </div>
          <div>
            <FieldLabel>输出长度</FieldLabel>
            <TextInput type="number" value={form.max_tokens} onChange={(e) => setForm((f) => ({ ...f, max_tokens: parseInt(e.target.value, 10) || 2000 }))} />
            <div className="mt-1 text-[10px] leading-4 text-gray-400">
              <span className="font-bold text-gray-500">{parameterMeta(catalog, 'max_tokens')}</span>
              <br />
              {catalog?.parameter_help?.max_tokens?.plain || catalog?.help.max_tokens_tip || '控制单次输出长度。'}
              {parameterChangeHint(catalog, 'max_tokens') && (
                <>
                  <br />
                  {parameterChangeHint(catalog, 'max_tokens')}
                </>
              )}
            </div>
          </div>
          <div>
            <FieldLabel>每分钟请求数</FieldLabel>
            <TextInput type="number" value={form.requests_per_minute} onChange={(e) => setForm((f) => ({ ...f, requests_per_minute: parseInt(e.target.value, 10) || 30 }))} />
            <div className="mt-1 text-[10px] leading-4 text-gray-400">
              <span className="font-bold text-gray-500">{parameterMeta(catalog, 'requests_per_minute')}</span>
              <br />
              {catalog?.parameter_help?.requests_per_minute?.plain || catalog?.help.rpm_tip || '每分钟请求数。个人 Key 建议从 10-30 开始。'}
              {parameterChangeHint(catalog, 'requests_per_minute') && (
                <>
                  <br />
                  {parameterChangeHint(catalog, 'requests_per_minute')}
                </>
              )}
            </div>
          </div>
          <div>
            <FieldLabel>输入未命中单价 / 百万 Tokens</FieldLabel>
            <TextInput type="number" step="0.001" value={form.cost_per_1m_input} onChange={(e) => setForm((f) => ({ ...f, cost_per_1m_input: e.target.value }))} placeholder="如 1" />
          </div>
          <div>
            <FieldLabel>输出单价 / 百万 Tokens</FieldLabel>
            <TextInput type="number" step="0.001" value={form.cost_per_1m_output} onChange={(e) => setForm((f) => ({ ...f, cost_per_1m_output: e.target.value }))} placeholder="如 2" />
          </div>
          <div>
            <FieldLabel>输入缓存命中 / 百万 Tokens</FieldLabel>
            <TextInput type="number" step="0.001" value={form.cost_per_1m_input_cache_hit} onChange={(e) => setForm((f) => ({ ...f, cost_per_1m_input_cache_hit: e.target.value }))} placeholder="如 0.02" />
          </div>
          <div className="flex items-end">
            <div className={cx('w-full rounded-xs border px-2.5 py-2 text-[11px] leading-4', currentPreset.pricingNote ? 'border-teal-border bg-teal-light text-teal' : 'border-gray-200 bg-gray-50 text-gray-400')}>
              {currentPreset.pricingNote || '费用估算按输入未命中价和输出价计算。'}
            </div>
          </div>
        </div>
      )}

      <Toolbar className="mt-4">
        <Button type="button" variant="primary" onClick={handleSave} disabled={saveDisabled}>
          {saving ? <Loader2 size={14} className="animate-spin" /> : null}
          {saving ? '保存中...' : '保存'}
        </Button>
        <Button type="button" variant="secondary" onClick={onClose}>取消</Button>
      </Toolbar>
    </Panel>
  );
}

function EvaluateTab({ models }: { models: LlmModelItem[] }) {
  const enabledModels = useMemo(() => models.filter((m) => m.enabled), [models]);
  const runnableModelIds = useMemo(
    () => new Set(enabledModels.filter((m) => m.api_key_set || !m.api_base).map((m) => m.id)),
    [enabledModels],
  );
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [promptType, setPromptType] = useState('analysis');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ eval_run_id: string; results: EvalResult[] } | null>(null);
  const [scoringId, setScoringId] = useState<number | null>(null);

  useEffect(() => {
    setSelected((prev) => new Set([...prev].filter((id) => runnableModelIds.has(id))));
  }, [runnableModelIds]);

  const toggleModel = (id: number) => {
    if (!runnableModelIds.has(id)) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleRun = async () => {
    if (selected.size < 2) {
      alert('至少选择 2 个模型进行对比');
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const res = await modelsApi.runEvaluation({
        model_ids: [...selected],
        prompt_type: promptType,
      });
      const detail = await modelsApi.getEvalRun(res.eval_run_id);
      setResult(detail);
    } catch (e) {
      alert('测评失败: ' + String(e));
    }
    setRunning(false);
  };

  const handleScore = async (evalId: number, score: number) => {
    setScoringId(evalId);
    try {
      await modelsApi.scoreEvaluation(evalId, score);
      if (result) {
        setResult({
          ...result,
          results: result.results.map((r) => (r.id === evalId ? { ...r, quality_score: score } : r)),
        });
      }
    } catch (e) {
      alert('评分失败: ' + String(e));
    } finally {
      setScoringId(null);
    }
  };

  const promptTypes = [
    { value: 'analysis', label: '选题分析' },
    { value: 'daily_report', label: 'AI 日报' },
    { value: 'weekly_digest', label: 'AI 周刊' },
    { value: 'classification', label: '内容分类' },
  ];

  return (
    <div className="flex flex-col gap-3.5">
      <Surface title="选择测评模型" icon={Layers3} hint={`${selected.size} / ${runnableModelIds.size} 已选`}>
        <Toolbar>
          {enabledModels.map((m) => {
            const runnable = runnableModelIds.has(m.id);
            const active = selected.has(m.id);
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => toggleModel(m.id)}
                disabled={!runnable}
                title={runnable ? undefined : '该模型缺少 API Key，暂不能参与测评'}
                className={cx(
                  'rounded-sm border px-3 py-2 text-[13px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50',
                  active ? 'border-primary bg-primary-light text-primary' : 'border-gray-200 bg-white text-gray-600 hover:border-primary-border',
                )}
              >
                {m.name}
                {!runnable && <span className="ml-1 text-[10px]">(缺 Key)</span>}
              </button>
            );
          })}
        </Toolbar>
        {selected.size < 2 && <div className="mt-2 text-xs text-amber">请至少选择 2 个模型</div>}
      </Surface>

      <Surface title="测评任务" icon={FlaskConical}>
        <Toolbar className="mb-4">
          {promptTypes.map((pt) => (
            <button
              key={pt.value}
              type="button"
              onClick={() => setPromptType(pt.value)}
              className={cx(
                'rounded-xs border px-3 py-1.5 text-[13px] font-bold transition',
                promptType === pt.value ? 'border-primary bg-primary-light text-primary' : 'border-gray-200 bg-white text-gray-600 hover:border-primary-border',
              )}
            >
              {pt.label}
            </button>
          ))}
        </Toolbar>

        <Button type="button" variant="primary" onClick={handleRun} disabled={running || selected.size < 2} className="px-5 text-sm">
          <Play size={15} strokeWidth={2.2} />
          {running ? '测评进行中...' : '开始 A/B 测评'}
        </Button>
      </Surface>

      {result && (
        <Surface title="测评结果" icon={CheckCircle2} hint={result.eval_run_id}>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {result.results.map((r) => (
              <Panel key={r.id} className={cx('flex flex-col gap-2 p-4', r.status === 'DONE' ? 'border-teal-border' : 'border-red-light')}>
                <div className="flex items-center justify-between gap-3">
                  <div className="truncate text-sm font-black text-gray-900">{r.model_name}</div>
                  <StatusPill tone={r.status === 'DONE' ? 'teal' : 'red'}>{r.status === 'DONE' ? '完成' : '失败'}</StatusPill>
                </div>
                <div className="text-xs text-gray-500">{r.status === 'DONE' ? `${r.duration_ms}ms` : r.error_message?.slice(0, 60)}</div>
                {r.tokens_input !== null && (
                  <div className="inline-flex items-center gap-1.5 text-[11px] text-gray-400">
                    Token: {r.tokens_input}
                    <ArrowRight size={12} strokeWidth={2} />
                    {r.tokens_output}
                  </div>
                )}
                {r.response_text && (
                  <div className="max-h-[200px] overflow-auto whitespace-pre-wrap rounded-xs bg-gray-50 p-2.5 text-xs leading-5 text-gray-700">
                    {r.response_text}
                  </div>
                )}
                {r.auto_score !== null && <div className="text-[11px] text-gray-500">自动评分: {r.auto_score}/5</div>}
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-gray-500">人工评分:</span>
                  {[1, 2, 3, 4, 5].map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => handleScore(r.id, s)}
                      disabled={scoringId === r.id}
                      className={cx(
                        'h-7 w-7 rounded-xs border text-sm transition disabled:cursor-wait disabled:opacity-60',
                        r.quality_score === s ? 'border-primary bg-primary-light text-primary' : 'border-gray-200 bg-white text-gray-500 hover:border-primary-border',
                      )}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </Panel>
            ))}
          </div>
        </Surface>
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
