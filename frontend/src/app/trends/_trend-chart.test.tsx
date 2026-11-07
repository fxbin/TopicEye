import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { TrendChart } from './_trend-chart';
import type { TrendPoint } from '@/types/trends';
const point = (date: string, count: number, version = 'v4'): TrendPoint => ({ date, content_count: count, topic_id: 1, topic_name: '话题', pick_count: 0, avg_score: 0, max_score: 0, top_items: [], calculation_version: version });
const render = (points: TrendPoint[], dates = ['2026-11-03', '2026-11-04', '2026-11-05']) => renderToStaticMarkup(<TrendChart name="话题" dates={dates} points={points} selectedDate={points.at(-1)!.date} />);
describe('只画真实、可比的相邻快照', () => {
 it('单点不制造下降线，缺记录仍读为无快照', () => { const html = render([point('2026-11-03', 18)]); expect(html).not.toContain('data-trend-segment'); expect(html).toContain('2026-11-04：无快照'); });
 it('缺口不跨日连线', () => expect(render([point('2026-11-03', 2), point('2026-11-05', 7)])).not.toContain('data-trend-segment'));
 it('真实零值连接并保留可读值', () => { const html = render([point('2026-11-03', 2), point('2026-11-04', 0)]); expect(html).toContain('data-trend-segment'); expect(html).toContain('2026-11-04：0条'); });
 it('双方缺失版本也不连线', () => expect(render([{...point('2026-11-03', 2), calculation_version: null}, {...point('2026-11-04', 3), calculation_version: undefined}])).not.toContain('data-trend-segment'));
 it('不同口径不连线', () => expect(render([point('2026-11-03', 2), point('2026-11-04', 7, 'v5')])).not.toContain('data-trend-segment'));
});
