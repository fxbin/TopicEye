import { describe, expect, it } from 'vitest';
import { scanPhase } from './_scan-state';
import type { AiTracesReport, SensitiveCheckResponse } from '@/types/content-check';

/**
 * 回归（评审阻断项）：检测结果只对检测时的文稿快照有效。
 * 编辑后必须判 stale——否则「未发现违禁词，可以发布」会贴着新加的极限词展示，
 * 旧偏移也会在新文本上错位高亮。页面渲染以 phase 为准，本测试锁住判定合同。
 * 合同对两类结果（敏感词 / AI 痕迹）一致：result 泛型化后各自都受同一快照约束。
 */

const clean: SensitiveCheckResponse = { total: 0, hits: [] };
const dirty: SensitiveCheckResponse = {
  total: 1,
  hits: [{ word: '最好', category: 'advertising_extreme', severity: 'high', start: 0, end: 2, suggestion: null }],
};

describe('scanPhase', () => {
  it('no result means idle regardless of text', () => {
    expect(scanPhase(null, '任意文稿', null)).toEqual({ kind: 'idle' });
    expect(scanPhase('旧文稿', '任意文稿', null)).toEqual({ kind: 'idle' });
  });

  it('result is current only while text equals the scanned snapshot', () => {
    expect(scanPhase('一篇干净文稿。', '一篇干净文稿。', clean)).toEqual({ kind: 'current', result: clean });
    expect(scanPhase('最好的选择', '最好的选择', dirty)).toEqual({ kind: 'current', result: dirty });
  });

  it('editing after scan invalidates the result (stale), even a clean verdict', () => {
    // 干净检测后追加极限词：结论必须过期，不得继续显示「可以发布」
    expect(scanPhase('干净文稿。', '干净文稿。全网最低价出售', clean)).toEqual({ kind: 'stale', result: clean });
    // 删改同样过期：旧偏移不得继续高亮
    expect(scanPhase('最好的选择', '最差的选择', dirty)).toEqual({ kind: 'stale', result: dirty });
  });

  it('undo back to the scanned snapshot restores current (content-equal is valid)', () => {
    expect(scanPhase('干净文稿。', '干净文稿。改了一笔', clean)).toEqual({ kind: 'stale', result: clean });
    expect(scanPhase('干净文稿。', '干净文稿。', clean)).toEqual({ kind: 'current', result: clean });
  });

  it('missing snapshot with a result is treated as stale (defensive)', () => {
    expect(scanPhase(null, '任意文稿', clean)).toEqual({ kind: 'stale', result: clean });
  });

  it('holds for the AI traces report payload under the same snapshot contract', () => {
    const aiReport: AiTracesReport = {
      level: 'high',
      character_count: 12,
      buzzword: { dimension: 'buzzword', hits: 2, density_per_kilochar: 166.67, level: 'high' },
      connective: { dimension: 'connective', hits: 1, density_per_kilochar: 83.33, level: 'high' },
      rhythm: { level: 'insufficient', sentence_count: 1, cv: null },
      hits: [{ word: '赋能', dimension: 'buzzword', start: 0, end: 2 }],
      advice: 'AI 高频词/套话连接词密集，建议逐条改写。启发式统计，仅供参考。',
    };
    expect(scanPhase('赋能闭环。', '赋能闭环。', aiReport)).toEqual({ kind: 'current', result: aiReport });
    expect(scanPhase('赋能闭环。改', '赋能闭环。', aiReport)).toEqual({ kind: 'stale', result: aiReport });
  });
});
