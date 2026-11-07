import { describe, expect, it } from 'vitest';
import { picksViewHref, readPicksView, readSnapshotDays } from '../picks-view';

describe('当日精选视图', () => {
  it('默认精选，辅助视图只接受已声明值', () => {
    expect(readPicksView(null)).toBe('picks');
    expect(readPicksView('topics')).toBe('topics');
    expect(readPicksView('keywords')).toBe('keywords');
    expect(readPicksView('//elsewhere.test')).toBe('picks');
  });
  it('切视图保留精选筛选与独立快照窗口，返回精选去掉辅助视图', () => {
    const current = new URLSearchParams({ category: 'AI', time_range: '48h', level: '值得观察', days: '14' });
    const href = picksViewHref('keywords', current);
    const target = new URL(href, 'https://topiceye.test');
    expect(target.pathname).toBe('/today-picks');
    expect(target.searchParams.get('view')).toBe('keywords');
    expect(target.searchParams.get('time_range')).toBe('48h');
    expect(target.searchParams.get('days')).toBe('14');
    expect(target.searchParams.get('category')).toBe('AI');
    const back = new URL(picksViewHref('picks', target.searchParams), target.origin);
    expect(back.searchParams.has('view')).toBe(false);
    expect(back.searchParams.get('level')).toBe('值得观察');
    expect(current.has('view')).toBe(false);
  });
  it('快照天数受限，不消费精选的24h参数', () => {
    for (const value of ['0', '-1', 'Infinity', '24h', '999', null]) expect(readSnapshotDays(value)).toBe(7);
    expect(readSnapshotDays('3')).toBe(3);
    expect(readSnapshotDays('30')).toBe(30);
  });
});
