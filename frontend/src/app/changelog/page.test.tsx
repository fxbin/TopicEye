import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import ChangelogPage from './page';

const state = vi.hoisted(() => ({ data: null as unknown, loading: true, error: null as string | null, role: 'user' }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ data: state.data, loading: state.loading, error: state.error, refetch: vi.fn() }) }));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ currentUser: { role: state.role }, authLoading: false }) }));
const record = { id: 1, version: '2026.11.02', title: '工作台与后台导航统一', summary: '页面切换更连贯', status: 'shipped', items: [] };

describe('更新记录页面状态', () => {
  it('首次加载保留页面标题和搜索入口', () => {
    Object.assign(state, { data: null, loading: true, error: null, role: 'user' });
    const html = renderToStaticMarkup(<ChangelogPage />);
    expect(html).toContain('更新记录</h1>');
    expect(html).toContain('release-search');
    expect(html).toContain('正在加载更新记录');
    expect(html).not.toContain('还没有已发布的更新');
  });
  it('计划不混入历史，普通用户不显示后台管理入口', () => {
    Object.assign(state, { data: [record, { ...record, id: 2, title: '尚未完成的计划', status: 'planned' }], loading: false, error: null });
    const html = renderToStaticMarkup(<ChangelogPage />);
    expect(html).toContain('工作台与后台导航统一');
    expect(html).not.toContain('尚未完成的计划');
    expect(html).not.toContain('管理更新');
  });
  it('刷新出错仍保留已加载内容', () => {
    Object.assign(state, { data: [record], loading: false, error: '网络错误' });
    const html = renderToStaticMarkup(<ChangelogPage />);
    expect(html).toContain('网络错误');
    expect(html).toContain('工作台与后台导航统一');
  });
});
