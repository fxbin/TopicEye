import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import UpdatesPage from '@/app/admin/updates/page';
import WeReadPage from '@/app/weread/page';

const state = vi.hoisted(() => ({ data: null, loading: true, error: null as string | null }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ ...state, refetch: vi.fn() }) }));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ currentUser: { id: 22, role: 'admin' }, authLoading: false }) }));

describe('工作台状态变化保留页面锚点', () => {
  it('发版列表首次加载时保留主标题且不显示假空态', () => {
    Object.assign(state, { data: null, loading: true, error: null });
    const html = renderToStaticMarkup(<UpdatesPage />);
    expect(html).toContain('发版记录管理');
    expect(html).toContain('正在加载发版管理');
    expect(html).not.toContain('还没有发版记录');
  });
  it.each([true, false])('微信读书 loading=%s 时仍保留标题，错误不会冒充空书架', loading => {
    Object.assign(state, { data: null, loading, error: loading ? null : '请求失败' });
    const html = renderToStaticMarkup(<WeReadPage />);
    expect(html).toContain('微信读书书架');
    expect(html).toContain('workspace-scroll');
    expect(html).not.toContain('还没有微信读书素材');
    if (!loading) expect(html).toContain('请求失败');
  });
});
