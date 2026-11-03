import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import SourceBadge from './SourceBadge';

describe('公共文章来源标注', () => {
  it('来源名与类型可读，不送往无关的个人管理页', () => {
    const html = renderToStaticMarkup(<SourceBadge name="公共科技信源" type="RSS" />);
    expect(html).toContain('公共科技信源');
    expect(html).toContain('RSS');
    expect(html).not.toContain('<a');
    expect(html).not.toContain('/sources');
  });
});
