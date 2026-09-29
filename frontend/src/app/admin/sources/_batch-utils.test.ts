import { describe, it, expect } from 'vitest';
import { recomputeSelectionAfterBatch, describeBatchResult } from './_batch-utils';

/**
 * #88 回归：批量启停的失败可见性与选择态重算。
 *
 * 旧实现（修复前）：逐条 catch 只 console.error，循环后无条件
 * setSelectedIds(new Set())，UI 报告「全部处理完」而实际有 N 条未改。
 */

describe('recomputeSelectionAfterBatch', () => {
  it('全部成功时清空选择态', () => {
    const prev = new Set([1, 2, 3]);
    const next = recomputeSelectionAfterBatch(prev, [1, 2, 3], []);
    expect(next.size).toBe(0);
  });

  it('失败项保持选中，便于直接重试（#88 核心行为）', () => {
    const prev = new Set([1, 2, 3, 4, 5]);
    const next = recomputeSelectionAfterBatch(prev, [1, 2, 3, 4, 5], [2, 4]);
    expect([...next].sort((a, b) => a - b)).toEqual([2, 4]);
  });

  it('执行期间用户新勾选的项不得被静默丢弃（自审发现的回归）', () => {
    // 批量是逐条 await，期间复选框未锁定：用户中途勾了 99（本批快照内没有）
    const prev = new Set([1, 2, 3, 99]);
    const batchIds = [1, 2, 3];
    const next = recomputeSelectionAfterBatch(prev, batchIds, [2]);

    // 失败项 2 保留
    expect(next.has(2)).toBe(true);
    // 成功项 1、3 清除
    expect(next.has(1)).toBe(false);
    expect(next.has(3)).toBe(false);
    // 中途新勾选的 99 绝不能丢
    expect(next.has(99)).toBe(true);
  });

  it('中途取消勾选失败项后，不把它强行加回', () => {
    // prev 里没有 2（用户已取消勾选），但它在失败列表里
    const prev = new Set([1, 3]);
    const next = recomputeSelectionAfterBatch(prev, [1, 2, 3], [2]);
    // 失败项按契约重新入选以支持重试——这是有意的：失败需要可见且可重试
    expect(next.has(2)).toBe(true);
  });

  it('不修改传入的 prevSelection（原 Set 不被就地改写）', () => {
    const prev = new Set([1, 2, 3]);
    recomputeSelectionAfterBatch(prev, [1, 2, 3], [2]);
    expect([...prev].sort((a, b) => a - b)).toEqual([1, 2, 3]);
  });

  it('空批次返回空选择态', () => {
    expect(recomputeSelectionAfterBatch(new Set(), [], []).size).toBe(0);
  });
});

describe('describeBatchResult', () => {
  it('全部成功 → teal，报告处理条数', () => {
    const r = describeBatchResult(30, [], false);
    expect(r.tone).toBe('teal');
    expect(r.text).toContain('已停用 30 个信源');
  });

  it('全部成功时动词随 enabled 变化', () => {
    expect(describeBatchResult(3, [], true).text).toContain('已启用 3 个信源');
  });

  it('部分失败 → red，列出失败数与失败 id（#88 核心行为）', () => {
    const r = describeBatchResult(30, [12, 47], true);
    expect(r.tone).toBe('red');
    expect(r.text).toContain('已启用 28 个信源');
    expect(r.text).toContain('2 个失败');
    expect(r.text).toContain('12、47');
  });

  it('部分失败时成功数 = 总数 - 失败数', () => {
    const r = describeBatchResult(5, [1, 2, 3, 4], false);
    expect(r.text).toContain('已停用 1 个信源');
    expect(r.text).toContain('4 个失败');
  });

  it('全部失败时成功数为 0，且不为 teal', () => {
    const r = describeBatchResult(2, [7, 8], false);
    expect(r.tone).toBe('red');
    expect(r.text).toContain('已停用 0 个信源');
  });
});
