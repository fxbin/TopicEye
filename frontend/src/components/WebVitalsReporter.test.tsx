import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { useReportWebVitals } from 'next/web-vitals';

vi.mock('next/navigation', () => ({
  usePathname: () => '/trending',
}));

vi.mock('next/web-vitals', () => ({
  useReportWebVitals: vi.fn(),
}));

import WebVitalsReporter from '@/components/WebVitalsReporter';

describe('WebVitalsReporter', () => {
  it('渲染为空，不产生任何可见标记', () => {
    expect(renderToStaticMarkup(<WebVitalsReporter />)).toBe('');
  });

  it('注册采集器时传的是一个可调用的回调', () => {
    (useReportWebVitals as unknown as ReturnType<typeof vi.fn>).mockClear();
    renderToStaticMarkup(<WebVitalsReporter />);
    const calls = (useReportWebVitals as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls).toHaveLength(1);
    expect(typeof calls[0][0]).toBe('function');
  });
});
