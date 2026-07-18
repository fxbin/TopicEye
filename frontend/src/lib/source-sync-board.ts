import type { BackendSource } from '@/components/SourceRow';
import { formatDateTime as formatDateTimeStr } from '@/lib/datetime';

export type SyncBoardKey = 'running' | 'due' | 'waiting' | 'fresh' | 'error' | 'paused';

export interface SyncBoardTiming {
  intervalMinutes: number;
  lastSyncAt: Date | null;
  nextSyncAt: Date | null;
  elapsedMinutes: number | null;
  diffMinutes: number | null;
  progress: number;
}

export interface SourceSyncBoardModel {
  columns: Record<SyncBoardKey, BackendSource[]>;
  dueCount: number;
  healthyCount: number;
  errorCount: number;
  pausedCount: number;
  nextDueSource: BackendSource | null;
}

export const syncBoardOrder: SyncBoardKey[] = ['running', 'due', 'waiting', 'fresh', 'error', 'paused'];

export function sourceTypeLabel(type: string): string {
  const map: Record<string, string> = {
    RSS: 'RSS',
    RSSHub: 'RSSHub',
    TwitterRSS: 'Twitter RSS',
    Reddit: 'Reddit',
    API: 'API',
    Zhihu: '知乎',
    DouyinHot: '抖音热榜',
    网站: '网站',
    公众号: '公众号',
    自定义: '自定义',
  };
  return map[type] || type;
}

export function parseBackendDate(dateStr: string | null): Date | null {
  if (!dateStr) return null;
  const normalized = dateStr.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr) ? dateStr : `${dateStr}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatInterval(minutes: number): string {
  if (minutes >= 1440) return `${Math.round(minutes / 1440)} 天`;
  if (minutes >= 60) return `${Math.round(minutes / 60)} 小时`;
  return `${minutes} 分钟`;
}

export function formatDuration(minutes: number): string {
  const normalized = Math.max(0, Math.round(minutes));
  if (normalized < 60) return `${normalized} 分钟`;
  const hours = Math.floor(normalized / 60);
  const restMinutes = normalized % 60;
  if (hours < 24) return restMinutes ? `${hours} 小时 ${restMinutes} 分钟` : `${hours} 小时`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `${days} 天 ${restHours} 小时` : `${days} 天`;
}

/**
 * 格式化同步时间。统一委托到 @/lib/datetime.formatDateTime。
 * 接收 Date 对象，内部转 ISO 字符串后调用公共版；空值返回 '-'。
 * 历史本地版返回 '未记录'，统一后规范为 '-'。
 */
export function formatDateTime(date: Date | null): string {
  return formatDateTimeStr(date ? date.toISOString() : null);
}

export function inferSyncBoardKey(source: BackendSource, syncingIds: Set<number>, now: Date): SyncBoardKey {
  if (syncingIds.has(source.id)) return 'running';
  if (source.status === 'syncing') return 'running';
  if (!source.enabled || source.status === 'disabled') return 'paused';
  if (source.status === 'error' || source.sync_error) return 'error';

  const lastSyncAt = parseBackendDate(source.last_sync_at);
  if (!lastSyncAt) return 'due';

  const intervalMs = Math.max(source.fetch_interval_minutes || 60, 5) * 60 * 1000;
  const ageMs = Math.max(0, now.getTime() - lastSyncAt.getTime());
  if (ageMs >= intervalMs) return 'due';
  if (ageMs / intervalMs <= 0.35) return 'fresh';
  return 'waiting';
}

export function getSyncTiming(source: BackendSource, now: Date): SyncBoardTiming {
  const intervalMinutes = Math.max(source.fetch_interval_minutes || 60, 5);
  const lastSyncAt = parseBackendDate(source.last_sync_at);
  const nextSyncAt = lastSyncAt ? new Date(lastSyncAt.getTime() + intervalMinutes * 60 * 1000) : null;
  const diffMinutes = nextSyncAt ? Math.round((nextSyncAt.getTime() - now.getTime()) / 60000) : null;
  const elapsedMinutes = lastSyncAt ? Math.max(0, Math.round((now.getTime() - lastSyncAt.getTime()) / 60000)) : null;
  const progress = elapsedMinutes === null ? 100 : Math.min(100, Math.round((elapsedMinutes / intervalMinutes) * 100));

  return {
    intervalMinutes,
    lastSyncAt,
    nextSyncAt,
    elapsedMinutes,
    diffMinutes,
    progress,
  };
}

export function buildSourceSyncBoard(
  sources: BackendSource[],
  syncingIds: Set<number>,
  now: Date
): SourceSyncBoardModel {
  const columns: Record<SyncBoardKey, BackendSource[]> = {
    running: [],
    due: [],
    waiting: [],
    fresh: [],
    error: [],
    paused: [],
  };

  sources.forEach((source) => {
    columns[inferSyncBoardKey(source, syncingIds, now)].push(source);
  });

  syncBoardOrder.forEach((key) => {
    columns[key].sort((a, b) => {
      if (key === 'due') {
        const aDue = getSyncTiming(a, now).diffMinutes ?? -Infinity;
        const bDue = getSyncTiming(b, now).diffMinutes ?? -Infinity;
        if (aDue !== bDue) return aDue - bDue;
      }
      if (key === 'waiting' || key === 'fresh') {
        const aNext = getSyncTiming(a, now).nextSyncAt?.getTime() ?? Infinity;
        const bNext = getSyncTiming(b, now).nextSyncAt?.getTime() ?? Infinity;
        if (aNext !== bNext) return aNext - bNext;
      }
      const orderDiff = (a.sort_order ?? a.id * 10) - (b.sort_order ?? b.id * 10);
      if (orderDiff !== 0) return orderDiff;
      return a.name.localeCompare(b.name);
    });
  });

  const dueCandidates = [...columns.due, ...columns.waiting, ...columns.fresh]
    .sort((a, b) => {
      const aDiff = getSyncTiming(a, now).diffMinutes ?? -Infinity;
      const bDiff = getSyncTiming(b, now).diffMinutes ?? -Infinity;
      return aDiff - bDiff;
    });

  return {
    columns,
    dueCount: columns.due.length,
    healthyCount: columns.running.length + columns.fresh.length + columns.waiting.length,
    errorCount: columns.error.length,
    pausedCount: columns.paused.length,
    nextDueSource: dueCandidates[0] || null,
  };
}
