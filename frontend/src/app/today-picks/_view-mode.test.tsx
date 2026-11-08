import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { PicksViewMode } from './_view-mode';

const render = (grouped = false, topicCount = 0, itemCount = 40, loading = false) => renderToStaticMarkup(
  <PicksViewMode grouped={grouped} topicCount={topicCount} itemCount={itemCount} loading={loading} onChange={() => {}} />,
);
const buttons = (html: string) => html.match(/<button\b[^>]*>/g)!;

describe('精选展示方式', () => {
  it('无分组时明确选中列表、禁用分组并给出可见原因', () => {
    const html = render();
    expect(buttons(html)[0]).toContain('aria-pressed="true"');
    expect(buttons(html)[0]).not.toContain('disabled=""');
    expect(buttons(html)[1]).toContain('aria-pressed="false"');
    expect(buttons(html)[1]).toContain('disabled=""');
    expect(buttons(html)[1]).toContain('aria-describedby="picks-grouping-help"');
    expect(html).toContain('已加载的精选暂无话题分组，按评分展示。');
    expect(html).toContain('精选列表');
    expect(html).toContain('精选分组');
  });
  it('有分组时两个选项可用，真实选中状态对应当前视图', () => {
    for (const grouped of [true, false]) {
      const html = render(grouped, 2);
      expect(buttons(html).every(button => !button.includes('disabled=""'))).toBe(true);
      expect(buttons(html)[0]).toContain(`aria-pressed="${!grouped}"`);
      expect(buttons(html)[1]).toContain(`aria-pressed="${grouped}"`);
      expect(html).not.toContain('picks-grouping-help');
    }
  });
  it('加载时禁用选项，不提前宣称没有分组', () => {
    const html = render(false, 0, 40, true);
    expect(buttons(html).every(button => button.includes('disabled=""'))).toBe(true);
    expect(html).not.toContain('picks-grouping-help');
  });
  it('无文章时不重复显示暂无分组说明', () => {
    expect(render(false, 0, 0)).not.toContain('picks-grouping-help');
  });
});
