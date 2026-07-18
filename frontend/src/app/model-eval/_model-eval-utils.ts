/**
 * Model eval page 静态配置与工具函数（无 React 依赖）。
 *
 * 从 app/model-eval/page.tsx 抽出：
 * - Tab / Tone 类型
 * - ProviderPreset 类型 + PROVIDER_PRESETS（5 个厂商预置）
 * - promptTypeLabel 提示词类型中文标签
 * - toneClasses 5 种色调的样式映射
 * - 定价工具（deepSeekPricingForModel / pricingForProviderModel）
 * - 格式化工具（formatNumber / formatTokens / formatCurrency / formatPerMillion /
 *   formatPresetValue）
 * - Preset 工具（presetRequires / presetNumberDefault / parameterMeta /
 *   parameterChangeHint / parseOptionalNumber）
 *
 * UI 原子组件（Surface / StatTile / StatusPill / FieldLabel / TextInput /
 * SelectInput / InfoCell）在 _components.tsx 中定义。
 */

import type { LlmModelPresetCatalog, LlmModelPresetItem } from '@/lib/api';
import type { Tone } from '@/components/ui';

export type { Tone };

export type Tab = 'models' | 'evaluate' | 'usage' | 'history';

export type ProviderPreset = {
  label: string;
  baseUrl: string;
  modelPlaceholder: string;
  costPer1MInput?: number;
  costPer1MInputCacheHit?: number;
  costPer1MOutput?: number;
  pricingNote?: string;
};

export const PROVIDER_PRESETS: Record<string, ProviderPreset> = {
  openai: {
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    modelPlaceholder: 'gpt-4.1-mini',
  },
  deepseek: {
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    modelPlaceholder: 'deepseek-chat',
    costPer1MInput: 1,
    costPer1MInputCacheHit: 0.02,
    costPer1MOutput: 2,
    pricingNote: 'DeepSeek 按百万 tokens 计费；V4 Flash 默认 ¥1/¥0.02/¥2，V4 Pro 当前优惠价 ¥3/¥0.025/¥6',
  },
  minimax: {
    label: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    modelPlaceholder: 'MiniMax-Text-01',
  },
  zhipu: {
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4/',
    modelPlaceholder: 'glm-4-plus',
  },
  custom: {
    label: '高级 LiteLLM 路由',
    baseUrl: '',
    modelPlaceholder: 'openai/deepseek-v4-flash-free',
  },
};

export const promptTypeLabel: Record<string, string> = {
  analysis: '选题分析',
  daily_report: 'AI 日报',
  weekly_digest: 'AI 周刊',
  classification: '内容分类',
  custom: '自定义',
};

export const toneClasses: Record<Tone, { text: string; border: string; bg: string; metric: string }> = {
  primary: { text: 'text-primary', border: 'border-primary-border', bg: 'bg-primary-light', metric: 'text-primary' },
  teal: { text: 'text-teal', border: 'border-teal-border', bg: 'bg-teal-light', metric: 'text-teal' },
  amber: { text: 'text-amber', border: 'border-amber-border', bg: 'bg-amber-light', metric: 'text-amber' },
  purple: { text: 'text-purple', border: 'border-purple-border', bg: 'bg-purple-light', metric: 'text-purple' },
  red: { text: 'text-red', border: 'border-red-light', bg: 'bg-red-light', metric: 'text-red' },
  neutral: { text: 'text-gray-600', border: 'border-gray-200', bg: 'bg-gray-50', metric: 'text-gray-900' },
};

export function deepSeekPricingForModel(modelId: string) {
  const normalized = modelId.toLowerCase();
  if (normalized.includes('deepseek-v4-flash-free')) {
    return { input: 0, cacheHit: 0, output: 0 };
  }
  if (normalized.includes('v4-pro')) {
    return { input: 3, cacheHit: 0.025, output: 6 };
  }
  return { input: 1, cacheHit: 0.02, output: 2 };
}

export function pricingForProviderModel(provider: string, modelId: string) {
  if (modelId.toLowerCase().includes('deepseek-v4-flash-free')) return deepSeekPricingForModel(modelId);
  if (provider === 'deepseek') return deepSeekPricingForModel(modelId);
  const preset = PROVIDER_PRESETS[provider];
  if (!preset?.costPer1MInput && !preset?.costPer1MOutput && !preset?.costPer1MInputCacheHit) return null;
  return {
    input: preset.costPer1MInput,
    cacheHit: preset.costPer1MInputCacheHit,
    output: preset.costPer1MOutput,
  };
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value || 0);
}

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}K`;
  return formatNumber(value);
}

export function formatCurrency(value: number): string {
  return `¥${(value || 0).toFixed(value >= 10 ? 2 : 4)}`;
}

export function formatPerMillion(value: number | null | undefined): string {
  return value !== null && value !== undefined ? `${formatCurrency(value)} / 百万` : '未配置';
}

export function formatPresetValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  return String(value);
}

export function presetRequires(preset: LlmModelPresetItem | undefined, field: string): boolean {
  return Boolean(preset?.requires.includes(field));
}

export function presetNumberDefault(
  preset: LlmModelPresetItem | undefined,
  catalog: LlmModelPresetCatalog | null,
  field: string,
  fallback: number,
): number {
  const value = preset?.defaults[field] ?? catalog?.defaults[field] ?? fallback;
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function parameterMeta(catalog: LlmModelPresetCatalog | null, field: string): string {
  const help = catalog?.parameter_help?.[field];
  const defaultValue = help?.default ?? catalog?.defaults[field];
  const parts = [`默认 ${formatPresetValue(defaultValue)}`];
  if (help?.recommended) {
    parts.push(help.recommended);
  } else if (help?.range?.length === 2) {
    parts.push(`范围 ${help.range[0]}-${help.range[1]}${help.unit ? ` ${help.unit}` : ''}`);
  } else if (help?.unit) {
    parts.push(help.unit);
  }
  return parts.join(' · ');
}

export function parameterChangeHint(catalog: LlmModelPresetCatalog | null, field: string): string {
  const changes = catalog?.parameter_help?.[field]?.when_to_change;
  if (!changes?.length) return '';
  return `需要调整：${changes.slice(0, 2).join('；')}`;
}

export function parseOptionalNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}