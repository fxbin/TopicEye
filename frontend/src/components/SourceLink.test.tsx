import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import SourceLink from './SourceLink';

describe('原文链接的缺失状态', () => {
  it.each([undefined, null, '', '#', 'javascript:alert(1)'])('缺少有效原文地址 %j 时不跳转', href => {
    const html = renderToStaticMarkup(<SourceLink href={href} target="_blank">榜单条目</SourceLink>);
    expect(html).not.toContain('<a');
    expect(html).not.toContain('href=');
    expect(html).toContain('暂无原文链接');
    expect(html).toContain('榜单条目');
  });
  it('有效原文链接仍可打开', () => {
    expect(renderToStaticMarkup(<SourceLink href="https://example.com/news" target="_blank" rel="noopener noreferrer">原文</SourceLink>)).toContain('href="https://example.com/news"');
  });
});
