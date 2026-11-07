import { describe, expect, it } from 'vitest';
import type { TrendPoint } from '@/types/trends';
import { buildTrendModel } from './_trend-model';

function point(overrides: Partial<TrendPoint> = {}): TrendPoint {
  return {
    date: '2026-11-06', topic_id: 1, topic_name: '人工智能',
    content_count: 18, avg_score: 70, max_score: 80, pick_count: 2,
    top_items: null, calculation_version: 'v4', ...overrides,
  };
}

describe('buildTrendModel', () => {
  it('keeps a single snapshot as one point with no fabricated +18 growth', () => {
    const { topics } = buildTrendModel([point()]);
    expect(topics[0]).toMatchObject({
      latestCount: 18, latestDate: '2026-11-06', previousDate: null,
      delta: null, momentum: 20,
    });
    expect(topics[0].pts).toHaveLength(1);
  });

  it('preserves a recorded zero and calculates a real decline', () => {
    const { topics } = buildTrendModel([
      point({ date: '2026-11-05', content_count: 18 }),
      point({ content_count: 0, pick_count: 0 }),
    ]);
    expect(topics[0]).toMatchObject({ latestCount: 0, delta: -18, momentum: 2 });
    expect(topics[0].pts[1].content_count).toBe(0);
  });

  it('allows growth from a recorded zero with matching versions', () => {
    const { topics } = buildTrendModel([
      point({ date: '2026-11-05', content_count: 0, calculation_version: 'v2' }),
      point({ calculation_version: 'v2' }),
    ]);
    expect(topics[0]).toMatchObject({ delta: 18, momentum: 58 });
  });

  it('fills the shared calendar axis without inventing topic snapshots', () => {
    const { topics, dates, recordedDays, latestDate } = buildTrendModel([
      point({ date: '2026-10-31', content_count: 4 }),
      point({ date: '2026-11-02' }),
    ]);
    expect(dates).toEqual(['2026-10-31', '2026-11-01', '2026-11-02']);
    expect(recordedDays).toBe(2);
    expect(latestDate).toBe('2026-11-02');
    expect(topics[0].pts).toHaveLength(2);
    expect(topics[0]).toMatchObject({ delta: null, momentum: 22, previousDate: '2026-10-31' });
  });

  it.each([
    ['v1', 'v2', null],
    [null, 'v2', null],
    ['v1', undefined, null],
    [null, undefined, null],
    [undefined, null, null],
    [undefined, undefined, null],
  ])('compares versions %s and %s as delta %s', (before, after, delta) => {
    const { topics } = buildTrendModel([
      point({ date: '2026-11-05', content_count: 4, calculation_version: before }),
      point({ calculation_version: after }),
    ]);
    expect(topics[0].delta).toBe(delta);
  });

  it('groups by stable id, takes the latest name, and sorts points without mutating input', () => {
    const latest = point({ topic_name: '新名称' });
    const earlier = point({ date: '2026-11-05', topic_name: '旧名称' });
    const input = [latest, point({ topic_id: 2, topic_name: '新名称' }), earlier];
    const { topics, totalContent, totalPicks, recordedDays } = buildTrendModel(input);
    expect(topics).toHaveLength(2);
    expect(topics[0]).toMatchObject({ topicId: 1, name: '新名称', total: 36, picks: 4 });
    expect(topics[0].pts).toEqual([earlier, latest]);
    expect(input[0]).toBe(latest);
    expect(totalContent).toBe(54);
    expect(totalPicks).toBe(6);
    expect(recordedDays).toBe(2);
  });

  it('selects the highest scored representative across the whole window', () => {
    const best = { title: '较早的高分内容', url: 'https://example.com/best', score: 98 };
    const { topics } = buildTrendModel([
      point({ date: '2026-11-05', max_score: 98, top_items: [best] }),
      point({ top_items: [{ title: '最新内容', url: 'https://example.com/latest', score: 80 }] }),
    ]);
    expect(topics[0].topItem).toEqual(best);
    expect(topics[0].maxScore).toBe(98);
  });

  it('sorts by momentum, then by ascending topic id', () => {
    const { topics } = buildTrendModel([
      point({ topic_id: 3 }), point({ topic_id: 2, content_count: 30 }), point({ topic_id: 1 }),
    ]);
    expect(topics.map((topic) => topic.topicId)).toEqual([2, 1, 3]);
  });

  it('fills a 31 day API window across a year boundary', () => {
    const { dates, recordedDays } = buildTrendModel([
      point({ date: '2025-12-20' }), point({ date: '2026-01-19' }),
    ]);
    expect(dates).toHaveLength(31);
    expect(dates[0]).toBe('2025-12-20');
    expect(dates[30]).toBe('2026-01-19');
    expect(recordedDays).toBe(2);
  });

  it('returns explicit empty values', () => {
    expect(buildTrendModel([])).toEqual({
      topics: [], dates: [], totalContent: 0, totalPicks: 0, latestDate: null, recordedDays: 0,
    });
    expect(buildTrendModel([point()]).topics[0].topItem).toBeNull();
  });
});
