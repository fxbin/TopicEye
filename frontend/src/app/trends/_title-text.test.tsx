import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import TitleText from './_title-text';

describe('原题中文断行', () => {
  it('最高与美元不被拆成单字，原题文本保持完整', () => {
    const title = 'Meta MSL 漏洞赏金计划：单个报告最高 30 万美元，提示词注入最高 13 万美元';
    const html = renderToStaticMarkup(<TitleText title={title} />);
    expect(html).toMatch(/<span[^>]*>最高<\/span>/);
    expect(html).toMatch(/<span[^>]*>美元<\/span>/);
    expect(html.replace(/<[^>]*>/g, '')).toBe(title);
  });
  it('中英混排的空格和标点保持原样，内容按文本转义', () => {
    const html = renderToStaticMarkup(<TitleText title={'AI <script> & 原题（2026）'} />);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html.replace(/<[^>]*>/g, '')).toBe('AI &lt;script&gt; &amp; 原题（2026）');
  });
});
