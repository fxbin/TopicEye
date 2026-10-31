/**
 * StageBadge 渲染测试（issue #173）。
 *
 * 覆盖：
 * - stage 为 null/未知 → 不渲染任何内容（后端无窗口数据时 stage 为 null）
 * - 各阶段渲染 Badge 文案与 tone 样式
 * - title 属性展示 stage_reason（判定依据悬浮提示）
 */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { StageBadge } from './_components';

function html(stage: string | null, reason?: string | null) {
  return renderToStaticMarkup(React.createElement(StageBadge, { stage, reason }));
}

describe('StageBadge', () => {
  it('renders nothing when stage is null', () => {
    expect(html(null)).toBe('');
    expect(html(null, '在榜 2 天')).toBe('');
  });

  it('renders nothing for unknown stage values', () => {
    expect(html('not-a-stage')).toBe('');
  });

  it('renders label with the stage tone class', () => {
    const evergreen = html('evergreen');
    expect(evergreen).toContain('常青');
    expect(evergreen).toContain('teal');

    const peaking = html('peaking');
    expect(peaking).toContain('爆发');
    expect(peaking).toContain('primary');

    const declining = html('declining');
    expect(declining).toContain('回落');
    expect(declining).toContain('amber');

    const ferment = html('ferment');
    expect(ferment).toContain('发酵');
  });

  it('exposes stage_reason as the hover title', () => {
    const markup = html('peaking', '排名较上一在榜日上升 45% · 最新排名 11');
    expect(markup).toContain('title="排名较上一在榜日上升 45% · 最新排名 11"');
  });

  it('falls back to the stage label as title when reason is missing', () => {
    expect(html('evergreen')).toContain('title="常青"');
  });
});
