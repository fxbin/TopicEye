import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import KeywordIndex from './KeywordIndex';

const longName = '人工智能在内容创作与研究工作流中的可靠性评估';
const words = Array.from({ length: 60 }, (_, i) => ({ keyword: i === 59 ? longName : `关键词${String(i + 1).padStart(2, '0')}`, count: 59 - i }));

describe('热词频率索引', () => {
  it('全部条目保持接口顺序，零频次与长词仍有完整来源入口', () => {
    const html = renderToStaticMarkup(<KeywordIndex words={words} selectedKeyword={null} onSelect={() => {}} />);
    expect((html.match(/aria-haspopup="dialog"/g) || []).length).toBe(60);
    expect(html.indexOf('关键词03')).toBeLessThan(html.indexOf('关键词04'));
    expect(html.indexOf('关键词04')).toBeLessThan(html.indexOf(longName));
    expect(html).toContain(`aria-label="查看关键词「${longName}」的来源明细"`);
    expect(html).toMatch(/>0<span[^>]*>条/);
  });
  it('来源展开状态只标记所选原始词名，不按显示名或次数合并', () => {
    const html = renderToStaticMarkup(<KeywordIndex words={[{ keyword: 'ai', count: 10000 }, { keyword: 'AI', count: 10000 }]} selectedKeyword="AI" onSelect={() => {}} />);
    expect((html.match(/aria-expanded="true"/g) || []).length).toBe(1);
    expect(html).toMatch(/aria-label="查看关键词「AI」的来源明细"[^>]*aria-expanded="true"/);
    expect(html).toContain('10,000');
    expect(html).not.toContain('%');
  });
});
