import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Badge } from './ui';

/* 回归 #156：中文徽章在 AdminTable 的 auto 列宽下被压成逐字竖排，
 * Badge 基类必须自带 whitespace-nowrap，任何调用方不传 className 也成立。 */
describe('Badge', () => {
  it('never lets CJK badge text wrap per character', () => {
    const html = renderToStaticMarkup(React.createElement(Badge, { tone: 'teal', children: '已分析' }));
    expect(html).toContain('whitespace-nowrap');
    expect(html).toContain('已分析');
  });

  it('keeps nowrap even when callers override className', () => {
    const html = renderToStaticMarkup(
      React.createElement(Badge, {
        tone: 'neutral',
        className: 'rounded px-2.5 py-1 text-[11px] font-semibold',
        children: '待处理',
      }),
    );
    expect(html).toContain('whitespace-nowrap');
  });
});
