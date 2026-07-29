'use client';

/**
 * 模型编辑表单（add/edit 双模式，AdminModal 弹窗承载）。
 *
 * 从 app/model-eval/page.tsx 抽出的组件，v2 交互改版：
 * - 承载形态：内联 Panel 改为 AdminModal 弹窗，内容区独立滚动，底部操作栏常驻
 * - 预设选择（4 个供应商 + 高级 LiteLLM 路由）
 * - API Key / Base URL / Model ID / 显示名称
 * - 路由参数（priority / cooldown / routing group / family / channel）
 * - 性能参数（temperature / max_tokens / rpm）
 * - 费用参数（input / output / cache hit 每百万 tokens 单价）
 * - 推荐参数 hint + restore defaults 按钮
 *
 * 交互约定：
 * - 必填校验失败时字段下方红字提示（首次点击保存后显示），不再静默禁用保存按钮
 * - 保存失败在表单内错误条展示，不再使用浏览器 alert()
 * - 切换预设保留已填写的显示名称与 API Key
 * - 编辑模式跳过预设目录拉取，打开即可保存
 * - 有未保存修改时关闭需二次确认（内联确认条）
 * - onClose(saved, createdId)：保存成功时 saved=true，新增成功时附带 createdId
 *   供调用方自动触发连接测试；取消时无参数
 *
 * 状态：catalog（拉取预设）/ presetKey / form（17 字段）/ saving /
 * saveError / submitAttempted / dirty / confirmDiscard。
 * ModelsTab 用此组件实现"添加模型"和"编辑模型"两种模式。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Loader2,
  RefreshCw,
  SlidersHorizontal,
} from 'lucide-react';
import { Button, cx } from '@/components/ui';
import { AdminModal, AdminModalFooter } from '@/components/admin-ui';
import { FieldLabel, InfoCell, SelectInput, TextInput } from './_components';
import { modelsApi } from '@/lib/api';
import type { LlmModelItem, LlmModelPresetCatalog } from '@/lib/api';
import {
  PROVIDER_PRESETS,
  formatPresetValue,
  parameterChangeHint,
  parameterMeta,
  parseOptionalNumber,
  presetNumberDefault,
  presetRequires,
  pricingForProviderModel,
} from './_model-eval-utils';

/** 弹窗内容区最大高度：为标题、副标题与底部操作栏预留视口空间 */
const MODAL_BODY_MAX_HEIGHT = '62vh';
/** 弹窗宽度：兼顾预设卡片双列排布与表单字段密度 */
const MODAL_MAX_WIDTH = 720;

