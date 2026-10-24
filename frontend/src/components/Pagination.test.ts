import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Pagination } from './Pagination';

describe('pagination boundaries', () => {
  it('empty results disable both navigation actions', () => {
    const html = renderToStaticMarkup(createElement(Pagination, { page: 1, totalPages: 0, onPage: () => {} }));
    expect(html.match(/disabled=""/g)).toHaveLength(2);
    expect(html).not.toContain('第 0 页');
  });
  it('marks exactly one current page and keeps the final window within bounds', () => {
    const html = renderToStaticMarkup(createElement(Pagination, { page: 9, totalPages: 9, onPage: () => {} }));
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
    expect(html).toContain('aria-label="第 9 页"');
    expect(html).not.toContain('aria-label="第 10 页"');
  });
});
