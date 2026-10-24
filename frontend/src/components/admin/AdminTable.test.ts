import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { AdminTable, type AdminTableColumn } from './AdminTable';

const layout = vi.hoisted(() => ({ narrow: false }));
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useSyncExternalStore: () => layout.narrow,
}));

const columns: AdminTableColumn<{ id: number; title: string }>[] = [
  { key: 'title', header: '标题', render: row => row.title },
  { key: 'status', header: '状态', render: () => '待审核' },
  { key: 'notes', header: '判断理由', render: () => '不同来源的同一事件' },
  { key: 'version', header: '版本', render: () => 'v2' },
  { key: 'draft', header: '审核意见', mobileAlwaysVisible: true, render: () => React.createElement('input', { 'aria-label': '审核理由', defaultValue: '尚未提交的判断' }) },
  { key: 'actions', header: '操作', sticky: 'right', render: () => React.createElement('button', { type: 'button' }, '接受') },
];
const rows = [{ id: 7, title: '需要审核的内容' }];

function render(narrow: boolean) {
  layout.narrow = narrow;
  return renderToStaticMarkup(React.createElement(AdminTable<{ id: number; title: string }>, { columns, rows, rowKey: row => row.id, selectable: true, selected: new Set([7]), onSelectedChange: vi.fn() }));
}

describe('responsive admin objects', () => {
  it.each([true, false])('keeps exactly one editor and action in narrow=%s', narrow => {
    const html = render(narrow);
    expect(html.match(/aria-label="审核理由"/g)).toHaveLength(1);
    expect(html.match(/>接受<\/button>/g)).toHaveLength(1);
    expect(html).toContain('尚未提交的判断');
    expect(html).toContain('需要审核的内容');
    expect(html).toContain('aria-label="选择第 1 行"');
  });

  it('keeps the row editor outside collapsed mobile metadata', () => {
    const html = render(true);
    expect(html).not.toContain('<table');
    expect(html).toContain('<article');
    const details = html.match(/<details\b[^>]*>([\s\S]*?)<\/details>/)?.[1];
    expect(details).toContain('版本');
    expect(details).not.toContain('审核理由');
    expect(html).toContain('checked=""');
  });

  it('keeps the desktop fallback visible when media subscription has not switched', () => {
    const html = render(false);
    expect(html).toContain('<table');
    expect(html).not.toContain('<article');
    const tableShell = html.match(/<div class="([^"]*)"><table/)?.[1];
    expect(tableShell).toBeTruthy();
    expect(tableShell?.split(/\s+/)).not.toContain('hidden');
  });
});
