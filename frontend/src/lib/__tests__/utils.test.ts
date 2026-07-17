import { describe, it, expect } from 'vitest';
import type { ContentAnalysis, ContentItem } from '@/types';
import { T } from '@/lib/design-tokens';
import {
  weightStars,
  extractRiskNotes,
  extractCreatorAngles,
  extractTags,
  extractTitleSuggestions,
  extractKeyPoints,
  getTagColor,
  getRecommendLevelLabel,
  formatPlanText,
} from '@/lib/utils';

const analysis = (o: Record<string, unknown>): ContentAnalysis => o as unknown as ContentAnalysis;
const item = (o: Record<string, unknown>): ContentItem => o as unknown as ContentItem;

describe('weightStars', () => {
  it('按权重渲染实心/空心圆，且封顶 5', () => {
    expect(weightStars(3)).toBe('●●●○○');
    expect(weightStars(5)).toBe('●●●●●');
    expect(weightStars(7)).toBe('●●●●●');
    expect(weightStars(0)).toBe('○○○○○');
  });
});

describe('extractRiskNotes', () => {
  it('analysis 为空返回空数组', () => {
    expect(extractRiskNotes(null)).toEqual([]);
  });

  it('字符串形式', () => {
    expect(extractRiskNotes(analysis({ risk_notes: '注意合规' }))).toEqual(['注意合规']);
    expect(extractRiskNotes(analysis({ risk_notes: '' }))).toEqual([]);
  });

  it('数组形式（过滤空串与非字符串）', () => {
    expect(extractRiskNotes(analysis({ risk_notes: ['a', '', 'b', 123] }))).toEqual(['a', 'b']);
  });

  it('对象形式（展开字符串与字符串数组）', () => {
    expect(
      extractRiskNotes(analysis({ risk_notes: { k1: 'x', k2: ['y', 'z', ''], k3: 123 } })),
    ).toEqual(['x', 'y', 'z']);
  });
});

describe('extract* helpers', () => {
  it('extractCreatorAngles', () => {
    expect(extractCreatorAngles(analysis({ creator_angles: ['角度1', '角度2'] }))).toEqual(['角度1', '角度2']);
    expect(extractCreatorAngles(null)).toEqual([]);
  });

  it('extractTitleSuggestions', () => {
    expect(extractTitleSuggestions(analysis({ title_suggestions: ['t1', 't2'] }))).toEqual(['t1', 't2']);
    expect(extractTitleSuggestions(null)).toEqual([]);
  });

  it('extractKeyPoints', () => {
    expect(extractKeyPoints(analysis({ key_points: ['k1', 'k2'] }))).toEqual(['k1', 'k2']);
    expect(extractKeyPoints(null)).toEqual([]);
  });

  it('extractTags 合并 item 与 analysis 并去重', () => {
    expect(extractTags(item({ tags: ['a', 'b'] }), analysis({ tags: ['b', 'c'] }))).toEqual(['a', 'b', 'c']);
  });
});

describe('getTagColor', () => {
  it('已知标签返回专属色，未知标签回退到 gray400', () => {
    expect(getTagColor('模型')).toBe('#8B5CF6');
    expect(getTagColor('不存在的标签')).toBe(T.gray400);
  });
});

describe('getRecommendLevelLabel', () => {
  it('复用推荐决策的等级', () => {
    const strong = analysis({
      quality_score: 60,
      hot_score: 60,
      freshness_score: 60,
      creator_score: 90,
      viral_score: 60,
      risk_score: 20,
    });
    expect(getRecommendLevelLabel(strong)).toBe('强烈建议写');
  });
});

describe('formatPlanText', () => {
  it('渲染完整创作方案的各段落', () => {
    const text = formatPlanText({
      titles: ['标题A', '标题B'],
      cover_slogan: '封面语',
      structure: { hook: '钩子', points: ['要点1', '要点2'], cta: '关注我' },
      scenes: [{ seq: 1, seconds: 5, visual: '画面', narration: '旁白' }],
      outline: [{ section: 1, heading: '引言', points: ['p1', 'p2'] }],
      tags: ['ai', '效率'],
      tone: '专业',
    });
    expect(text).toContain('【备选标题】');
    expect(text).toContain('1. 标题A');
    expect(text).toContain('封面文案：封面语');
    expect(text).toContain('Hook: 钩子');
    expect(text).toContain('- 要点1');
    expect(text).toContain('互动引导: 关注我');
    expect(text).toContain('镜头1(5s): 画面');
    expect(text).toContain('【文章大纲】');
    expect(text).toContain('标签：#ai #效率');
    expect(text).toContain('风格：专业');
  });

  it('空方案返回空串', () => {
    expect(formatPlanText({})).toBe('');
  });
});
