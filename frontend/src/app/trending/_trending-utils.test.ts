/**
 * 生命周期阶段徽章映射测试（issue #173）。
 *
 * 覆盖：
 * - STAGE_META 四阶段的文案与 tone（常青=teal / 爆发=primary / 回落=amber / 发酵=neutral）
 * - stageMeta 的 null/undefined/未知值透传（不渲染徽章的依据）
 */
import { describe, expect, it } from 'vitest';
import { STAGE_META, stageMeta } from './_trending-utils';

describe('trending stage badge mapping', () => {
  it('maps all four stages to the agreed label and tone', () => {
    expect(STAGE_META.evergreen).toEqual({ label: '常青', tone: 'teal' });
    expect(STAGE_META.peaking).toEqual({ label: '爆发', tone: 'primary' });
    expect(STAGE_META.declining).toEqual({ label: '回落', tone: 'amber' });
    expect(STAGE_META.ferment).toEqual({ label: '发酵', tone: 'neutral' });
  });

  it('passes null/undefined stages through as undefined (badge not rendered)', () => {
    expect(stageMeta(null)).toBeUndefined();
    expect(stageMeta(undefined)).toBeUndefined();
    expect(stageMeta('')).toBeUndefined();
  });

  it('passes unknown stage values through as undefined instead of throwing', () => {
    expect(stageMeta('unknown-stage')).toBeUndefined();
  });

  it('returns the mapping entry for known stages', () => {
    expect(stageMeta('evergreen')).toBe(STAGE_META.evergreen);
    expect(stageMeta('ferment')).toBe(STAGE_META.ferment);
  });
});
