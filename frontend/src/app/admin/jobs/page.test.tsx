import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import JobStatsPage from './page';

const state = vi.hoisted(() => ({ data: null as unknown, loading: false, error: null as string | null }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ ...state, refetch: vi.fn() }) }));

const data = {
  period: { days: 7 },
  totals: { total_runs: 14916, success_count: 13778, failed_count: 0, timeout_count: 884, success_rate: .924, avg_duration_ms: 38000, max_duration_ms: 726000 },
  by_status: [{ status: 'SUCCESS', count: 13778 }, { status: 'TIMEOUT', count: 884 }],
  by_job_key: [{ job_key: 'post_sync_clustering', runs: 669, success_rate: .016, avg_duration_ms: 594000, last_status: 'RUNNING', last_run_at: null }],
  recent_failures: [{ job_key: 'very_long_job_key_'.repeat(10), status: 'TIMEOUT', started_at: null, duration_ms: 300000, error_message: 'long error '.repeat(50) }],
};
const render = () => renderToStaticMarkup(<JobStatsPage />);

describe('任务监控布局与数据状态', () => {
  it('所有带标题的内容区都保留 Surface 的内边距', () => {
    Object.assign(state, { data, loading: false, error: null });
    const html = render();
    for (const title of ['状态分布', '各任务运行情况', '最近失败 / 超时']) {
      const section = html.match(new RegExp(`<section[^>]*class="([^"]*)"[^>]*>(?:(?!<section)[\\s\\S])*?<h2[^>]*>${title}</h2>`));
      expect(section, title).not.toBeNull();
      expect(section![1]).toContain('p-4.5');
      expect(section![1]).toContain('sm:p-5');
    }
    expect(html).toContain('post_sync_clustering');
    expect(html).toContain('min-w-[640px]');
    expect(html).toContain('overflow-x-auto');
    expect(html).toContain('break-all');
  });

  it('首次加载显示骨架，避免空态闪成数据', () => {
    Object.assign(state, { data: null, loading: true, error: null });
    const html = render();
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toContain('该窗口内没有运行记录');
    expect(html).not.toContain('没有匹配的任务');
  });

  it('刷新时保留原数据与布局', () => {
    Object.assign(state, { data, loading: true, error: null });
    const html = render();
    expect(html).toContain('post_sync_clustering');
    expect(html).not.toContain('aria-busy="true"');
  });

  it('请求失败不能伪装成没有记录', () => {
    Object.assign(state, { data: null, loading: false, error: '网络连接失败' });
    const html = render();
    expect(html).toContain('网络连接失败');
    expect(html).not.toContain('该窗口内没有运行记录');
    expect(html).not.toContain('没有匹配的任务');
  });

  it('加载完成后才展示真实空态', () => {
    Object.assign(state, { data: { ...data, by_status: [], by_job_key: [], recent_failures: [] }, loading: false, error: null });
    const html = render();
    expect(html).toContain('该窗口内没有运行记录');
    expect(html).toContain('没有匹配的任务');
  });
});
