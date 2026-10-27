'use client';

/**
 * 模型编辑表单（add/edit 双模式，AdminModal 弹窗承载）。
 *
 * v4 流程改版（渠道优先）：
 * - 承载形态不变：AdminModal 弹窗，内容区独立滚动，底部操作栏常驻
 * - 添加流程从「4 张预设卡片开场」改为 用户描述的自然顺序：
 *   选择渠道 → 选择模型（目录下拉或自定义）→ 接入协议（API Base）→ API Key；
 *   可选项（显示名称 / 描述 / 专家参数）随后。编辑模式同构，字段预填。
 * - 渠道下拉即原专家参数里的 Provider 选择（models.dev 目录精选分组 +
 *   内置预设回落），提前为主步骤；专家参数区不再重复 Provider 字段
 * - preset_key 不再随创建 payload 发送：预设卡片的参数捆绑随卡片一起退役，
 *   参数默认走 catalog 通用默认值（presetNumberDefault 的 catalog 回退）
 * - v3 密度收敛保留：每字段一行式 11px 提示、三个单价并排、全弹窗无 10px 小字
 *
 * 交互约定（v2 契约不变）：
 * - 必填校验失败时字段下方红字提示（首次点击保存后显示），不静默禁用保存按钮
 * - 保存失败在表单内错误条展示；切换渠道保留已填的显示名称与 API Key
 * - 编辑模式跳过预设目录拉取，打开即可保存
 * - 有未保存修改时关闭需二次确认（内联确认条）
 * - onClose(saved, createdId)：保存成功时 saved=true，新增成功时附带 createdId
 *   供调用方自动触发连接测试；取消时无参数
 *
 * 状态：catalog（参数帮助文案）/ form（17 字段）/ saving / saveError /
 * submitAttempted / dirty / confirmDiscard / providerSelectKey（渠道下拉值）/
 * catalogProviders + catalogModels（目录数据，价格/上下文预填）。
 * ModelsTab 用此组件实现"添加模型"和"编辑模型"两种模式。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Loader2,
  RefreshCw,
  SlidersHorizontal,
} from 'lucide-react';
import { Button, cx } from '@/components/ui';
import { AdminModal, AdminModalFooter } from '@/components/admin-ui';
import { FieldLabel, InfoCell, SelectInput, TextInput } from './_components';
import { modelsApi } from '@/lib/api';
import type {
  LlmModelItem,
  LlmModelPresetCatalog,
  ModelCatalogModelItem,
  ModelCatalogProviderItem,
  ModelCatalogProvidersResponse,
} from '@/lib/api';
import {
  PROVIDER_PRESETS,
  formatPresetValue,
  formatTokens,
  parameterMeta,
  parseOptionalNumber,
  presetNumberDefault,
} from './_model-eval-utils';

/**
 * 弹窗内容区最大高度：按视口实际高度减去弹窗固定 chrome
 *（标题/副标题/底部操作栏/内边距约 230px），避免固定 vh 比例
 * 在高视口浪费空间、矮视口裁切输入框。
 */
const MODAL_BODY_MAX_HEIGHT = 'calc(100dvh - 230px)';
/** 弹窗宽度：兼顾渠道/模型字段与专家参数的表单密度 */
const MODAL_MAX_WIDTH = 720;

/**
 * 专家参数字段的一行式提示：说明 + 默认/范围元信息合并为一行 11px。
 * 此前每字段挂「元信息加粗行 + 说明行 + 需要调整行」三行 10px 小字，
 * 多字段的提示连成小字墙，扫读负担远大于信息价值。
 */
function ParamHint({ catalog, field, fallback }: { catalog: LlmModelPresetCatalog | null; field: string; fallback: string }) {
  return (
    <div className="mt-1 text-[11px] leading-4 text-ink-500">
      {catalog?.parameter_help?.[field]?.plain || fallback}
      {' · '}
      {parameterMeta(catalog, field)}
    </div>
  );
}

