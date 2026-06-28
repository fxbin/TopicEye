'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  LockKeyhole,
  PlugZap,
  RefreshCw,
  Settings2,
  Sparkles,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  UserRound,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { integrationsApi, modelsApi } from '@/lib/api';
import type { LlmModelItem, LlmModelPresetCatalog, LlmModelPresetItem } from '@/lib/api';
import type { IntegrationStatus, WeReadSyncResult } from '@/types';
import { formatDateTime } from '@/lib/datetime';

const DEFAULT_INSTALL_COMMAND = 'npx skills add Tencent/WeChatReading -g';
const INSTALL_SCRIPT_COMMAND = 'npm run skills:install-weread';

function formatTime(value?: string | null) {
  return value ? formatDateTime(value, true) : '尚未同步';
}

function CopyCommandButton({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border border-gray-200 bg-white text-gray-500 transition hover:border-primary-border hover:text-primary"
      title={copied ? '已复制' : '复制命令'}
    >
      {copied ? <CheckCircle2 size={15} /> : <Copy size={15} />}
    </button>
  );
}

function CommandRow({ label, command }: { label: string; command: string }) {
  return (
    <div className="grid gap-2 rounded-sm border border-gray-200 bg-gray-50 p-3 sm:grid-cols-[116px_1fr_auto] sm:items-center">
      <div className="text-xs font-black text-gray-500">{label}</div>
      <code className="min-w-0 overflow-x-auto whitespace-nowrap rounded-xs bg-white px-2.5 py-2 font-mono text-xs font-bold text-gray-800">
        {command}
      </code>
      <CopyCommandButton command={command} />
    </div>
  );
}

function formatPresetValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  return String(value);
}

function presetRequires(preset: LlmModelPresetItem | undefined, field: string) {
  return Boolean(preset?.requires.includes(field));
}

function presetDefaultValue(
  preset: LlmModelPresetItem | undefined,
  catalog: LlmModelPresetCatalog | null,
  field: string,
) {
  return preset?.defaults[field] ?? catalog?.defaults[field];
}

function parameterMeta(catalog: LlmModelPresetCatalog | null, field: string) {
  const help = catalog?.parameter_help?.[field];
  const defaultValue = help?.default ?? catalog?.defaults[field];
  const parts = [`默认 ${formatPresetValue(defaultValue)}`];
  if (help?.recommended) {
    parts.push(help.recommended);
  } else if (help?.range?.length === 2) {
    parts.push(`建议 ${help.range[0]}-${help.range[1]}${help.unit ? ` ${help.unit}` : ''}`);
  } else if (help?.unit) {
    parts.push(help.unit);
  }
  return parts.join(' · ');
}

function parameterChangeHint(catalog: LlmModelPresetCatalog | null, field: string) {
  const changes = catalog?.parameter_help?.[field]?.when_to_change;
  if (!changes?.length) return '';
  return `需要调整：${changes.slice(0, 2).join('；')}`;
}

