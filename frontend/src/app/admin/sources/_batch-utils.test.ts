import { describe, it, expect } from 'vitest';
import {
  recomputeSelectionAfterBatch,
  describeBatchResult,
  runBatchToggle,
} from './_batch-utils';

/**
 * 独立复核 M4/M4b：删掉 `.tsx` 里的 `failedIds.push(id)` 或整段横幅渲染后，
 * 179 条测试全绿存活——因为「失败不可见」的执行层原本写在组件里。
 * 以下断言直接锁住执行与收集本身。
 */
describe('runBatchToggle — 缺陷 #1 的真修复（#88）', () => {
  const makeUpdate = (failIds: number[]) => {
    const calls: number[] = [];
    const update = async (id: number) => {
      calls.push(id);
      if (failIds.includes(id)) throw new Error(`boom ${id}`);
    };
    return { update, calls };
  };

  it('全部成功时返回空失败列表', async () => {
    const { update, calls } = makeUpdate([]);
    expect(await runBatchToggle([1, 2, 3], update)).toEqual([]);
    expect(calls).toEqual([1, 2, 3]);
  });

  it('收集每一条失败的 id，顺序与入参一致（#88 核心修复）', async () => {
    const { update } = makeUpdate([2, 5]);
    expect(await runBatchToggle([1, 2, 3, 4, 5], update)).toEqual([2, 5]);
  });

  it('单条失败不得中断整批——后续条目仍会被执行', async () => {
    const { update, calls } = makeUpdate([1]);
    const failed = await runBatchToggle([1, 2, 3], update);
    expect(calls).toEqual([1, 2, 3]);
    expect(failed).toEqual([1]);
  });

  it('每条失败都触发 onError 回调（console 留痕等副作用）', async () => {
    const { update } = makeUpdate([1, 3]);
    const seen: number[] = [];
    await runBatchToggle([1, 2, 3], update, (id) => seen.push(id));
    expect(seen).toEqual([1, 3]);
  });

  it('成功条目不触发 onError', async () => {
    const { update } = makeUpdate([2]);
    const seen: number[] = [];
    await runBatchToggle([1, 2, 3], update, (id) => seen.push(id));
    expect(seen).toEqual([2]);
  });

  it('onError 自身抛错不得影响失败收集结果', async () => {
    const { update } = makeUpdate([1, 2]);
    const failed = await runBatchToggle([1, 2, 3], update, () => {
      throw new Error('callback exploded');
    });
    expect(failed).toEqual([1, 2]);
  });

  it('空批次不调用 update', async () => {
    const { update, calls } = makeUpdate([]);
    expect(await runBatchToggle([], update)).toEqual([]);
    expect(calls).toEqual([]);
  });

  it('重复 id 的失败会被如实计入两次（不去重，避免谎报成功数）', async () => {
    const { update } = makeUpdate([1]);
    expect(await runBatchToggle([1, 1], update)).toEqual([1, 1]);
  });
});

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

  it('中途取消勾选失败项后，它仍会被重新勾上——这是有意的重试入口，不是 bug', () => {
    // 独立复核指出：批量期间复选框未锁定，用户中途取消勾选一个注定失败的项，
    // 执行结束后它会被无条件加回。批量按钮虽 disabled={batchProcessing}，
    // 行复选框没有，所以这个状态确实可达。
    // 契约选择：失败项一律重新入选，保证「失败即可重试」不因用户误操作丢失。
    const prev = new Set([1, 3]); // 2 已被用户取消勾选
    const next = recomputeSelectionAfterBatch(prev, [1, 2, 3], [2]);
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
