import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { HumanizeRewritePanel } from './_humanize';
import type { HumanizeRewriteSuggestion } from '@/types/content-check';

const suggestion = (over: Partial<HumanizeRewriteSuggestion> = {}): HumanizeRewriteSuggestion => ({
  original: '首先对齐目标，其次沉淀方法论，最后形成可复用的打法',
  rewritten: '先定目标，再把能反复用的做法整理出来，3 个月跑通了 40% 的增长',
  hit_words: ['方法论', '打法'],
  ...over,
});

function renderPanel(over: Partial<React.ComponentProps<typeof HumanizeRewritePanel>> = {}) {
  const props: React.ComponentProps<typeof HumanizeRewritePanel> = {
    suggestions: null,
    loading: false,
    error: null,
    canGenerate: true,
    onGenerate: () => {},
    ...over,
  };
  return renderToStaticMarkup(React.createElement(HumanizeRewritePanel, props));
}

describe('HumanizeRewritePanel', () => {
  it('renders suggestions with original → rewritten pairs and purple hit-word badges', () => {
    const html = renderPanel({ suggestions: [suggestion()] });
    expect(html).toContain('改写建议');
    expect(html).toContain('首先对齐目标，其次沉淀方法论，最后形成可复用的打法'); // 原句
    expect(html).toContain('先定目标，再把能反复用的做法整理出来，3 个月跑通了 40% 的增长'); // 建议句（数字原样）
    expect(html).toContain('>方法论</span>'); // 徽标词
    expect(html).toContain('>打法</span>');
    expect(html).toContain('bg-purple-light'); // 徽标沿用 AI 痕迹紫色系
    expect(html).not.toContain('bg-red-'); // 不染风险红系
  });

  it('renders multiple suggestions as separate items', () => {
    const html = renderPanel({ suggestions: [suggestion(), suggestion({ original: '这套组合拳能够有效赋能创作者', rewritten: '这套做法真能帮创作者用起来', hit_words: ['赋能'] })] });
    expect((html.match(/data-humanize-suggestion/g) ?? []).length).toBe(2);
    expect(html).toContain('这套组合拳能够有效赋能创作者');
  });

  it('disables the button when there is nothing to rewrite and explains why', () => {
    const html = renderPanel({ canGenerate: false });
    expect(html).toContain('disabled'); // 按钮禁用
    expect(html).toContain('暂无可改写的句子');
  });

  it('shows loading state and keeps the button disabled while generating', () => {
    const html = renderPanel({ loading: true });
    expect(html).toContain('生成中…');
    expect(html).toContain('disabled');
    expect(html).not.toContain('暂无可改写的句子'); // loading 不与零命中提示同屏
  });

  it('shows the standalone inline error without hijacking the scan retry UI', () => {
    const html = renderPanel({ error: '改写建议生成失败：模型服务暂不可用，请稍后重试' });
    expect(html).toContain('role="alert"');
    expect(html).toContain('模型服务暂不可用');
    expect(html).not.toContain('重新检测'); // 不复用检测 ErrorState 的重试语义
  });

  it('falls back to a hint when the server returns zero usable suggestions', () => {
    const html = renderPanel({ suggestions: [] });
    expect(html).toContain('本次未生成可用的改写建议');
    expect(html).not.toContain('data-humanize-suggestion');
  });
});
