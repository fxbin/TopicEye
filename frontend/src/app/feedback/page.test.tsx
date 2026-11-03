import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import FeedbackPage from './page';

const state = vi.hoisted(() => ({ user: { id: 1, role: 'user' } as { id: number; role: string } | null, data: null as unknown, error: null as string | null, loading: false, fetcher: null as (() => Promise<unknown>) | null }));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ currentUser: state.user, authLoading: false }) }));
const api = vi.hoisted(() => ({ listMine: vi.fn().mockResolvedValue({ items: [], total: 0 }), listIssues: vi.fn(), createIssue: vi.fn() }));
vi.mock('@/lib/api', () => ({ productFeedbackApi: api }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: (fetcher: () => Promise<unknown>) => {
  state.fetcher = fetcher;
  return { data: state.data, error: state.error, loading: state.loading, refetch: vi.fn() };
} }));

describe('前台反馈', () => {
  it('历史只请求当前用户接口，不读取后台的全部用户列表', async () => {
    state.user = { id: 1, role: 'user' };
    state.data = null;
    state.error = null;
    renderToStaticMarkup(<FeedbackPage />);
    await state.fetcher?.();
    expect(api.listMine).toHaveBeenCalledWith({ limit: 10, offset: 0 });
    expect(api.listIssues).not.toHaveBeenCalled();
  });
  it('普通用户可提交并查看个人处理回复和分页，没有后台入口', () => {
    state.user = { id: 1, role: 'user' };
    state.data = { total: 11, items: [{ id: 1, title: '我的问题', description: '问题的详细描述', status: 'fixed', resolution_note: '已经修好', created_at: '2026-11-03T00:00:00Z' }] };
    state.error = null;
    const html = renderToStaticMarkup(<FeedbackPage />);
    expect(html).toContain('feedback-title');
    expect(html).toContain('feedback-description');
    expect(html).toContain('已经修好');
    expect(html).toContain('下一页');
    expect(html).not.toContain('/admin');
  });
  it('历史加载失败显示重试，不伪装成暂无记录', () => {
    state.data = null;
    state.error = '获取个人历史失败';
    const html = renderToStaticMarkup(<FeedbackPage />);
    expect(html).toContain('获取个人历史失败');
    expect(html).not.toContain('还没有反馈记录');
  });
  it('未登录保留返回反馈页的登录入口，不渲染个人记录', () => {
    state.user = null;
    const html = renderToStaticMarkup(<FeedbackPage />);
    expect(html).toContain('href="/login?returnTo=%2Ffeedback"');
    expect(html).not.toContain('我的问题');
    expect(html).not.toContain('<form');
  });
});
