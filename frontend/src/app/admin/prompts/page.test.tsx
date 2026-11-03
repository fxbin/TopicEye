import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import Page from './page';

const state = vi.hoisted(() => ({ role: 'admin', error: null as string | null, loading: false }));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ currentUser: { role: state.role }, authLoading: false }) }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({
  data: { catalog_expected: 2, total: 2,
    items: ['system', 'user'].map((name, id) => ({ id, name, scene: 'content_analysis', description: '分析模板', source_file: `prompts.analysis:${name}`, version_hash: '12345678' })),
    scenes: [{ scene: 'content_analysis', template_count: 2, stats_7d: { call_count: 12, success_count: 8, failed_count: 4, other_count: 0, total_cost: 0.3 } }],
  }, loading: state.loading, error: state.error, refetch: vi.fn(),
}) }));

describe('提示词目录统计语义', () => {
  it('同场景只展示一组尝试/成功/失败，模板不重复展示成本', () => {
    state.role = 'admin'; state.error = null;
    const html = renderToStaticMarkup(<Page />);
    expect(html.match(/7天请求尝试/g)).toHaveLength(1);
    expect(html.match(/记录成本/g)).toHaveLength(1);
    expect(html).toContain('请求成功');
    expect(html).toContain('请求失败');
    expect(html).toContain('单版模板用量暂不可归因');
    expect(html).toContain('系统模板与用户模板常在同一次请求中使用');
    expect(html).toContain('>system</span>');
    expect(html).toContain('>user</span>');
  });
  it('刷新失败时保留已有场景结果和错误提示', () => {
    state.error = '刷新失败';
    const html = renderToStaticMarkup(<Page />);
    expect(html).toContain('刷新失败');
    expect(html).toContain('7天请求尝试');
  });
  it('普通用户不能读取提示词管理内容', () => {
    state.role = 'user';
    const html = renderToStaticMarkup(<Page />);
    expect(html).toContain('需要管理员权限');
    expect(html).not.toContain('分析模板');
  });
});
