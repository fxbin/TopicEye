import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { MaterialPage } from './TopicMaterials';

const state = vi.hoisted(() => ({ data: null as unknown, loading: false, error: null as string | null }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ ...state, refetch: vi.fn() }) }));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ openReader: vi.fn() }) }));
vi.mock('@/components/SourceBadge', () => ({ default: () => null }));
vi.mock('@/components/EvidenceTag', () => ({ default: () => null }));
const payload = {
  summary: { content_count: 25, source_count: 2, provenance_status: 'sample_only' },
  calculation: { event_members_excluded: false },
  items: [{ content_id: null, title: '前一页的材料', url: null, selected: false, score: null }],
  total: 25,
};
const render = (page: number) => renderToStaticMarkup(<MaterialPage topicId={1} date="2026-11-03" filter="all" page={page} setPage={vi.fn()} />);

const content = (html: string) => html.replace(/<[^>]*>/g, '');
describe('材料分页请求边界', () => {
  it('翻页加载保留分页控件，隐藏前一页的内容', () => {
    state.data = { page: 1, payload }; state.loading = true; state.error = null;
    const html = render(2);
    expect(content(html)).not.toContain('前一页的材料');
    expect(html).toContain('正在读取这次快照的材料');
    expect(html).toContain('aria-label="下一页材料"');
    expect(html).toContain('aria-label="上一页材料"');
    expect(html).toContain('2 / 2 页 · 读取中');
  });
  it('翻页失败仍保留分页与重试入口，不把旧页当新页', () => {
    state.data = { page: 1, payload }; state.loading = false; state.error = '材料读取失败';
    const html = render(2);
    expect(content(html)).not.toContain('前一页的材料');
    expect(html).toContain('role="alert"');
    expect(html).toContain('重试');
    expect(html).toContain('aria-label="上一页材料"');
  });
  it('不完整历史并列说明历史收录与实际可查看数量', () => {
    state.data = { page: 1, payload: { ...payload, total: 3, summary: { ...payload.summary, content_count: 0 }, daily_counts: [{ date: '2026-11-03', count: 25 }] } }; state.loading = false; state.error = null;
    const html = render(1);
    expect(html).toContain('当前可查看 <b>3</b> 条');
    expect(html).toContain('历史收录 25 条');
  });
  it('新页成功后只显示新页，并保留不完整记录提示', () => {
    state.data = { page: 2, payload: { ...payload, items: [{ ...payload.items[0], title: '第二页的材料' }] } }; state.loading = false; state.error = null;
    const html = render(2);
    expect(content(html)).toContain('第二页的材料');
    expect(content(html)).not.toContain('前一页的材料');
    expect(html).toContain('历史成员记录不完整');
    expect(html).toContain('当前可查看');
    expect(html).toContain('历史收录');
    expect(html).toContain('不能还原当时全部内容');
    expect(html).toContain('aria-disabled="true"');
  });
});
