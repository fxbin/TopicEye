import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  parseUTC,
  timeAgo,
  timeAgoShort,
  formatClock,
  formatDateTime,
  formatDate,
  formatTimelineDate,
  isToday,
} from '@/lib/datetime';

// 依赖 vitest.config.ts 里 process.env.TZ='UTC'：本地小时数 == UTC 小时数，
// 使 formatClock / formatDateTime 等断言跨机器稳定。
describe('parseUTC', () => {
  it('无时区后缀按 UTC 解析', () => {
    expect(parseUTC('2026-06-28T10:00:00').getTime()).toBe(Date.UTC(2026, 5, 28, 10, 0, 0));
  });

  it('已带 Z 保持不变', () => {
    expect(parseUTC('2026-06-28T10:00:00Z').getTime()).toBe(Date.UTC(2026, 5, 28, 10, 0, 0));
  });

  it('已带时区偏移保持不变', () => {
    expect(parseUTC('2026-06-28T10:00:00+08:00').getTime()).toBe(Date.UTC(2026, 5, 28, 2, 0, 0));
  });
});

describe('formatClock', () => {
  it('输出 HH:MM', () => {
    expect(formatClock('2026-06-28T14:30:00')).toBe('14:30');
  });

  it('非法输入返回占位符', () => {
    expect(formatClock('not-a-date')).toBe('--:--');
  });
});

describe('formatDate / formatDateTime', () => {
  it('空值返回占位符', () => {
    expect(formatDate(null)).toBe('-');
    expect(formatDateTime(undefined)).toBe('-');
  });

  it('日期含年份', () => {
    expect(formatDate('2026-06-28T10:00:00')).toMatch(/2026/);
  });

  it('日期时间含 HH:MM，includeYear 时带年份', () => {
    expect(formatDateTime('2026-06-28T14:30:00')).toMatch(/\d{2}:\d{2}/);
    expect(formatDateTime('2026-06-28T14:30:00', true)).toMatch(/2026/);
  });
});

describe('相对时间（固定 now）', () => {
  const NOW = new Date('2026-06-28T12:00:00Z');
  const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('timeAgo 覆盖各时间粒度', () => {
    expect(timeAgo(null)).toBe('从未同步');
    expect(timeAgo(ago(30_000))).toBe('刚刚');
    expect(timeAgo(ago(5 * 60_000))).toBe('5 分钟前');
    expect(timeAgo(ago(3 * 3_600_000))).toBe('3 小时前');
    expect(timeAgo(ago(5 * 86_400_000))).toBe('5 天前');
    expect(timeAgo(ago(60 * 86_400_000))).toBe('2 个月前');
  });

  it('timeAgoShort 紧凑格式并处理空值/未来时间', () => {
    expect(timeAgoShort(null)).toBe('-');
    expect(timeAgoShort(new Date(NOW.getTime() + 60_000).toISOString())).toBe('-');
    expect(timeAgoShort(ago(30_000))).toBe('刚刚');
    expect(timeAgoShort(ago(5 * 60_000))).toBe('5分钟前');
    expect(timeAgoShort(ago(2 * 3_600_000))).toBe('2小时前');
    expect(timeAgoShort(ago(3 * 86_400_000))).toBe('3天前');
  });

  it('isToday 判断是否当天', () => {
    expect(isToday(NOW.toISOString())).toBe(true);
    expect(isToday('2020-01-01T00:00:00')).toBe(false);
  });

  it('formatTimelineDate：当天显示「今天」，否则显示日期', () => {
    expect(formatTimelineDate(NOW.toISOString())).toBe('今天');
    const past = formatTimelineDate('2020-01-01T00:00:00');
    expect(past).not.toBe('今天');
    expect(past).toMatch(/\d/);
    expect(formatTimelineDate('garbage')).toBe('未知时间');
  });
});
