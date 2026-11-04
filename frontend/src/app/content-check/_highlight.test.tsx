import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { HighlightText, buildAiTraceHoverTitle, buildHighlightSegments, buildHoverTitle } from './_highlight';
import type { AiTraceWordHit, SensitiveHit } from '@/types/content-check';

const hit = (over: Partial<SensitiveHit>): SensitiveHit => ({
  word: '最好',
  category: 'advertising_extreme',
  severity: 'high',
  start: 0,
  end: 2,
  suggestion: null,
  ...over,
});

const aiHit = (over: Partial<AiTraceWordHit> = {}): AiTraceWordHit => ({
  word: '赋能',
  dimension: 'buzzword',
  start: 0,
  end: 2,
  ...over,
});

describe('buildHighlightSegments', () => {
  it('splits text into plain/hit/plain segments in order', () => {
    const segments = buildHighlightSegments('这是最好的时代', [hit({ start: 2, end: 4 })]);
    expect(segments).toEqual([
      { text: '这是' },
      { text: '最好', hit: hit({ start: 2, end: 4 }) },
      { text: '的时代' },
    ]);
  });

  it('slices by codepoint so astral chars (emoji) keep offsets aligned', () => {
    // 😀 在 JS 里占 2 个 UTF-16 unit，但后端 start=1 是 codepoint 偏移
    const segments = buildHighlightSegments('😀最好的选择', [hit({ start: 1, end: 3 })]);
    expect(segments.map((s) => s.text)).toEqual(['😀', '最好', '的选择']);
    expect(segments[1].hit?.word).toBe('最好');
  });

  it('handles multiple hits, no hits and trailing text', () => {
    const multi = buildHighlightSegments('a最好b绝对c', [
      hit({ word: '绝对', start: 4, end: 6 }),
      hit({ start: 1, end: 3 }),
    ]);
    expect(multi.map((s) => s.text)).toEqual(['a', '最好', 'b', '绝对', 'c']);
    expect(multi.map((s) => Boolean(s.hit))).toEqual([false, true, false, true, false]);

    expect(buildHighlightSegments('干净文稿', [])).toEqual([{ text: '干净文稿' }]);
    expect(buildHighlightSegments('', [])).toEqual([]);
  });

  it('drops out-of-range hits and clamps overlapping ones instead of misplacing highlights', () => {
    const dirty = buildHighlightSegments('最好', [hit({ start: 5, end: 9 })]);
    expect(dirty).toEqual([{ text: '最好' }]);
    // 防御后端契约外的重叠命中：夹取到未渲染区间，文字不重复不错位
    const overlap = buildHighlightSegments('最好绝对', [
      hit({ start: 0, end: 2 }),
      hit({ word: '绝对', start: 1, end: 4 }),
    ]);
    expect(overlap.map((s) => s.text)).toEqual(['最好', '绝对']);
    expect(overlap[0].hit?.word).toBe('最好');
    expect(overlap[1].hit?.word).toBe('绝对');
  });
});

describe('HighlightText rendering', () => {
  it('renders hit words as severity-colored <mark> with hover suggestion in title', () => {
    const html = renderToStaticMarkup(
      React.createElement(HighlightText, {
        text: '全网最低价出手',
        hits: [hit({ word: '全网最低价', start: 0, end: 5, suggestion: '改为「券后 X 元」并确保可验证' })],
      }),
    );
    expect(html).toContain('<mark');
    expect(html).toContain('>全网最低价</mark>'); // 命中词渲染在 mark 内
    expect(html).toContain('出手'); // 命中后的纯文本保留
    expect(html).toContain('data-sensitive-word="全网最低价"');
    expect(html).toContain('bg-red-100'); // high 严重度配色
    expect(decode(html)).toContain('建议：改为「券后 X 元」并确保可验证');
  });

  it('falls back to 删除或改写 hover advice when backend gives no suggestion', () => {
    const html = renderToStaticMarkup(
      React.createElement(HighlightText, {
        text: '远离赌博',
        hits: [hit({ word: '赌博', category: 'political_adult', start: 2, end: 4 })],
      }),
    );
    expect(decode(html)).toContain('建议：删除或改写');
    expect(decode(html)).toContain('高危违禁词');
  });
});

