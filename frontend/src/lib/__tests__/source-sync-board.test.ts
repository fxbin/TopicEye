import { describe, it, expect } from 'vitest';
import {
  sourceTypeLabel,
  parseBackendDate,
  formatInterval,
  formatDuration,
  inferSyncBoardKey,
  getSyncTiming,
  syncBoardOrder,
} from '@/lib/source-sync-board';
import type { BackendSource } from '@/components/SourceRow';

describe('sourceTypeLabel', () => {
  it('maps known types', () => {
    expect(sourceTypeLabel('RSS')).toBe('RSS');
    expect(sourceTypeLabel('RSSHub')).toBe('RSSHub');
    expect(sourceTypeLabel('TwitterRSS')).toBe('Twitter RSS');
    expect(sourceTypeLabel('Reddit')).toBe('Reddit');
    expect(sourceTypeLabel('API')).toBe('API');
    expect(sourceTypeLabel('Zhihu')).toBe('知乎');
    expect(sourceTypeLabel('DouyinHot')).toBe('抖音热榜');
    expect(sourceTypeLabel('网站')).toBe('网站');
  });

  it('passes through unknown types', () => {
    expect(sourceTypeLabel('Unknown')).toBe('Unknown');
    expect(sourceTypeLabel('')).toBe('');
  });
});

describe('parseBackendDate', () => {
  it('returns null for null/empty input', () => {
    expect(parseBackendDate(null)).toBeNull();
    expect(parseBackendDate('')).toBeNull();
  });

  it('parses ISO string with Z suffix', () => {
    const d = parseBackendDate('2024-01-15T10:30:00Z');
    expect(d).toBeInstanceOf(Date);
    expect(d!.toISOString()).toBe('2024-01-15T10:30:00.000Z');
  });

  it('parses ISO string with timezone offset', () => {
    const d = parseBackendDate('2024-01-15T10:30:00+08:00');
    expect(d).toBeInstanceOf(Date);
    expect(d!.toISOString()).toBe('2024-01-15T02:30:00.000Z');
  });

  it('appends Z to naive datetime strings', () => {
    const d = parseBackendDate('2024-01-15T10:30:00');
    expect(d).toBeInstanceOf(Date);
    expect(d!.toISOString()).toBe('2024-01-15T10:30:00.000Z');
  });

  it('returns null for invalid date strings', () => {
    expect(parseBackendDate('not-a-date')).toBeNull();
  });
});

describe('formatInterval', () => {
  it('formats minutes', () => {
    expect(formatInterval(30)).toBe('30 分钟');
  });

  it('formats hours (rounds)', () => {
    expect(formatInterval(90)).toBe('2 小时');
    expect(formatInterval(60)).toBe('1 小时');
  });

  it('formats days (rounds)', () => {
    expect(formatInterval(1440)).toBe('1 天');
    expect(formatInterval(2880)).toBe('2 天');
    expect(formatInterval(1500)).toBe('1 天');
  });
});

describe('formatDuration', () => {
  it('formats minutes', () => {
    expect(formatDuration(0)).toBe('0 分钟');
    expect(formatDuration(45)).toBe('45 分钟');
    expect(formatDuration(59)).toBe('59 分钟');
  });

  it('formats hours without minutes', () => {
    expect(formatDuration(60)).toBe('1 小时');
    expect(formatDuration(120)).toBe('2 小时');
  });

  it('formats hours with remaining minutes', () => {
    expect(formatDuration(90)).toBe('1 小时 30 分钟');
    expect(formatDuration(125)).toBe('2 小时 5 分钟');
  });

  it('formats days without remaining hours', () => {
    expect(formatDuration(1440)).toBe('1 天');
    expect(formatDuration(2880)).toBe('2 天');
  });

  it('formats days with remaining hours', () => {
    expect(formatDuration(1500)).toBe('1 天 1 小时');
    expect(formatDuration(3000)).toBe('2 天 2 小时');
  });

  it('handles negative input by clamping to 0', () => {
    expect(formatDuration(-10)).toBe('0 分钟');
  });
});

describe('syncBoardOrder', () => {
  it('has 6 columns in correct order', () => {
    expect(syncBoardOrder).toEqual(['running', 'due', 'waiting', 'fresh', 'error', 'paused']);
  });
});