export function ModelEditForm({ model, onClose }: { model?: LlmModelItem | null; onClose: (saved?: boolean, createdId?: number) => void }) {
  const isEdit = !!model;
  const initialPreset = PROVIDER_PRESETS[model?.provider || 'openai'] || PROVIDER_PRESETS.openai;
  const [catalog, setCatalog] = useState<LlmModelPresetCatalog | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(!isEdit);
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
  const [saveError, setSaveError] = useState('');
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
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

  /**
   * 用户输入统一入口：任何字段编辑都会标记表单为脏，并清除上一次的保存错误，
   * 供关闭时的放弃确认使用。程序化变更（初始化预设、恢复默认）不经过此入口。
   */
  const patchForm = (patch: Partial<typeof form>) => {
    setDirty(true);
    setSaveError('');
    setForm((prev) => ({ ...prev, ...patch }));
  };

  const applyPreset = useCallback((nextKey: string, nextCatalog: LlmModelPresetCatalog | null) => {
    const preset = nextCatalog?.presets.find((item) => item.key === nextKey);
    if (!preset) return;
    const defaults = preset.defaults || {};
    setPresetKey(nextKey);
    setForm((prev) => ({
      ...prev,
      name: prev.name,
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
    setDirty(true);
    setSaveError('');
    setForm((prev) => ({
      ...prev,
      routing_priority: presetNumberDefault(selectedPreset, catalog, 'routing_priority', 100),
      cooldown_seconds: presetNumberDefault(selectedPreset, catalog, 'cooldown_seconds', 300),
      temperature: presetNumberDefault(selectedPreset, catalog, 'temperature', 0.3),
      max_tokens: presetNumberDefault(selectedPreset, catalog, 'max_tokens', 2000),
      requests_per_minute: presetNumberDefault(selectedPreset, catalog, 'requests_per_minute', 30),
    }));
  }, [catalog, selectedPreset]);

  const handlePresetSelection = (nextKey: string) => {
    // 初始化目录时的 applyPreset 不应触发放弃确认；只有用户主动选择才算修改。
    setDirty(true);
    setSaveError('');
    applyPreset(nextKey, catalog);
  };

  useEffect(() => {
    if (isEdit) return;
    let cancelled = false;
    setLoadingCatalog(true);
    modelsApi.presets()
      .then((res) => {
        if (cancelled) return;
        setCatalog(res);
        const nextKey = res.presets.some((item) => item.key === presetKey) ? presetKey : res.presets[0]?.key || 'custom';
        applyPreset(nextKey, res);
      })
      .catch((e) => {
        console.error('fetchModelPresets', e);
        if (!cancelled) {
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

  /**
   * 必填字段校验：显示名称（编辑模式）与 Model ID（两种模式都要求，
   * 预设已内置 Model ID 时由预设自动填充，不会拦截用户）。
   * 结果在首次保存尝试后展示于字段下方。
   */
  const fieldErrors = useMemo(() => {
    const errors: { name?: string; model_id?: string } = {};
    if (isEdit && !form.name.trim()) errors.name = '请填写显示名称';
    if (!form.model_id.trim()) errors.model_id = '请填写 Model ID';
    return errors;
  }, [form.model_id, form.name, isEdit]);

  const handleSave = async () => {
    setSubmitAttempted(true);
    if (Object.keys(fieldErrors).length > 0) return;
    setSaving(true);
    setSaveError('');
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
        onClose(true);
      } else {
        const res = await modelsApi.create(payload);
        onClose(true, res.id);
      }
    } catch (e) {
      setSaveError(String(e));
      setSaving(false);
    }
  };

  /** 关闭入口：有未保存修改时先展示内联确认条，确认后才真正关闭 */
  const handleClose = () => {
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    onClose();
  };

  const handleProviderChange = (provider: string) => {
    const preset = PROVIDER_PRESETS[provider] || PROVIDER_PRESETS.custom;
    const pricing = pricingForProviderModel(provider, form.model_id);
    setDirty(true);
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
    setDirty(true);
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

  const saveDisabled = saving || loadingCatalog;

  return (
    <AdminModal title={isEdit ? '编辑模型' : '添加模型'} onClose={handleClose} maxWidth={MODAL_MAX_WIDTH}>
      <div className="-mt-3 mb-3 text-xs leading-5 text-gray-500">
        {isEdit ? '修改已有模型配置。API Key 留空时不会覆盖原密钥。' : '推荐先选预设，只填写 API Key；参数默认值已经内置。'}
      </div>

      <div className="overflow-y-auto pr-1" style={{ maxHeight: MODAL_BODY_MAX_HEIGHT }}>
        {!isEdit && catalog?.help.beginner_tip && (
          <div className="mb-4 rounded-xs border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal">
            {catalog.help.beginner_tip}
          </div>
        )}

        {!isEdit && (
          <div className="mb-4">
            {loadingCatalog ? (
              <div className="flex min-h-[112px] items-center justify-center gap-2 rounded-sm border border-gray-200 bg-gray-50 text-sm font-bold text-gray-500">
                <Loader2 size={15} className="animate-spin" />
                正在加载模型预设
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {catalog?.presets.map((preset) => {
                  const active = preset.key === presetKey;
                  return (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={() => handlePresetSelection(preset.key)}
                      aria-pressed={active}
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
            <FieldLabel htmlFor="model-api-key">API Key {isEdit ? '(留空不修改)' : ''}</FieldLabel>
            <TextInput id="model-api-key" type="password" value={form.api_key} onChange={(e) => patchForm({ api_key: e.target.value })} placeholder="粘贴供应商 API Key" autoComplete="off" />
          </div>
          <div>
            <FieldLabel htmlFor="model-name" required={isEdit}>显示名称</FieldLabel>
            <TextInput id="model-name" required={isEdit} aria-invalid={submitAttempted && !!fieldErrors.name} aria-describedby={submitAttempted && fieldErrors.name ? 'model-name-error' : undefined} value={form.name} onChange={(e) => patchForm({ name: e.target.value })} placeholder={selectedPreset?.defaults.name ? String(selectedPreset.defaults.name) : '不填则使用预设名称'} />
            {submitAttempted && fieldErrors.name && <div id="model-name-error" role="alert" className="mt-1 text-[10px] font-bold leading-4 text-red">{fieldErrors.name}</div>}
          </div>
          {(needsModelId || showAdvanced || (submitAttempted && !!fieldErrors.model_id)) && (
            <div>
              <FieldLabel htmlFor="model-id" required>Model ID</FieldLabel>
              <TextInput id="model-id" required aria-invalid={submitAttempted && !!fieldErrors.model_id} aria-describedby={submitAttempted && fieldErrors.model_id ? 'model-id-error' : undefined} value={form.model_id} onChange={(e) => handleModelIdChange(e.target.value)} placeholder={selectedPreset?.model_id || selectedPreset?.model_id_placeholder || `如 ${currentPreset.modelPlaceholder}`} />
              {submitAttempted && fieldErrors.model_id ? (
                <div id="model-id-error" role="alert" className="mt-1 text-[10px] font-bold leading-4 text-red">{fieldErrors.model_id}</div>
              ) : (
                <div className="mt-1 text-[10px] leading-4 text-gray-400">可填裸模型名，也可直接填完整 LiteLLM 路由。</div>
              )}
            </div>
          )}
          {(needsApiBase || showAdvanced) && (
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <FieldLabel htmlFor="model-api-base">API Base URL {needsApiBase ? '*' : ''}</FieldLabel>
                {currentPreset.baseUrl && (
                  <button
                    type="button"
                    onClick={() => patchForm({ api_base: currentPreset.baseUrl })}
                    className="rounded-full border border-primary-border bg-primary-light px-2 py-0.5 text-[10px] font-black text-primary"
                  >
                    使用内置
                  </button>
                )}
              </div>
              <TextInput id="model-api-base" value={form.api_base} onChange={(e) => patchForm({ api_base: e.target.value })} placeholder={selectedPreset?.api_base_placeholder || 'https://api.example.com/v1'} />
              {currentPreset.baseUrl && <div className="mt-1 text-[10px] leading-4 text-gray-400">内置默认：{currentPreset.baseUrl}</div>}
              {!currentPreset.baseUrl && <div className="mt-1 text-[10px] leading-4 text-gray-400">OpenAI 兼容网关通常填写 /v1 结尾的地址。</div>}
            </div>
          )}
          <div>
            <FieldLabel>描述</FieldLabel>
            <TextInput value={form.description} onChange={(e) => patchForm({ description: e.target.value })} placeholder="可选备注" />
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
              <FieldLabel required>Provider</FieldLabel>
              <SelectInput value={form.provider || 'openai'} onChange={(e) => handleProviderChange(e.target.value)}>
                {Object.entries(PROVIDER_PRESETS).map(([value, preset]) => (
                  <option key={value} value={value}>{preset.label}</option>
                ))}
              </SelectInput>
            </div>
            <div>
              <FieldLabel>路由组</FieldLabel>
              <TextInput value={form.routing_group} onChange={(e) => patchForm({ routing_group: e.target.value || 'default' })} placeholder="default" />
            </div>
            <div>
              <FieldLabel>路由优先级</FieldLabel>
              <TextInput type="number" value={form.routing_priority} onChange={(e) => patchForm({ routing_priority: parseInt(e.target.value, 10) || 100 })} />
            </div>
            <div>
              <FieldLabel>失败冷却秒数</FieldLabel>
              <TextInput type="number" value={form.cooldown_seconds} onChange={(e) => patchForm({ cooldown_seconds: parseInt(e.target.value, 10) || 300 })} />
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
              <TextInput value={form.model_family} onChange={(e) => patchForm({ model_family: e.target.value })} placeholder="如 deepseek / qwen / glm" />
            </div>
            <div>
              <FieldLabel>渠道名</FieldLabel>
              <TextInput value={form.channel_name} onChange={(e) => patchForm({ channel_name: e.target.value })} placeholder="如 official / opencode / openrouter" />
            </div>
            <div>
              <FieldLabel>稳定度</FieldLabel>
              <TextInput type="number" step="0.1" value={form.temperature} onChange={(e) => patchForm({ temperature: parseFloat(e.target.value) || 0.3 })} />
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
              <TextInput type="number" value={form.max_tokens} onChange={(e) => patchForm({ max_tokens: parseInt(e.target.value, 10) || 2000 })} />
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
              <TextInput type="number" value={form.requests_per_minute} onChange={(e) => patchForm({ requests_per_minute: parseInt(e.target.value, 10) || 30 })} />
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
              <TextInput type="number" step="0.001" value={form.cost_per_1m_input} onChange={(e) => patchForm({ cost_per_1m_input: e.target.value })} placeholder="如 1" />
            </div>
            <div>
              <FieldLabel>输出单价 / 百万 Tokens</FieldLabel>
              <TextInput type="number" step="0.001" value={form.cost_per_1m_output} onChange={(e) => patchForm({ cost_per_1m_output: e.target.value })} placeholder="如 2" />
            </div>
            <div>
              <FieldLabel>输入缓存命中 / 百万 Tokens</FieldLabel>
              <TextInput type="number" step="0.001" value={form.cost_per_1m_input_cache_hit} onChange={(e) => patchForm({ cost_per_1m_input_cache_hit: e.target.value })} placeholder="如 0.02" />
            </div>
            <div className="flex items-end">
              <div className={cx('w-full rounded-xs border px-2.5 py-2 text-[11px] leading-4', currentPreset.pricingNote ? 'border-teal-border bg-teal-light text-teal' : 'border-gray-200 bg-gray-50 text-gray-400')}>
                {currentPreset.pricingNote || '费用估算按输入未命中价和输出价计算。'}
              </div>
            </div>
          </div>
        )}
      </div>

      {saveError && (
        <div role="alert" className="mt-3 rounded-xs border border-red-light bg-red-light px-3 py-2 text-xs font-bold leading-5 text-red">
          保存失败：{saveError}
        </div>
      )}

      {confirmDiscard ? (
        <div className="mt-5 flex items-center justify-between gap-3 rounded-xs border border-gray-200 bg-gray-50 px-3 py-2.5">
          <span className="text-xs font-bold text-gray-600">已填写的内容尚未保存，确定放弃？</span>
          <div className="flex shrink-0 gap-2">
            <Button type="button" variant="secondary" onClick={() => setConfirmDiscard(false)}>继续编辑</Button>
            <Button type="button" variant="danger" onClick={() => onClose()}>放弃修改</Button>
          </div>
        </div>
      ) : (
        <AdminModalFooter>
          <Button type="button" variant="secondary" onClick={handleClose}>取消</Button>
          <Button type="button" variant="primary" onClick={handleSave} disabled={saveDisabled}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : null}
            {saving ? '保存中...' : '保存'}
          </Button>
        </AdminModalFooter>
      )}
    </AdminModal>
  );
}
