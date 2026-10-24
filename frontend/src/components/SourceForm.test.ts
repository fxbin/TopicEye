import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import SourceForm, { type FormState } from './SourceForm';

const form: FormState = { name: '我的信源', source_type: 'RSS', url: 'https://example.com/feed', keyword: '', category: '', weight: 4, fetch_interval_minutes: 60, enabled: true };

describe('source form accessible controls', () => {
  it.each(['RSS', 'API', 'X'])('associates every %s input with its visible label', (source_type) => {
    const html = renderToStaticMarkup(React.createElement(SourceForm, { form: { ...form, source_type }, setForm: vi.fn() }));
    const controls = [...html.matchAll(/<(?:input|select|textarea)\b[^>]*>/g)].map(([tag]) => tag);
    expect(controls.length).toBeGreaterThanOrEqual(5);
    for (const control of controls) {
      const id = control.match(/\bid="([^"]+)"/)?.[1];
      expect(id, control).toBeTruthy();
      expect(html).toContain(`for="${id}"`);
    }
  });

  it('gives each weight a distinct name and exposes only the selected value', () => {
    const html = renderToStaticMarkup(React.createElement(SourceForm, { form, setForm: vi.fn() }));
    const weights = [...html.matchAll(/<button\b[^>]*aria-label="信源权重[^>]*>/g)].map(([tag]) => tag);
    expect(weights).toHaveLength(5);
    expect(weights.filter(tag => tag.includes('aria-pressed="true"'))).toHaveLength(1);
    expect(weights[3]).toContain('aria-pressed="true"');
    expect(weights.map(tag => tag.match(/aria-label="([^"]+)"/)?.[1])).toEqual([1, 2, 3, 4, 5].map(weight => `信源权重 ${weight} / 5`));
  });
});