function makeSource(overrides: Partial<BackendSource> = {}): BackendSource {
  return {
    id: 1,
    name: 'Test Source',
    url: 'https://example.com',
    source_type: 'RSS',
    status: 'active',
    enabled: true,
    fetch_interval_minutes: 60,
    last_sync_at: null,
    sync_error: null,
    ...overrides,
  } as BackendSource;
}

describe('inferSyncBoardKey', () => {
  const now = new Date('2024-01-15T12:00:00Z');

  it('returns running when id is in syncingIds', () => {
    expect(inferSyncBoardKey(makeSource({ id: 5 }), new Set([5]), now)).toBe('running');
  });

  it('returns running when status is syncing', () => {
    expect(inferSyncBoardKey(makeSource({ status: 'syncing' }), new Set(), now)).toBe('running');
  });

  it('returns paused when disabled', () => {
    expect(inferSyncBoardKey(makeSource({ enabled: false }), new Set(), now)).toBe('paused');
  });

  it('returns paused when status is disabled', () => {
    expect(inferSyncBoardKey(makeSource({ status: 'disabled' }), new Set(), now)).toBe('paused');
  });

  it('returns error when status is error', () => {
    expect(inferSyncBoardKey(makeSource({ status: 'error' }), new Set(), now)).toBe('error');
  });

  it('returns error when sync_error is set', () => {
    expect(inferSyncBoardKey(makeSource({ sync_error: 'timeout' }), new Set(), now)).toBe('error');
  });

  it('returns due when last_sync_at is null', () => {
    expect(inferSyncBoardKey(makeSource({ last_sync_at: null }), new Set(), now)).toBe('due');
  });

  it('returns due when age exceeds interval', () => {
    const oldSync = new Date('2024-01-15T10:00:00Z'); // 2h ago, interval 60min
    expect(inferSyncBoardKey(makeSource({ last_sync_at: oldSync.toISOString(), fetch_interval_minutes: 60 }), new Set(), now)).toBe('due');
  });

  it('returns fresh when age is < 35% of interval', () => {
    const recentSync = new Date('2024-01-15T11:50:00Z'); // 10min ago, interval 60min
    expect(inferSyncBoardKey(makeSource({ last_sync_at: recentSync.toISOString(), fetch_interval_minutes: 60 }), new Set(), now)).toBe('fresh');
  });

  it('returns waiting when age is 35-100% of interval', () => {
    const midSync = new Date('2024-01-15T11:20:00Z'); // 40min ago, interval 60min
    expect(inferSyncBoardKey(makeSource({ last_sync_at: midSync.toISOString(), fetch_interval_minutes: 60 }), new Set(), now)).toBe('waiting');
  });
});

describe('getSyncTiming', () => {
  const now = new Date('2024-01-15T12:00:00Z');

  it('returns correct timing for a source with last sync', () => {
    const lastSync = new Date('2024-01-15T11:00:00Z'); // 1h ago
    const timing = getSyncTiming(makeSource({ last_sync_at: lastSync.toISOString(), fetch_interval_minutes: 60 }), now);
    expect(timing.intervalMinutes).toBe(60);
    expect(timing.lastSyncAt).toEqual(lastSync);
    expect(timing.nextSyncAt).toEqual(new Date('2024-01-15T12:00:00Z'));
    expect(timing.elapsedMinutes).toBe(60);
    expect(timing.diffMinutes).toBe(0);
    expect(timing.progress).toBe(100);
  });

  it('returns 100 progress when last_sync_at is null', () => {
    const timing = getSyncTiming(makeSource({ last_sync_at: null }), now);
    expect(timing.lastSyncAt).toBeNull();
    expect(timing.nextSyncAt).toBeNull();
    expect(timing.elapsedMinutes).toBeNull();
    expect(timing.progress).toBe(100);
  });

  it('uses minimum interval of 5 minutes', () => {
    const timing = getSyncTiming(makeSource({ fetch_interval_minutes: 1 }), now);
    expect(timing.intervalMinutes).toBe(5);
  });

  it('falls back to 60 minutes when fetch_interval is falsy', () => {
    const timing = getSyncTiming(makeSource({ fetch_interval_minutes: 0 as unknown as number }), now);
    expect(timing.intervalMinutes).toBe(60);
  });
});
