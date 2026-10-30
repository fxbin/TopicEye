import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import MuteRulesPanel from './MuteRulesPanel';

// vitest include 只收 *.test.ts（见 vitest.config.ts）；组件测试沿用
// SourceForm.test.ts 的 renderToStaticMarkup + React.createElement 模式。
describe('mute rules panel accessible controls', () => {
  it('associates the add-form select and input with visible labels', () => {
    const html = renderToStaticMarkup(React.createElement(MuteRulesPanel));
    const controls = [...html.matchAll(/<(?:input|select|textarea)\b[^>]*>/g)].map(([tag]) => tag);
    expect(controls.length).toBeGreaterThanOrEqual(2);
    for (const control of controls) {
      const id = control.match(/\bid="([^"]+)"/)?.[1];
      expect(id, control).toBeTruthy();
      expect(html).toContain(`for="${id}"`);
    }
  });

  it('offers exactly the three rule types in the type select', () => {
    const html = renderToStaticMarkup(React.createElement(MuteRulesPanel));
    const select = html.match(/<select\b[^>]*>[\s\S]*?<\/select>/)?.[0] ?? '';
    expect([...select.matchAll(/<option\b[^>]*value="([^"]+)"/g)].map((m) => m[1])).toEqual(['keyword', 'source', 'domain']);
    expect(select).toContain('关键词');
    expect(select).toContain('信源');
    expect(select).toContain('域名');
  });

  it('renders the panel with all three type labels', () => {
    const html = renderToStaticMarkup(React.createElement(MuteRulesPanel));
    expect(html).toContain('降噪规则');
    for (const label of ['关键词', '信源', '域名']) {
      expect(html).toContain(label);
    }
  });
});
