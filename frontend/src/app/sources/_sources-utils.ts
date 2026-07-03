/**
 * Sources page 类型、配置与工具函数。
 *
 * 从 app/sources/page.tsx 抽出：
 * - 2 个类型：SourceTierKey / DropTarget
 * - sourceTierMeta 配置（4 层看板分层：core / stable / watch / attention）
 * - getSourceTier        根据信源状态/权重判定 tier
 * - normalizeRsshubInstanceUrl  RSSHub URL 规范化
 * - isPlainObject        类型守卫
 * - validateApiSourceConfig  API 信源配置校验
 */

export type SourceTierKey = 'core' | 'stable' | 'watch' | 'attention';
export type DropTarget = { tier: SourceTierKey; beforeId: number | null };

export const sourceTierMeta: Record<SourceTierKey, { label: string; desc: string; text: string; bg: string; border: string; dot: string; tone: 'primary' | 'teal' | 'amber' | 'red' }> = {
  core: { label: '核心信源', desc: '高权重、正常采集，影响精选排序', text: 'text-primary', bg: 'bg-primary-light', border: 'border-primary-border', dot: 'bg-primary', tone: 'primary' },
  stable: { label: '稳定信源', desc: '常规权重，作为日常覆盖面', text: 'text-teal', bg: 'bg-teal-light', border: 'border-teal-border', dot: 'bg-teal', tone: 'teal' },
  watch: { label: '观察池', desc: '低权重或新来源，先保留信号', text: 'text-amber', bg: 'bg-amber-light', border: 'border-amber-border', dot: 'bg-amber', tone: 'amber' },
  attention: { label: '待处理', desc: '禁用、报错或同步异常', text: 'text-red', bg: 'bg-red-light', border: 'border-red-light', dot: 'bg-red', tone: 'red' },
};

export function getSourceTier(source: { status: string; enabled: boolean; sync_error: string | null; weight?: number | null }): SourceTierKey {
  if (source.status === 'syncing') return 'stable';
  if (!source.enabled || source.status === 'error' || source.sync_error) return 'attention';
  if ((source.weight ?? 3) >= 4) return 'core';
  if ((source.weight ?? 3) <= 2) return 'watch';
  return 'stable';
}

export function normalizeRsshubInstanceUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    url.protocol = url.protocol.toLowerCase();
    url.hostname = url.hostname.toLowerCase();
    url.pathname = url.pathname.replace(/\/+$/, '');
    url.search = '';
    url.hash = '';
    return url.toString().replace(/\/$/, '');
  } catch {
    return null;
  }
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function validateApiSourceConfig(form: { source_type: string; keyword: string }): string | null {
  if (form.source_type !== 'API' || !form.keyword.trim()) return null;

  let config: unknown;
  try {
    config = JSON.parse(form.keyword);
  } catch {
    return 'API 配置必须是合法 JSON 对象';
  }

  if (!isPlainObject(config)) return 'API 配置必须是合法 JSON 对象';

  const method = config.method;
  if (method !== undefined && (typeof method !== 'string' || !['GET', 'POST'].includes(method.trim().toUpperCase()))) {
    return 'API 配置 method 仅支持 GET 或 POST';
  }

  for (const key of ['headers', 'params', 'body', 'fields']) {
    const value = config[key];
    if (value !== undefined && value !== null && !isPlainObject(value)) {
      return `API 配置 ${key} 必须是 JSON 对象`;
    }
  }

  const itemsPath = config.items_path;
  if (itemsPath !== undefined && (typeof itemsPath !== 'string' || !itemsPath.trim())) {
    return 'API 配置 items_path 必须是非空字符串';
  }

  const timeout = config.timeout;
  if (timeout !== undefined) {
    const value = Number(timeout);
    if (!Number.isFinite(value) || value < 1 || value > 120) {
      return 'API 配置 timeout 必须是 1 到 120 秒之间的数字';
    }
  }

  return null;
}