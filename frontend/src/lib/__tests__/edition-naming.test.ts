import { describe, it, expect } from 'vitest';
import { EDITION_LABELS, dailyEditionLabel } from '@/lib/edition-naming';

/**
 * #132 刊物种属「情报正族」的单点契约。
 *
 * 眉题在报头承担「这是哪种刊物」的种属职能（命名圆桌 r1-s1/r3-s2）：
 * 当日期「今日情报」，历史期（?date= 深链）用日期中性的「每日情报」——
 * 否则历史期报头会出现「今日情报 / 2026-09-01」的自相矛盾（#132 复审 N4）。
 */
describe('EDITION_LABELS', () => {
  it('情报正族四值 + 日期中性形式', () => {
    expect(EDITION_LABELS.daily).toBe('今日情报');
    expect(EDITION_LABELS.daily_neutral).toBe('每日情报');
    expect(EDITION_LABELS.weekly).toBe('每周情报');
    expect(EDITION_LABELS.monthly).toBe('每月情报');
    expect(EDITION_LABELS.special).toBe('专题情报');
  });
});

describe('dailyEditionLabel', () => {
  it('当日报 → 今日情报', () => {
    const now = new Date();
    const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    expect(dailyEditionLabel(iso)).toBe('今日情报');
  });

  it('历史期 → 每日情报（日期中性）', () => {
    expect(dailyEditionLabel('2020-01-01')).toBe('每日情报');
  });

  it('缺日期 → 每日情报（保守中性）', () => {
    expect(dailyEditionLabel()).toBe('每日情报');
    expect(dailyEditionLabel(null)).toBe('每日情报');
  });
});
