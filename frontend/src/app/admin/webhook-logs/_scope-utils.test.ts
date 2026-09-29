import { describe, it, expect } from 'vitest';
import { summarizeLogPage } from './_scope-utils';

/**
 * #88 回归：Webhook 日志页的读数口径。
 *
 * 旧实现（修复前）：页内 30 行的 successCount/failCount 与全局 total 并排
 * 渲染成同款 Badge，诱导 0.16% 失败率的误读；且失败徽章以 failCount > 0
 * 为条件渲染，0 失败时整枚徽章消失——徽章缺席本身即错误信念。
 */

const PAGE_SIZE = 30;

/** 造 n 条日志，其中 failures 条为失败。 */
const makeLogs = (n: number, failures: number) =>
  Array.from({ length: n }, (_, i) => ({ success: i >= failures }));

describe('summarizeLogPage', () => {
  it('只对当前页求和，绝不把全局 total 混进页内计数（#88 核心不变量）', () => {
    // 全局 1240 条，当前页 30 条里 2 条失败
    const s = summarizeLogPage(makeLogs(30, 2), 1240, 0, PAGE_SIZE);
    expect(s.successCount).toBe(28);
    expect(s.failCount).toBe(2);
    // 失败率不能被读成 2/1240：页内计数与全局 total 是两条不相加的口径
    expect(s.successCount).not.toBe(1238);
  });

  it('中段分页的页码范围正确', () => {
    const s = summarizeLogPage(makeLogs(30, 0), 1240, 900, PAGE_SIZE);
    expect(s.pageStart).toBe(901);
    expect(s.pageEnd).toBe(930);
    expect(s.currentPage).toBe(31);
  });

  it('末页不足一页时，页尾不超出实际条数', () => {
    const s = summarizeLogPage(makeLogs(10, 0), 1240, 1230, PAGE_SIZE);
    expect(s.pageStart).toBe(1231);
    expect(s.pageEnd).toBe(1240);
    expect(s.hasNext).toBe(false);
  });

  it('空页的范围为 0-0，不产出假区间', () => {
    const s = summarizeLogPage([], 1240, 30, PAGE_SIZE);
    expect(s.pageStart).toBe(0);
    expect(s.pageEnd).toBe(0);
    expect(s.successCount).toBe(0);
    expect(s.failCount).toBe(0);
  });

  it('空数据集时 totalPages 为 1 而非 0（避免除零渲染）', () => {
    const s = summarizeLogPage([], 0, 0, PAGE_SIZE);
    expect(s.totalPages).toBe(1);
    expect(s.currentPage).toBe(1);
  });

  it('首页无上一页、末页无下一页', () => {
    const first = summarizeLogPage(makeLogs(30, 0), 1240, 0, PAGE_SIZE);
    expect(first.hasPrev).toBe(false);
    expect(first.hasNext).toBe(true);

    const last = summarizeLogPage(makeLogs(10, 0), 1240, 1230, PAGE_SIZE);
    expect(last.hasPrev).toBe(true);
    expect(last.hasNext).toBe(false);
  });

  it('failCount = 页内条数 - successCount（二者恒等，不会各算各的）', () => {
    for (const failures of [0, 1, 15, 30]) {
      const s = summarizeLogPage(makeLogs(30, failures), 999, 0, PAGE_SIZE);
      expect(s.successCount + s.failCount).toBe(30);
    }
  });

  it('失败为 0 时 failCount 显式为 0——供 UI 无条件渲染而非缺席', () => {
    const s = summarizeLogPage(makeLogs(30, 0), 1240, 0, PAGE_SIZE);
    expect(s.failCount).toBe(0);
  });
});
