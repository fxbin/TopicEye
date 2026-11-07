import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import TrendsPage from './TrendExplorer';
const state = vi.hoisted(() => ({ data: null as unknown, loading: false, error: null as string | null }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ ...state, refetch: vi.fn() }) }));
vi.mock('./TrendEvidenceDrawer', () => ({ default: () => null }));
vi.mock('@/components/SourceLink', () => ({ default: ({ children }: { children: React.ReactNode }) => <span>{children}</span> }));
const snapshot = { topic_id: 1, topic_name: '单次话题', date: '2026-11-03', content_count: 18, pick_count: 5, max_score: 66, avg_score: 50, top_items: [], calculation_version: 'v4' };
const content = (html: string) => html.replace(/<[^>]*>/g, '');
describe('趋势窗口渲染身份', () => {
 it('旧窗口不借给新窗口', () => { state.data = { view: 'topics', days: 14, trends: [snapshot], keywords: [] }; const html = renderToStaticMarkup(<TrendsPage view="topics" days={7} onDaysChange={() => {}} />); expect(html).not.toContain('单次话题'); expect(html).toContain('正在读取近 7 天'); });
 it('单点不可比较且控件前置', () => { state.data = { view: 'topics', days: 7, trends: [snapshot], keywords: [] }; const html = renderToStaticMarkup(<TrendsPage view="topics" days={7} onDaysChange={() => {}} />); expect(html).toContain('仅一次快照，暂无法比较'); expect(html).not.toContain('+18'); expect(html).toContain('按收录与入选数排序'); expect(html.indexOf('aria-label="观察窗口"')).toBeLessThan(html.indexOf('单次话题')); });
 it('预览只取最新快照现有顺序首条，不以最高分或旧快照替代', () => { state.data = { view: 'topics', days: 7, trends: [{ ...snapshot, date: '2026-11-02', top_items: [{ title: '旧快照高分材料', url: '', score: 99 }] }, { ...snapshot, top_items: [{ title: '最新首条材料', url: '', score: 20 }, { title: '最新高分第二条', url: '', score: 98 }] }], keywords: [] }; const html = renderToStaticMarkup(<TrendsPage view="topics" days={7} onDaysChange={() => {}} />); expect(content(html)).toContain('最新首条材料'); expect(content(html)).not.toContain('旧快照高分材料'); expect(content(html)).not.toContain('最新高分第二条'); expect(html).toContain('最新快照 · 首条节选'); expect(html).toContain('aria-expanded="false"'); });
 it('缺节选不借用窗口中的旧材料', () => { state.data = { view: 'topics', days: 7, trends: [{ ...snapshot, date: '2026-11-02', top_items: [{ title: '仅旧日期材料', url: '', score: 99 }] }, snapshot], keywords: [] }; const html = renderToStaticMarkup(<TrendsPage view="topics" days={7} onDaysChange={() => {}} />); expect(content(html)).toContain('本次快照暂无文章节选'); expect(content(html)).not.toContain('仅旧日期材料'); });
 it('从辅助视图返回时保留先前已展开的话题数量', () => { state.data = { view: 'topics', days: 7, trends: Array.from({ length: 26 }, (_, i) => ({ ...snapshot, topic_id: i + 1 })), keywords: [] }; const html = renderToStaticMarkup(<TrendsPage view="topics" days={7} onDaysChange={() => {}} initialLimit={26} />); expect((html.match(/id="topic-trigger-/g) || []).length).toBe(26); });
 it('刷新失败保留当前窗口需说明', () => { state.error = '读取失败'; const html = renderToStaticMarkup(<TrendsPage view="topics" days={7} onDaysChange={() => {}} />); expect(html).toContain('以下保留当前窗口上次成功读取的快照'); state.error = null; });
});