export default function ProfilePage() {
  const router = useRouter();
  const { currentUser, authLoading, refreshCounts } = useAppContext();
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<WeReadSyncResult | null>(null);
  const [aiModels, setAiModels] = useState<LlmModelItem[]>([]);
  const [aiCatalog, setAiCatalog] = useState<LlmModelPresetCatalog | null>(null);
  const [customAiAllowed, setCustomAiAllowed] = useState(false);
  const [loadingAi, setLoadingAi] = useState(true);
  const [savingAi, setSavingAi] = useState(false);
  const [deletingAiId, setDeletingAiId] = useState<number | null>(null);
  const [aiNotice, setAiNotice] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiForm, setAiForm] = useState({
    preset_key: 'deepseek_balanced',
    api_key: '',
    model_id: '',
    api_base: '',
    name: '',
    showAdvanced: false,
    temperature: '',
    max_tokens: '',
    requests_per_minute: '',
    cooldown_seconds: '',
  });

  const installCommand = status?.install_command || DEFAULT_INSTALL_COMMAND;
  const docsUrl = status?.docs_url || 'https://weread.qq.com/r/weread-skills';
  const canSave = apiKey.trim().length >= 8 && !saving;
  const canSync = Boolean(status?.configured) && !syncing;
  const selectedPreset = useMemo(
    () => aiCatalog?.presets.find((item) => item.key === aiForm.preset_key),
    [aiCatalog, aiForm.preset_key],
  );
  const aiConfigured = aiModels.some((item) => item.enabled);
  const needsModelId = presetRequires(selectedPreset, 'model_id');
  const needsApiBase = presetRequires(selectedPreset, 'api_base');
  const canSaveAi = customAiAllowed
    && aiForm.api_key.trim().length >= 8
    && (!needsModelId || aiForm.model_id.trim())
    && (!needsApiBase || aiForm.api_base.trim())
    && !savingAi;
  const selectedPresetDefaults = useMemo(() => ([
    {
      label: '稳定度',
      value: presetDefaultValue(selectedPreset, aiCatalog, 'temperature'),
      field: 'temperature',
    },
    {
      label: '输出长度',
      value: presetDefaultValue(selectedPreset, aiCatalog, 'max_tokens'),
      field: 'max_tokens',
    },
    {
      label: '请求上限',
      value: presetDefaultValue(selectedPreset, aiCatalog, 'requests_per_minute'),
      field: 'requests_per_minute',
    },
    {
      label: '失败冷却',
      value: presetDefaultValue(selectedPreset, aiCatalog, 'cooldown_seconds'),
      field: 'cooldown_seconds',
    },
  ]), [aiCatalog, selectedPreset]);

  const readiness = useMemo(() => {
    if (!status?.configured) {
      return { label: '未配置', tone: 'amber' as const, text: '先保存微信读书 API Key。' };
    }
    if (!status.sync_endpoint_configured) {
      return { label: '待接入', tone: 'amber' as const, text: 'API Key 已保存，后端还未配置 WEREAD_SKILL_API_URL。' };
    }
    return { label: '可同步', tone: 'teal' as const, text: 'Key 与同步 endpoint 均已配置。' };
  }, [status]);

  const loadStatus = useCallback(async () => {
    if (!currentUser) {
      setLoadingStatus(false);
      return;
    }
    setLoadingStatus(true);
    setError(null);
    try {
      setStatus(await integrationsApi.getWeRead());
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取微信读书配置失败');
    } finally {
      setLoadingStatus(false);
    }
  }, [currentUser]);

  const loadAiConfig = useCallback(async () => {
    if (!currentUser) {
      setLoadingAi(false);
      return;
    }
    setLoadingAi(true);
    setAiError(null);
    try {
      const [mine, catalog] = await Promise.all([modelsApi.mine(), modelsApi.presets()]);
      setAiModels(mine.models);
      setCustomAiAllowed(mine.custom_ai_allowed);
      setAiCatalog(catalog);
      setAiForm((prev) => (
        catalog.presets.some((item) => item.key === prev.preset_key)
          ? prev
          : { ...prev, preset_key: catalog.presets[0]?.key || 'custom' }
      ));
    } catch (err) {
      setAiError(err instanceof Error ? err.message : '读取个人 AI 配置失败');
    } finally {
      setLoadingAi(false);
    }
  }, [currentUser]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    void loadAiConfig();
  }, [loadAiConfig]);

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    setSyncResult(null);
    try {
      const next = await integrationsApi.updateWeRead({ api_key: apiKey.trim() });
      setStatus(next);
      setApiKey('');
      setNotice('微信读书 API Key 已保存。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (clearing) return;
    setClearing(true);
    setError(null);
    setNotice(null);
    setSyncResult(null);
    try {
      setStatus(await integrationsApi.clearWeRead());
      setApiKey('');
      setNotice('微信读书 API Key 已清除。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '清除失败');
    } finally {
      setClearing(false);
    }
  };

  const handleSync = async () => {
    if (!canSync) return;
    setSyncing(true);
    setError(null);
    setNotice(null);
    setSyncResult(null);
    try {
      const result = await integrationsApi.syncWeRead(50);
      setSyncResult(result);
      setNotice(result.message);
      refreshCounts();
      await loadStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : '同步失败';
      setError(message);
      await loadStatus();
    } finally {
      setSyncing(false);
    }
  };

  const handleAiPresetChange = (presetKey: string) => {
    const preset = aiCatalog?.presets.find((item) => item.key === presetKey);
    setAiForm((prev) => ({
      ...prev,
      preset_key: presetKey,
      model_id: preset?.model_id || '',
      api_base: preset?.api_base || '',
      name: '',
      showAdvanced: false,
      temperature: '',
      max_tokens: '',
      requests_per_minute: '',
      cooldown_seconds: '',
    }));
  };

  const handleSaveAi = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSaveAi) return;
    setSavingAi(true);
    setAiNotice(null);
    setAiError(null);
    try {
      const payload: Record<string, unknown> = {
        preset_key: aiForm.preset_key,
        api_key: aiForm.api_key.trim(),
      };
      if (aiForm.name.trim()) payload.name = aiForm.name.trim();
      if (aiForm.model_id.trim()) payload.model_id = aiForm.model_id.trim();
      if (aiForm.api_base.trim()) payload.api_base = aiForm.api_base.trim();
      if (aiForm.showAdvanced) {
        if (aiForm.temperature.trim()) payload.temperature = Number(aiForm.temperature);
        if (aiForm.max_tokens.trim()) payload.max_tokens = Number(aiForm.max_tokens);
        if (aiForm.requests_per_minute.trim()) payload.requests_per_minute = Number(aiForm.requests_per_minute);
        if (aiForm.cooldown_seconds.trim()) payload.cooldown_seconds = Number(aiForm.cooldown_seconds);
      }
      const result = await modelsApi.createMine(payload);
      setAiNotice(result.message);
      setAiForm((prev) => ({ ...prev, api_key: '', name: '' }));
      await loadAiConfig();
    } catch (err) {
      setAiError(err instanceof Error ? err.message : '保存个人 AI 失败');
    } finally {
      setSavingAi(false);
    }
  };

  const handleDeleteAi = async (model: LlmModelItem) => {
    if (deletingAiId || !confirm(`确定删除个人 AI 配置「${model.name}」？`)) return;
    setDeletingAiId(model.id);
    setAiNotice(null);
    setAiError(null);
    try {
      const result = await modelsApi.deleteMine(model.id);
      setAiNotice(result.message);
      await loadAiConfig();
    } catch (err) {
      setAiError(err instanceof Error ? err.message : '删除个人 AI 失败');
    } finally {
      setDeletingAiId(null);
    }
  };

  if (authLoading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page">
        <div className="inline-flex items-center gap-2 text-sm font-bold text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          正在检查登录状态
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <div className="flex h-full min-h-0 overflow-y-auto bg-page px-6 py-8 lg:px-10">
        <Panel className="mx-auto flex w-full max-w-[620px] flex-col items-start justify-center p-7">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-sm bg-primary-light text-primary">
            <UserRound size={22} />
          </div>
          <h1 className="mb-2 text-2xl font-black text-gray-900">需要登录后配置个人集成</h1>
          <p className="mb-5 text-sm leading-7 text-gray-500">
            微信读书 API Key 属于个人凭据，只会绑定到你的账号，不会显示给其他用户。
          </p>
          <Button type="button" variant="primary" onClick={() => router.push('/login')}>
            去登录
            <ArrowRight size={14} />
          </Button>
        </Panel>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[1120px] space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Badge tone={currentUser.plan === 'free' ? 'neutral' : 'primary'}>
                {currentUser.plan === 'free' ? '免费版' : '付费版'}
              </Badge>
              <Badge tone={readiness.tone}>{readiness.label}</Badge>
              <Badge tone={aiConfigured ? 'teal' : 'neutral'}>{aiConfigured ? '个人 AI 已配置' : '默认 AI'}</Badge>
            </div>
            <h1 className="text-[26px] font-black leading-tight text-gray-900">个人中心</h1>
            <p className="mt-2 max-w-[720px] text-sm leading-7 text-gray-500">
              管理账号、外部素材接入和同步状态。微信读书素材会进入内容流，后续可参与选题、收藏和创作方案生成。
            </p>
          </div>
          <Button type="button" onClick={loadStatus} disabled={loadingStatus} className="shrink-0">
            {loadingStatus ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            刷新状态
          </Button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
          <Panel className="p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-black text-gray-500">当前账号</div>
                <div className="mt-1 truncate text-base font-black text-gray-900">
                  {currentUser.display_name || currentUser.email}
                </div>
              </div>
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-teal-light text-teal">
                <ShieldCheck size={20} />
              </div>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-500">邮箱</span>
                <span className="min-w-0 truncate font-bold text-gray-800">{currentUser.email}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-500">套餐</span>
                <span className="font-bold text-gray-800">{currentUser.plan === 'free' ? '免费版' : currentUser.plan}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-500">创建时间</span>
                <span className="font-bold text-gray-800">{formatTime(currentUser.created_at)}</span>
              </div>
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <BookOpen size={18} className="text-primary" />
                  <h2 className="text-lg font-black text-gray-900">微信读书素材</h2>
                </div>
                <p className="text-sm leading-6 text-gray-500">{readiness.text}</p>
              </div>
              <Badge tone={status?.configured ? 'teal' : 'neutral'}>
                {status?.api_key_hint ? `Key ${status.api_key_hint}` : '未保存 Key'}
              </Badge>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                  <KeyRound size={14} />
                  API Key
                </div>
                <div className={cx('text-sm font-black', status?.configured ? 'text-teal' : 'text-gray-700')}>
                  {status?.configured ? '已保存' : '未配置'}
                </div>
              </div>
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                  <PlugZap size={14} />
                  同步 Endpoint
                </div>
                <div className={cx('text-sm font-black', status?.sync_endpoint_configured ? 'text-teal' : 'text-amber')}>
                  {status?.sync_endpoint_configured ? '已配置' : '未配置'}
                </div>
              </div>
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                  <RefreshCw size={14} />
                  最近同步
                </div>
                <div className="truncate text-sm font-black text-gray-800">{formatTime(status?.last_sync_at)}</div>
              </div>
            </div>

            <form onSubmit={handleSave} className="mt-5 grid gap-3 md:grid-cols-[1fr_auto_auto]">
              <label className="block">
                <span className="mb-1.5 block text-xs font-black text-gray-500">微信读书 API Key</span>
                <input
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                  placeholder={status?.configured ? '输入新 Key 后可覆盖当前配置' : '粘贴微信读书 API Key'}
                  type="password"
                  autoComplete="off"
                />
              </label>
              <div className="flex items-end">
                <Button type="submit" variant="primary" disabled={!canSave} className="w-full md:w-auto">
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                  保存 Key
                </Button>
              </div>
              <div className="flex items-end">
                <Button
                  type="button"
                  variant="danger"
                  onClick={handleClear}
                  disabled={clearing || !status?.configured}
                  className="w-full md:w-auto"
                >
                  {clearing ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                  清除
                </Button>
              </div>
            </form>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button type="button" variant="success" onClick={handleSync} disabled={!canSync}>
                {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {status?.configured && !status.sync_endpoint_configured ? '检查同步服务' : '同步 50 条素材'}
              </Button>
              {docsUrl && (
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-700 transition hover:border-primary-border hover:text-primary"
                >
                  官方文档
                  <ExternalLink size={14} />
                </a>
              )}
            </div>

            {(notice || error || syncResult || status?.last_sync_error) && (
              <div className="mt-4 space-y-2">
                {notice && (
                  <div className="rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal">
                    {notice}
                  </div>
                )}
                {error && (
                  <div className="rounded-sm border border-amber-border bg-amber-light px-3 py-2 text-xs font-bold text-amber">
                    {error}
                  </div>
                )}
                {syncResult && (
                  <div className="grid gap-2 text-xs sm:grid-cols-3">
                    <div className="rounded-sm bg-gray-50 px-3 py-2 font-bold text-gray-600">拉取 {syncResult.fetched}</div>
                    <div className="rounded-sm bg-gray-50 px-3 py-2 font-bold text-gray-600">新增 {syncResult.new}</div>
                    <div className="rounded-sm bg-gray-50 px-3 py-2 font-bold text-gray-600">重复 {syncResult.duplicates}</div>
                  </div>
                )}
                {!error && status?.last_sync_error && (
                  <div className="rounded-sm border border-red-light bg-red-light px-3 py-2 text-xs font-bold text-red">
                    上次同步错误：{status.last_sync_error}
                  </div>
                )}
              </div>
            )}
          </Panel>
        </div>

        <Panel className="p-5">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <BrainCircuit size={18} className="text-primary" />
                <h2 className="text-lg font-black text-gray-900">个人 AI</h2>
              </div>
              <p className="text-sm leading-6 text-gray-500">
                使用推荐预设时只需要填写 API Key。系统会自动套用适合选题分析的默认参数，熟悉模型后再展开高级参数。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={customAiAllowed ? 'teal' : 'amber'}>
                {customAiAllowed ? '允许自定义' : '付费权益'}
              </Badge>
              <Button type="button" onClick={loadAiConfig} disabled={loadingAi} className="shrink-0">
                {loadingAi ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                刷新
              </Button>
            </div>
          </div>

          {!customAiAllowed && (
            <div className="mb-4 rounded-sm border border-amber-border bg-amber-light px-3 py-3 text-sm leading-6 text-amber">
              <div className="mb-1 flex items-center gap-2 font-black">
                <LockKeyhole size={15} />
                自定义 AI 需要付费套餐
              </div>
              免费用户会继续使用系统默认 AI。升级后可以绑定自己的 API Key、模型和 OpenAI 兼容网关。
            </div>
          )}

          {aiCatalog?.help.beginner_tip && (
            <div className="mb-4 rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal">
              {aiCatalog.help.beginner_tip}
            </div>
          )}

          <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
            <form onSubmit={handleSaveAi} className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                {aiCatalog?.presets.map((preset) => {
                  const active = preset.key === aiForm.preset_key;
                  return (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={() => handleAiPresetChange(preset.key)}
                      className={cx(
                        'min-h-[112px] rounded-sm border bg-white p-3 text-left transition',
                        active ? 'border-primary-border bg-primary-light' : 'border-gray-200 hover:border-primary-border',
                      )}
                    >
                      <div className="mb-2 flex items-start justify-between gap-2">
                        <div className={cx('text-sm font-black', active ? 'text-primary' : 'text-gray-900')}>{preset.label}</div>
                        {active && <CheckCircle2 size={16} className="shrink-0 text-primary" />}
                      </div>
                      <div className="text-xs leading-5 text-gray-500">{preset.description}</div>
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

              {selectedPreset && (
                <div className="grid gap-3 rounded-sm border border-gray-200 bg-gray-50 p-3 md:grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)]">
                  <div className="min-w-0">
                    <div className="mb-1 text-xs font-black text-gray-500">当前预设</div>
                    <div className="truncate text-sm font-black text-gray-900">{selectedPreset.label}</div>
                    <div className="mt-1 text-xs leading-5 text-gray-500">{selectedPreset.help}</div>
                    <div className="mt-2 text-[11px] font-bold text-teal">不填写高级参数时，将使用右侧默认值。</div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {selectedPresetDefaults.map((item) => (
                      <div key={item.label} className="rounded-xs border border-gray-200 bg-white px-2.5 py-2">
                        <div className="mb-1 text-[10px] font-black text-gray-400">{item.label}</div>
                        <div className="font-mono text-sm font-black text-gray-900">{formatPresetValue(item.value)}</div>
                        <div className="mt-1 truncate text-[10px] text-gray-400">
                          {aiCatalog?.parameter_help?.[item.field]?.beginner || '默认即可'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-2">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-black text-gray-500">API Key</span>
                  <input
                    value={aiForm.api_key}
                    onChange={(event) => setAiForm((prev) => ({ ...prev, api_key: event.target.value }))}
                    className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                    placeholder="粘贴供应商 API Key"
                    type="password"
                    autoComplete="off"
                    disabled={!customAiAllowed}
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-xs font-black text-gray-500">显示名称</span>
                  <input
                    value={aiForm.name}
                    onChange={(event) => setAiForm((prev) => ({ ...prev, name: event.target.value }))}
                    className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                    placeholder={selectedPreset?.defaults.name ? String(selectedPreset.defaults.name) : '不填则使用预设名称'}
                    disabled={!customAiAllowed}
                  />
                </label>
                {(needsModelId || aiForm.preset_key === 'custom') && (
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-black text-gray-500">模型名</span>
                    <input
                      value={aiForm.model_id}
                      onChange={(event) => setAiForm((prev) => ({ ...prev, model_id: event.target.value }))}
                      className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                      placeholder={selectedPreset?.model_id || selectedPreset?.model_id_placeholder || '如 gpt-4.1-mini'}
                      disabled={!customAiAllowed}
                    />
                  </label>
                )}
                {(needsApiBase || aiForm.preset_key === 'openai_compatible') && (
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-black text-gray-500">API Base</span>
                    <input
                      value={aiForm.api_base}
                      onChange={(event) => setAiForm((prev) => ({ ...prev, api_base: event.target.value }))}
                      className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                      placeholder={selectedPreset?.api_base_placeholder || 'https://api.example.com/v1'}
                      disabled={!customAiAllowed}
                    />
                    <div className="mt-1 text-[10px] leading-4 text-gray-400">
                      OpenAI 兼容网关需要填写服务商给出的 /v1 地址。
                    </div>
                  </label>
                )}
              </div>

              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setAiForm((prev) => ({ ...prev, showAdvanced: !prev.showAdvanced }))}
                    className="inline-flex items-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-600 transition hover:border-primary-border hover:text-primary"
                  >
                    <Settings2 size={14} />
                    {aiForm.showAdvanced ? '收起专家参数' : '专家参数'}
                  </button>
                  <span className="text-xs font-bold text-gray-500">
                    {aiForm.showAdvanced
                      ? (aiCatalog?.help.advanced_tip || '只在你明确知道要调整模型行为时再改。')
                      : '不用展开也能保存，系统会使用推荐默认参数。'}
                  </span>
                </div>
                {aiForm.showAdvanced && (
                  <div className="mt-3 grid gap-3 md:grid-cols-4">
                    <div className="rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal md:col-span-4">
                      留空表示使用当前预设默认值；只有当输出太保守、被截断、或供应商限流时才需要改。
                    </div>
                    <label className="block">
                      <span className="mb-1.5 block text-xs font-black text-gray-500">稳定度</span>
                      <input
                        value={aiForm.temperature}
                        onChange={(event) => setAiForm((prev) => ({ ...prev, temperature: event.target.value }))}
                        className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                        placeholder={formatPresetValue(selectedPreset?.defaults.temperature ?? aiCatalog?.defaults.temperature)}
                        type="number"
                        step="0.1"
                        disabled={!customAiAllowed}
                      />
                      <div className="mt-1 text-[10px] leading-4 text-gray-400">
                        <span className="font-bold text-gray-500">{parameterMeta(aiCatalog, 'temperature')}</span>
                        <br />
                        {aiCatalog?.parameter_help?.temperature?.plain || aiCatalog?.help.temperature_tip || '选题分析和摘要建议保持默认。'}
                        {parameterChangeHint(aiCatalog, 'temperature') && (
                          <>
                            <br />
                            {parameterChangeHint(aiCatalog, 'temperature')}
                          </>
                        )}
                      </div>
                    </label>
                    <label className="block">
                      <span className="mb-1.5 block text-xs font-black text-gray-500">输出长度</span>
                      <input
                        value={aiForm.max_tokens}
                        onChange={(event) => setAiForm((prev) => ({ ...prev, max_tokens: event.target.value }))}
                        className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                        placeholder={formatPresetValue(selectedPreset?.defaults.max_tokens ?? aiCatalog?.defaults.max_tokens)}
                        type="number"
                        disabled={!customAiAllowed}
                      />
                      <div className="mt-1 text-[10px] leading-4 text-gray-400">
                        <span className="font-bold text-gray-500">{parameterMeta(aiCatalog, 'max_tokens')}</span>
                        <br />
                        {aiCatalog?.parameter_help?.max_tokens?.plain || aiCatalog?.help.max_tokens_tip || '控制单次输出长度。'}
                        {parameterChangeHint(aiCatalog, 'max_tokens') && (
                          <>
                            <br />
                            {parameterChangeHint(aiCatalog, 'max_tokens')}
                          </>
                        )}
                      </div>
                    </label>
                    <label className="block">
                      <span className="mb-1.5 block text-xs font-black text-gray-500">每分钟请求数</span>
                      <input
                        value={aiForm.requests_per_minute}
                        onChange={(event) => setAiForm((prev) => ({ ...prev, requests_per_minute: event.target.value }))}
                        className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                        placeholder={formatPresetValue(selectedPreset?.defaults.requests_per_minute ?? aiCatalog?.defaults.requests_per_minute)}
                        type="number"
                        disabled={!customAiAllowed}
                      />
                      <div className="mt-1 text-[10px] leading-4 text-gray-400">
                        <span className="font-bold text-gray-500">{parameterMeta(aiCatalog, 'requests_per_minute')}</span>
                        <br />
                        {aiCatalog?.parameter_help?.requests_per_minute?.plain || aiCatalog?.help.rpm_tip || '个人 Key 建议从保守上限开始。'}
                        {parameterChangeHint(aiCatalog, 'requests_per_minute') && (
                          <>
                            <br />
                            {parameterChangeHint(aiCatalog, 'requests_per_minute')}
                          </>
                        )}
                      </div>
                    </label>
                    <label className="block">
                      <span className="mb-1.5 block text-xs font-black text-gray-500">失败冷却</span>
                      <input
                        value={aiForm.cooldown_seconds}
                        onChange={(event) => setAiForm((prev) => ({ ...prev, cooldown_seconds: event.target.value }))}
                        className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                        placeholder={formatPresetValue(selectedPreset?.defaults.cooldown_seconds ?? aiCatalog?.defaults.cooldown_seconds)}
                        type="number"
                        disabled={!customAiAllowed}
                      />
                      <div className="mt-1 text-[10px] leading-4 text-gray-400">
                        <span className="font-bold text-gray-500">{parameterMeta(aiCatalog, 'cooldown_seconds')}</span>
                        <br />
                        {aiCatalog?.parameter_help?.cooldown_seconds?.plain || aiCatalog?.help.cooldown_tip || '失败后暂停一段时间再重试。'}
                        {parameterChangeHint(aiCatalog, 'cooldown_seconds') && (
                          <>
                            <br />
                            {parameterChangeHint(aiCatalog, 'cooldown_seconds')}
                          </>
                        )}
                      </div>
                    </label>
                    <div className="md:col-span-4">
                      <button
                        type="button"
                        onClick={() => setAiForm((prev) => ({
                          ...prev,
                          temperature: '',
                          max_tokens: '',
                          requests_per_minute: '',
                          cooldown_seconds: '',
                        }))}
                        className="inline-flex items-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-600 transition hover:border-primary-border hover:text-primary"
                      >
                        <RefreshCw size={14} />
                        恢复推荐默认
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" variant="primary" disabled={!canSaveAi}>
                  {savingAi ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  保存个人 AI
                </Button>
                {selectedPreset?.help && <span className="text-xs font-bold text-gray-500">{selectedPreset.help}</span>}
              </div>

              {(aiNotice || aiError) && (
                <div className="space-y-2">
                  {aiNotice && (
                    <div className="rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal">
                      {aiNotice}
                    </div>
                  )}
                  {aiError && (
                    <div className="rounded-sm border border-amber-border bg-amber-light px-3 py-2 text-xs font-bold text-amber">
                      {aiError}
                    </div>
                  )}
                </div>
              )}
            </form>

            <div className="space-y-3">
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-3 text-xs font-black text-gray-500">当前个人 AI</div>
                {loadingAi && <div className="text-sm font-bold text-gray-500">加载中...</div>}
                {!loadingAi && aiModels.length === 0 && (
                  <div className="text-sm leading-6 text-gray-500">还没有个人 AI 配置，系统会使用内置默认模型。</div>
                )}
                {!loadingAi && aiModels.map((model) => (
                  <div key={model.id} className="mb-2 rounded-sm border border-gray-200 bg-white p-3 last:mb-0">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-black text-gray-900">{model.name}</div>
                        <div className="mt-1 truncate text-xs text-gray-500">{model.provider} · {model.model_id}</div>
                      </div>
                      <Badge tone={model.enabled ? 'teal' : 'neutral'}>{model.enabled ? '启用' : '停用'}</Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded-xs bg-gray-50 px-2 py-1 text-gray-500">稳定度 {formatPresetValue(model.temperature)}</div>
                      <div className="rounded-xs bg-gray-50 px-2 py-1 text-gray-500">长度 {formatPresetValue(model.max_tokens)}</div>
                      <div className="rounded-xs bg-gray-50 px-2 py-1 text-gray-500">请求 {formatPresetValue(model.requests_per_minute)}/分</div>
                    </div>
                    <div className="mt-2 flex justify-end">
                      <Button type="button" variant="danger" onClick={() => handleDeleteAi(model)} disabled={!customAiAllowed || deletingAiId === model.id}>
                        {deletingAiId === model.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="rounded-sm border border-gray-200 bg-white p-3">
                <div className="mb-2 text-xs font-black text-gray-500">默认参数说明</div>
                <div className="space-y-2 text-xs leading-5 text-gray-500">
                  {aiCatalog?.help.rpm_tip && <div>{aiCatalog.help.rpm_tip}</div>}
                  {aiCatalog?.help.temperature_tip && <div>{aiCatalog.help.temperature_tip}</div>}
                  {aiCatalog?.help.max_tokens_tip && <div>{aiCatalog.help.max_tokens_tip}</div>}
                </div>
              </div>
            </div>
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <TerminalSquare size={18} className="text-primary" />
            <h2 className="text-lg font-black text-gray-900">Skill 安装</h2>
          </div>
          <p className="mb-4 max-w-[820px] text-sm leading-7 text-gray-500">
            官方 Skill 需要用户在本机安装并获取 API Key。服务启动阶段不会自动执行全局安装，避免网络依赖和全局写入影响后端稳定性。
          </p>
          <div className="space-y-3">
            <CommandRow label="官方命令" command={installCommand} />
            <CommandRow label="前端脚本" command={INSTALL_SCRIPT_COMMAND} />
          </div>
          <div className="mt-4 rounded-sm border border-gray-200 bg-gray-50 px-3 py-2 text-xs leading-6 text-gray-500">
            后端同步入口通过环境变量 <span className="font-mono font-bold text-gray-700">WEREAD_SKILL_API_URL</span> 配置；
            未配置时可以保存 Key，点击同步会记录明确错误。
          </div>
        </Panel>
      </div>
    </div>
  );
}
