import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ProductUpdateItem } from '@/types/product-feedback';
import { archiveDate, filterReleaseNotes } from './_release-filter';
import { ReleaseNote } from './_update-timeline';

const release = (id: number, version: string): ProductUpdateItem => ({ id, version, title: '工作台更连贯', summary: '整理导航和阅读体验', status: 'shipped', created_at: '2026-11-02', updated_at: '2030-01-01', items: [{ kind: 'improvement', title: '返回前台有等待反馈', description: '等待首页时先看到骨架，并保留清楚的页面位置。' }] });

describe('公开更新记录', () => {
  it('只显示已发布记录，编辑时间不会改变历史顺序', () => {
    const older = release(1, '2026.10.31');
    older.updated_at = '2035-01-01';
    const newer = release(2, '2026.11.02');
    const plan = { ...release(3, '2027.01.01'), status: 'planned' as const };
    expect(filterReleaseNotes([older, plan, newer], '', 'all').map(r => r.id)).toEqual([2, 1]);
  });
  it.each(['工作台', '阅读体验', '返回前台', '2026-11-02'])('可以按主题、摘要、条目或日期搜索：%s', query => {
    expect(filterReleaseNotes([release(2, '2026.11.02')], query, 'all')).toHaveLength(1);
  });
  it('按变化类别筛选', () => {
    expect(filterReleaseNotes([release(2, '2026.11.02')], '', 'fix')).toEqual([]);
  });
  it('展示条目标题与说明，不把编辑时间当成功能变化时间', () => {
    const html = renderToStaticMarkup(<ReleaseNote item={release(2, '2026.11.02')} latest />);
    expect(html).toContain('返回前台有等待反馈');
    expect(html).toContain('等待首页时先看到骨架');
    expect(html).not.toContain('2030');
    expect(html).toContain('aria-expanded="true"');
    expect(archiveDate('2026.11.02')).toBe('2026-11-02');
  });
});
