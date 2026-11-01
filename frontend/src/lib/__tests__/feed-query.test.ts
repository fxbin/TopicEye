import { describe, expect, it } from 'vitest';
import { mergeCategoryOptions } from '@/lib/content-categories';
import {
  INITIAL_CONTENT_LIMIT,
  INITIAL_HOURS,
  buildFeedQuery,
  buildTagFacetQuery,
} from '@/lib/feed-query';

describe('mergeCategoryOptions', () => {
  it('把已知分类与列表条目里的分类求并集', () => {
    const result = mergeCategoryOptions(
      ['全部'],
      ['AI 工具', '创作'],
      [{ category: '生活' }, { category: 'AI 工具' }, { category: null }],
    );
    // 顺序按中文 locale 排（ICU 里中文排在拉丁字母前），不写死具体顺序，
    // 断言的是"集合正确 + 顺序与比较器一致"。
    expect(new Set(result)).toEqual(new Set(['全部', 'AI 工具', '生活', '创作']));
    expect(result[0]).toBe('全部');
    expect(result.slice(1)).toEqual(
      [...result.slice(1)].sort((a, b) => a.localeCompare(b, 'zh-CN')),
    );
  });

  it('「全部」永远排第一，其余按中文排序', () => {
    const result = mergeCategoryOptions(['全部', 'B'], ['a'], []);
    expect(result[0]).toBe('全部');
    expect(result.slice(1)).toEqual(['a', 'B']);
  });

  it('忽略空分类名并去重', () => {
    const result = mergeCategoryOptions(['全部'], ['AI', '', 'AI'], [{ category: 'AI' }]);
    expect(result).toEqual(['全部', 'AI']);
  });

  it('没有输入时只返回「全部」', () => {
    expect(mergeCategoryOptions([], [], [])).toEqual(['全部']);
  });
});

describe('首屏查询口径', () => {
  it('列表参数与客户端首屏那次调用逐项一致', () => {
    const params = new URLSearchParams(buildFeedQuery());
    expect(params.get('page_size')).toBe(String(INITIAL_CONTENT_LIMIT));
    expect(params.get('hours')).toBe(String(INITIAL_HOURS));
    expect(params.get('include_trend_sources')).toBe('false');
    expect(params.get('group_events')).toBe('true');
    // stable_feed=true 时后端会返回 feed_snapshot，"加载更多"必须带它
    expect(params.get('stable_feed')).toBe('true');
  });

  it('标签分面参数与客户端一致', () => {
    const params = new URLSearchParams(buildTagFacetQuery());
    expect(params.get('hours')).toBe(String(INITIAL_HOURS));
    expect(params.get('limit')).toBe('16');
  });

  it('默认值就是客户端的首屏口径', () => {
    // 12 是刻意定的：首屏只看得到 3–4 张卡片，而 payload 与条数线性相关
    // （40 条的首屏 HTML 有 544KB，弱网下反而更慢）。理由见 lib/feed-query.ts。
    expect(INITIAL_CONTENT_LIMIT).toBe(12);
    expect(INITIAL_HOURS).toBe(24);
  });
});