describe('buildHoverTitle', () => {
  it('carries word, category label, severity label and suggestion', () => {
    const title = buildHoverTitle(
      hit({ word: '加微信', category: 'platform_throttle', severity: 'medium', start: 0, end: 3, suggestion: '站外导流表述，删除或改到平台允许的转化路径' }),
    );
    expect(title).toContain('「加微信」平台限流词 · 中风险');
    expect(title).toContain('建议：站外导流表述');
  });
});

describe('AI 痕迹命中高亮', () => {
  it('renders ai trace words as purple <mark> distinct from risk red/yellow', () => {
    const html = renderToStaticMarkup(
      React.createElement(HighlightText, {
        text: '这套打法能够赋能创作者',
        hits: [aiHit({ word: '赋能', start: 6, end: 8 })],
      }),
    );
    expect(html).toContain('<mark');
    expect(html).toContain('>赋能</mark>');
    expect(html).toContain('data-ai-trace-word="赋能"');
    expect(html).toContain('data-ai-trace-dimension="buzzword"');
    expect(html).toContain('bg-purple-light'); // AI 痕迹独立配色，非风险红/黄
    expect(html).not.toContain('bg-red-100');
    expect(decode(html)).toContain('启发式统计');
  });

  it('renders sensitive and ai trace hits together, each with its own color', () => {
    const html = renderToStaticMarkup(
      React.createElement(HighlightText, {
        text: '最好的增长抓手是赋能用户',
        hits: [hit({ word: '最好', start: 0, end: 2 }), aiHit({ word: '抓手', start: 5, end: 7 }), aiHit({ word: '赋能', start: 8, end: 10 })],
      }),
    );
    expect(html).toContain('bg-red-100'); // 风险命中红色
    expect(html).toContain('bg-purple-light'); // AI 痕迹命中紫色
    expect(html).toContain('>最好</mark>');
    expect(html).toContain('>抓手</mark>');
    expect(html).toContain('>赋能</mark>');
  });

  it('prefers the sensitive hit on an identical span (risk verdict outranks writing advice)', () => {
    const segments = buildHighlightSegments('最好的选择', [
      aiHit({ word: '最好', start: 0, end: 2 }),
      hit({ word: '最好', start: 0, end: 2 }),
    ]);
    expect(segments).toEqual([
      { text: '最好', hit: hit({ start: 0, end: 2 }) },
      { text: '的选择' },
    ]);
  });

  it('keeps ai trace offsets aligned on codepoints (emoji before the hit)', () => {
    const segments = buildHighlightSegments('😀这个闭环跑通了', [aiHit({ word: '闭环', start: 3, end: 5 })]);
    expect(segments.map((s) => s.text)).toEqual(['😀这个', '闭环', '跑通了']);
    expect(segments[1].hit?.dimension).toBe('buzzword');
  });
});

describe('buildAiTraceHoverTitle', () => {
  it('carries word, dimension label and the heuristic caliber', () => {
    expect(buildAiTraceHoverTitle(aiHit({ word: '抓手', dimension: 'buzzword', start: 0, end: 2 }))).toContain(
      '「抓手」AI 高频词 · 启发式统计',
    );
    expect(buildAiTraceHoverTitle(aiHit({ word: '首先', dimension: 'connective', start: 0, end: 2 }))).toContain(
      '「首先」套话连接词 · 启发式统计',
    );
    expect(buildAiTraceHoverTitle(aiHit())).toContain('建议：换成具体动作、数字或事例');
  });
});

/** renderToStaticMarkup 会把 title 里的换行转义成 &#xA; 之类的实体，比对前还原。 */
function decode(html: string): string {
  return html
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(Number(dec)))
    .replace(/\n/g, '');
}