export function ModelEditForm({ model, onClose }: { model?: LlmModelItem | null; onClose: (saved?: boolean, createdId?: number) => void }) {
  const isEdit = !!model;
  const [catalog, setCatalog] = useState<LlmModelPresetCatalog | null>(null);
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
    context_window: model?.context_window ?? null,
    requests_per_minute: model?.requests_per_minute ?? 30,
    description: model?.description || '',
    enabled: model?.enabled ?? true,
    // 定价默认来自模型目录预填（命中目录模型时），
    // 前端不再硬编码厂商价格
    cost_per_1m_input: model?.cost_per_1m_input?.toString() ?? '',
    cost_per_1m_input_cache_hit: model?.cost_per_1m_input_cache_hit?.toString() ?? '',
    cost_per_1m_output: model?.cost_per_1m_output?.toString() ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(isEdit);
  // ── 模型目录（models.dev 缓存）：渠道分组下拉 + 模型 datalist + 价格预填 ──
  const [catalogProviders, setCatalogProviders] = useState<ModelCatalogProvidersResponse | null>(null);
  const [catalogModels, setCatalogModels] = useState<ModelCatalogModelItem[]>([]);
  // 下拉 value 用 models.dev id（唯一）；表单保存的 provider 是 litellm provider
  const [providerSelectKey, setProviderSelectKey] = useState('');
  const currentPreset = PROVIDER_PRESETS[form.provider] || PROVIDER_PRESETS.custom;

  /**
   * 渠道下拉统一选项：目录精选分组优先；目录不可用或未覆盖时回落
   * 内置 PROVIDER_PRESETS（离线兜底）。value 是 models.dev id（唯一键），
   * litellm provider 从 featured 项取，保存时再映射。
   */
  const providerOptions = useMemo(() => {
    const options: { value: string; label: string; group: string; featured?: ModelCatalogProviderItem }[] = [];
    for (const group of catalogProviders?.groups ?? []) {
      for (const item of group.providers) {
        options.push({ value: item.id, label: `${item.display_name}（${item.model_count}）`, group: group.label, featured: item });
      }
    }
    const coveredLitellm = new Set(options.map((o) => o.featured!.litellm_provider));
    for (const [value, preset] of Object.entries(PROVIDER_PRESETS)) {
      if (value !== 'custom' && !coveredLitellm.has(value)) {
        options.push({ value, label: preset.label, group: '内置预设' });
      }
    }
    options.push({ value: 'custom', label: PROVIDER_PRESETS.custom.label, group: '内置预设' });
    return options;
  }, [catalogProviders]);
  const providerOptionsByKey = useMemo(() => new Map(providerOptions.map((o) => [o.value, o])), [providerOptions]);

  // 下拉高亮与 form.provider（litellm 值）映射失配时反查同步；编辑模式初始也走这里。
  // 非目录渠道的 litellm provider 直接等于选项 value（custom 渠道落 provider="custom"，
  // 与后端 custom 预设约定一致：裸模型名按 OpenAI 兼容网关处理）
  useEffect(() => {
    setProviderSelectKey((prev) => {
      const option = providerOptionsByKey.get(prev);
      const optionProvider = option?.featured?.litellm_provider ?? prev;
      if (optionProvider === (form.provider || '')) return prev;
      const next = providerOptions.find(
        (o) => (o.featured?.litellm_provider ?? o.value) === (form.provider || ''),
      );
      return next?.value ?? 'custom';
    });
  }, [form.provider, providerOptions, providerOptionsByKey]);

  // 选中目录渠道后拉取目录模型（datalist 数据源）；失败静默，仍可手填
  useEffect(() => {
    const option = providerOptionsByKey.get(providerSelectKey);
    if (!option?.featured) {
      setCatalogModels([]);
      return;
    }
    let cancelled = false;
    modelsApi
      .catalogModels(option.featured.id, undefined, 200)
      .then((res) => {
        if (!cancelled) setCatalogModels(res.items);
      })
      .catch(() => {
        if (!cancelled) setCatalogModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [providerSelectKey, providerOptionsByKey]);

  // 目录渠道清单（添加/编辑两种模式都要；失败回落内置预设渠道）
  useEffect(() => {
    let cancelled = false;
    modelsApi
      .catalogProviders()
      .then((res) => {
        if (!cancelled) setCatalogProviders(res);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // 参数帮助文案（专家参数的一行式提示与恢复默认用）；失败回落组件内置文案
  useEffect(() => {
    let cancelled = false;
    modelsApi
      .presets()
      .then((res) => {
        if (!cancelled) setCatalog(res);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  /** 当前 Model ID 在目录中的命中项（价格/上下文参考提示用） */
  const matchedCatalogModel = useMemo(
    () => catalogModels.find((m) => m.model_id === form.model_id) ?? null,
    [catalogModels, form.model_id],
  );

  /** 当前渠道的默认接入地址：目录渠道取 models.dev 网关，内置渠道取预设 baseUrl */
  const channelDefaultBase = useMemo(() => {
    const option = providerOptionsByKey.get(providerSelectKey);
    return option?.featured?.default_api_base ?? (providerSelectKey && providerSelectKey !== 'custom' ? PROVIDER_PRESETS[providerSelectKey]?.baseUrl : undefined);
  }, [providerOptionsByKey, providerSelectKey]);

  /**
   * 用户输入统一入口：任何字段编辑都会标记表单为脏，并清除上一次的保存错误，
   * 供关闭时的放弃确认使用。程序化变更（渠道联动预填、恢复默认）不经过此入口。
   */
  const patchForm = (patch: Partial<typeof form>) => {
    setDirty(true);
    setSaveError('');
    setForm((prev) => ({ ...prev, ...patch }));
  };

  const restoreRecommendedDefaults = useCallback(() => {
    setDirty(true);
    setSaveError('');
    setForm((prev) => ({
      ...prev,
      routing_priority: presetNumberDefault(undefined, catalog, 'routing_priority', 100),
      cooldown_seconds: presetNumberDefault(undefined, catalog, 'cooldown_seconds', 300),
      temperature: presetNumberDefault(undefined, catalog, 'temperature', 0.3),
      max_tokens: presetNumberDefault(undefined, catalog, 'max_tokens', 2000),
      requests_per_minute: presetNumberDefault(undefined, catalog, 'requests_per_minute', 30),
    }));
  }, [catalog]);

  /**
   * 必填字段校验：显示名称（编辑模式）、渠道（添加模式）与 Model ID（两种模式都要求）。
   * 渠道不选直接保存会打后端 422（provider 必填），这里前置为内联红字提示。
   * 结果在首次保存尝试后展示于字段下方。
   */
  const fieldErrors = useMemo(() => {
    const errors: { name?: string; provider?: string; model_id?: string } = {};
    if (isEdit && !form.name.trim()) errors.name = '请填写显示名称';
    if (!isEdit && !form.provider.trim()) errors.provider = '请先选择渠道';
    if (!form.model_id.trim()) errors.model_id = '请填写模型 ID';
    return errors;
  }, [form.model_id, form.name, form.provider, isEdit]);

  const handleSave = async () => {
    setSubmitAttempted(true);
    if (Object.keys(fieldErrors).length > 0) return;
    setSaving(true);
    setSaveError('');
    try {
      const payload: Record<string, unknown> = { ...form };
      payload.cost_per_1m_input = parseOptionalNumber(form.cost_per_1m_input);
      payload.cost_per_1m_input_cache_hit = parseOptionalNumber(form.cost_per_1m_input_cache_hit);
      payload.cost_per_1m_output = parseOptionalNumber(form.cost_per_1m_output);
      // 创建时后端必填 name；未填则用模型名（与占位文案一致）
      if (!payload.name && !isEdit) payload.name = form.model_id;
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

  const handleProviderSelect = (key: string) => {
    const option = providerOptionsByKey.get(key);
    if (!option) return;
    const featured = option.featured;
    // custom 渠道落 provider="custom"（后端约定），base 清空由用户填
    const nextProvider = featured?.litellm_provider ?? key;
    setProviderSelectKey(key);
    setDirty(true);
    setSaveError('');
    setForm((f) => ({
      ...f,
      provider: nextProvider,
      // 目录厂商带默认网关则预填（OpenAI 兼容网关统一 provider=openai+api_base）；
      // custom 清空；无默认值的托管厂商（azure/bedrock 等）保留已填地址
      api_base: featured?.default_api_base ?? (key === 'custom' ? '' : PROVIDER_PRESETS[key]?.baseUrl ?? f.api_base),
    }));
  };

  const handleModelIdChange = (modelId: string) => {
    // 命中目录时预填价格与上下文窗口（models.dev，价格 USD/百万 tokens 原值）；
    // 未命中不猜价，留空由用户填写或走后端目录价估算兜底
    const catalogMatch = catalogModels.find((m) => m.model_id === modelId);
    setDirty(true);
    setForm((f) => ({
      ...f,
      model_id: modelId,
      ...(catalogMatch
        ? {
            context_window: catalogMatch.context_window,
            cost_per_1m_input: catalogMatch.cost_per_1m_input?.toString() ?? f.cost_per_1m_input,
            cost_per_1m_input_cache_hit: catalogMatch.cost_per_1m_cache_read?.toString() ?? f.cost_per_1m_input_cache_hit,
            cost_per_1m_output: catalogMatch.cost_per_1m_output?.toString() ?? f.cost_per_1m_output,
          }
        : {}),
    }));
  };

  const saveDisabled = saving;

  return (
    <AdminModal title={isEdit ? '编辑模型' : '添加模型'} onClose={handleClose} maxWidth={MODAL_MAX_WIDTH}>
      {isEdit ? (
        <div className="-mt-3 mb-3 text-xs leading-5 text-ink-500">
          修改已有模型配置。API Key 留空时不会覆盖原密钥。
        </div>
      ) : (
        <div className="-mt-3 mb-4 rounded-xs border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal">
          选渠道、选模型、填 API Key 即可接入；路由与性能参数已有合理默认，需要时再展开专家参数。
        </div>
      )}

      <div className="overflow-y-auto pr-1" style={{ maxHeight: MODAL_BODY_MAX_HEIGHT }}>
        {/* ── 主流程：渠道 → 模型 → 接入协议 ── */}
        <div className="grid grid-cols-1 gap-3">
          <div>
            <FieldLabel htmlFor="model-provider" required>1 · 选择渠道</FieldLabel>
            <SelectInput id="model-provider" value={providerSelectKey || ''} aria-invalid={submitAttempted && !!fieldErrors.provider} onChange={(e) => handleProviderSelect(e.target.value)}>
              {!providerSelectKey && <option value="">选择渠道…</option>}
              {Array.from(new Set(providerOptions.map((o) => o.group))).map((group) => (
                <optgroup key={group} label={group}>
                  {providerOptions.filter((o) => o.group === group).map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </optgroup>
              ))}
            </SelectInput>
            {submitAttempted && fieldErrors.provider && (
              <div role="alert" className="mt-1 text-[11px] font-bold leading-4 text-red">{fieldErrors.provider}</div>
            )}
            <div className="mt-1 text-[11px] leading-4 text-ink-500">
              当前 LiteLLM 路由前缀：<span className="font-bold text-ink-700">{form.provider || '未设置'}</span>
              {providerSelectKey === 'custom' && '；可填裸模型名或完整 LiteLLM 路由，OpenAI 兼容网关在此填写 Base URL'}
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="model-id" required>2 · 选择模型（目录可选，支持自定义）</FieldLabel>
            <TextInput id="model-id" required list="model-catalog-models" aria-invalid={submitAttempted && !!fieldErrors.model_id} aria-describedby={submitAttempted && fieldErrors.model_id ? 'model-id-error' : undefined} value={form.model_id} onChange={(e) => handleModelIdChange(e.target.value)} placeholder={currentPreset.modelPlaceholder} />
            <datalist id="model-catalog-models">
              {catalogModels.map((m) => (
                <option key={`${m.provider}/${m.model_id}`} value={m.model_id}>
                  {`${m.name ?? m.model_id}${m.context_window ? ` · ${formatTokens(m.context_window)} ctx` : ''}${m.status && m.status !== 'ga' ? ` · ${m.status}` : ''}`}
                </option>
              ))}
            </datalist>
            {submitAttempted && fieldErrors.model_id ? (
              <div id="model-id-error" role="alert" className="mt-1 text-[11px] font-bold leading-4 text-red">{fieldErrors.model_id}</div>
            ) : matchedCatalogModel ? (
              <div className="mt-1 text-[11px] font-bold leading-4 text-teal">
                目录参考：上下文 {formatTokens(matchedCatalogModel.context_window || 0)}
                {matchedCatalogModel.max_output_tokens ? ` · 输出上限 ${formatTokens(matchedCatalogModel.max_output_tokens)}` : ''}
                {matchedCatalogModel.cost_per_1m_input != null
                  ? ` · $${matchedCatalogModel.cost_per_1m_input}/${matchedCatalogModel.cost_per_1m_output ?? '-'} 每百万 tokens`
                  : ''}
                （models.dev，费用与上下文窗口已预填，超出窗口的调用会自动跳过该路由）
              </div>
            ) : (
              <div className="mt-1 text-[11px] leading-4 text-ink-500">
                {catalogModels.length > 0 ? '可从下拉选择目录模型，或手填自定义模型名 / 完整 LiteLLM 路由。' : '目录暂无该渠道模型，可直接手填模型名或完整 LiteLLM 路由。'}
              </div>
            )}
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <FieldLabel htmlFor="model-api-base">3 · API Base URL（接入协议）</FieldLabel>
              {channelDefaultBase && channelDefaultBase !== form.api_base && (
                <button
                  type="button"
                  onClick={() => patchForm({ api_base: channelDefaultBase })}
                  className="rounded-full border border-primary-border bg-primary-light px-2 py-0.5 text-[11px] font-black text-primary"
                >
                  使用内置
                </button>
              )}
            </div>
            <TextInput id="model-api-base" value={form.api_base} onChange={(e) => patchForm({ api_base: e.target.value })} placeholder="https://api.example.com/v1 或 http://host.docker.internal:11434/v1" />
            {/\/\/(localhost|127\.0\.0\.1)([:/]|\s|$)/.test(form.api_base) && (
              <div className="mt-1 rounded-xs border border-amber-border bg-amber-light px-2 py-1 text-[11px] font-bold leading-4 text-amber">
                检测到 localhost：后端跑在 Docker 内时 localhost 指向容器自身，调用时会自动转换为 host.docker.internal；若仍连不上，请直接填写 http://host.docker.internal:端口。
              </div>
            )}
            {channelDefaultBase
              ? <div className="mt-1 text-[11px] leading-4 text-ink-500">渠道默认：{channelDefaultBase}{form.api_base && form.api_base !== channelDefaultBase && '（当前使用自定义地址）'}</div>
              : <div className="mt-1 text-[11px] leading-4 text-ink-500">OpenAI 兼容网关通常填写 /v1 结尾的地址；本地推理服务（Ollama / LM Studio 等）用 http://host.docker.internal:端口/v1。</div>}
          </div>

          <div>
            <FieldLabel htmlFor="model-api-key">4 · API Key {isEdit ? '(留空不修改)' : ''}</FieldLabel>
            <TextInput id="model-api-key" type="password" value={form.api_key} onChange={(e) => patchForm({ api_key: e.target.value })} placeholder="粘贴供应商 API Key" autoComplete="off" />
            {providerSelectKey === 'custom' && (
              <div className="mt-1 text-[11px] leading-4 text-ink-500">本地推理服务不校验 Key 时，可填 ollama 等任意占位值。</div>
            )}
          </div>

          {/* ── 可选信息 ── */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div>
              <FieldLabel htmlFor="model-name" required={isEdit}>显示名称</FieldLabel>
              <TextInput id="model-name" required={isEdit} aria-invalid={submitAttempted && !!fieldErrors.name} aria-describedby={submitAttempted && fieldErrors.name ? 'model-name-error' : undefined} value={form.name} onChange={(e) => patchForm({ name: e.target.value })} placeholder="不填则使用模型名" />
              {submitAttempted && fieldErrors.name && <div id="model-name-error" role="alert" className="mt-1 text-[11px] font-bold leading-4 text-red">{fieldErrors.name}</div>}
            </div>
            <div>
              <FieldLabel htmlFor="model-description">描述</FieldLabel>
              <TextInput id="model-description" value={form.description} onChange={(e) => patchForm({ description: e.target.value })} placeholder="可选备注" />
            </div>
            <div className="grid grid-cols-3 gap-2 rounded-xs border border-ink-200 bg-ink-100 p-2.5 lg:col-span-2">
              <InfoCell label="稳定度" value={formatPresetValue(form.temperature)} />
              <InfoCell label="输出长度" value={formatPresetValue(form.max_tokens)} />
              <InfoCell label="请求/分" value={formatPresetValue(form.requests_per_minute)} />
            </div>
          </div>
        </div>

        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowAdvanced((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded-sm border border-ink-200 bg-white px-3 py-2 text-xs font-bold text-ink-700 transition hover:border-primary-border hover:text-primary"
          >
            <SlidersHorizontal size={14} />
            {showAdvanced ? '收起专家参数' : '专家参数'}
          </button>
          <button
            type="button"
            onClick={restoreRecommendedDefaults}
            className="ml-2 inline-flex items-center gap-1.5 rounded-sm border border-ink-200 bg-white px-3 py-2 text-xs font-bold text-ink-700 transition hover:border-primary-border hover:text-primary"
          >
            <RefreshCw size={14} />
            恢复推荐默认
          </button>
        </div>

        {showAdvanced && (
          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="rounded-xs border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal lg:col-span-2">
              {catalog?.help.advanced_tip || '这些参数只在你明确知道要调整模型行为时再改；不确定时点“恢复推荐默认”。'}
            </div>
            <div>
              <FieldLabel htmlFor="model-routing-group">路由组</FieldLabel>
              <TextInput id="model-routing-group" value={form.routing_group} onChange={(e) => patchForm({ routing_group: e.target.value || 'default' })} placeholder="default" />
            </div>
            <div>
              <FieldLabel htmlFor="model-routing-priority">路由优先级</FieldLabel>
              <TextInput id="model-routing-priority" type="number" value={form.routing_priority} onChange={(e) => patchForm({ routing_priority: parseInt(e.target.value, 10) || 100 })} />
            </div>
            <div>
              <FieldLabel htmlFor="model-cooldown-seconds">失败冷却秒数</FieldLabel>
              <TextInput id="model-cooldown-seconds" type="number" value={form.cooldown_seconds} onChange={(e) => patchForm({ cooldown_seconds: parseInt(e.target.value, 10) || 300 })} />
              <ParamHint catalog={catalog} field="cooldown_seconds" fallback={catalog?.help.cooldown_tip || '失败后暂停一段时间再重试。'} />
            </div>
            <div>
              <FieldLabel htmlFor="model-model-family">模型家族</FieldLabel>
              <TextInput id="model-model-family" value={form.model_family} onChange={(e) => patchForm({ model_family: e.target.value })} placeholder="如 deepseek / qwen / glm" />
            </div>
            <div>
              <FieldLabel htmlFor="model-channel-name">渠道名</FieldLabel>
              <TextInput id="model-channel-name" value={form.channel_name} onChange={(e) => patchForm({ channel_name: e.target.value })} placeholder="如 official / opencode / openrouter" />
            </div>
            <div>
              <FieldLabel htmlFor="model-temperature">稳定度</FieldLabel>
              <TextInput id="model-temperature" type="number" step="0.1" value={form.temperature} onChange={(e) => patchForm({ temperature: parseFloat(e.target.value) || 0.3 })} />
              <ParamHint catalog={catalog} field="temperature" fallback={catalog?.help.temperature_tip || '越低越稳定，分析和摘要通常用 0.2-0.4。'} />
            </div>
            <div>
              <FieldLabel htmlFor="model-max-tokens">输出长度</FieldLabel>
              <TextInput id="model-max-tokens" type="number" value={form.max_tokens} onChange={(e) => patchForm({ max_tokens: parseInt(e.target.value, 10) || 2000 })} />
              <ParamHint catalog={catalog} field="max_tokens" fallback={catalog?.help.max_tokens_tip || '控制单次输出长度。'} />
            </div>
            <div>
              <FieldLabel htmlFor="model-context-window">上下文窗口</FieldLabel>
              <TextInput id="model-context-window"
                type="number"
                value={form.context_window?.toString() ?? ''}
                onChange={(e) => patchForm({ context_window: parseOptionalNumber(e.target.value) })}
                placeholder="目录预填；留空不做调用前预检"
              />
              <div className="mt-1 text-[11px] leading-4 text-ink-500">
                配置后超出窗口的请求会自动跳过该路由并尝试下一候选；留空表示不预检。
              </div>
            </div>
            <div>
              <FieldLabel htmlFor="model-requests-per-minute">每分钟请求数</FieldLabel>
              <TextInput id="model-requests-per-minute" type="number" value={form.requests_per_minute} onChange={(e) => patchForm({ requests_per_minute: parseInt(e.target.value, 10) || 30 })} />
              <ParamHint catalog={catalog} field="requests_per_minute" fallback={catalog?.help.rpm_tip || '每分钟请求数。个人 Key 建议从 10-30 开始。'} />
            </div>
            {/* 三个单价并排一行，说明收为行下轻量文字；此前说明盒占一格与输入框混排，打断表单流 */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:col-span-2">
              <div>
                <FieldLabel htmlFor="model-cost-per-1m-input">输入未命中 / 百万</FieldLabel>
                <TextInput id="model-cost-per-1m-input" type="number" step="0.001" value={form.cost_per_1m_input} onChange={(e) => patchForm({ cost_per_1m_input: e.target.value })} placeholder="如 1" />
              </div>
              <div>
                <FieldLabel htmlFor="model-cost-per-1m-output">输出单价 / 百万</FieldLabel>
                <TextInput id="model-cost-per-1m-output" type="number" step="0.001" value={form.cost_per_1m_output} onChange={(e) => patchForm({ cost_per_1m_output: e.target.value })} placeholder="如 2" />
              </div>
              <div>
                <FieldLabel htmlFor="model-cost-per-1m-input-cache-hit">缓存命中 / 百万</FieldLabel>
                <TextInput id="model-cost-per-1m-input-cache-hit" type="number" step="0.001" value={form.cost_per_1m_input_cache_hit} onChange={(e) => patchForm({ cost_per_1m_input_cache_hit: e.target.value })} placeholder="如 0.02" />
              </div>
            </div>
            <div className="text-[11px] leading-4 text-ink-500 lg:col-span-2">
              单位：元 / 百万 Tokens。费用估算按输入未命中价和输出价计算；留空时后端用模型目录价（USD）估算。
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
        <div className="mt-5 flex items-center justify-between gap-3 rounded-xs border border-ink-200 bg-ink-100 px-3 py-2.5">
          <span className="text-xs font-bold text-ink-700">已填写的内容尚未保存，确定放弃？</span>
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
