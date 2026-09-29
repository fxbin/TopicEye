import { describe, it, expect } from 'vitest';
import { summarizeLogPage, buildSummaryBadges } from './_scope-utils';

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
    // 失败率不能被读成 2/1240：页内计数与全局 total 是两条不相加的口径。
    // 用「换 total 不改变页内计数」来证明，而非断言一个不可能产出的常量。
    const samePage = summarizeLogPage(makeLogs(30, 2), 99999, 0, PAGE_SIZE);
    expect(samePage.successCount).toBe(s.successCount);
    expect(samePage.failCount).toBe(s.failCount);
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

  it('每一条日志恰被计入成功或失败之一（逐条核对，不依赖构造性恒等式）', () => {
    for (const failures of [0, 1, 15, 30]) {
      const logs = makeLogs(30, failures);
      const s = summarizeLogPage(logs, 999, 0, PAGE_SIZE);
      const counted = logs.filter((l) => l.success).length;
      expect(s.successCount).toBe(counted);
      expect(s.failCount).toBe(logs.filter((l) => !l.success).length);
    }
  });

  it('失败为 0 时 failCount 显式为 0——供 UI 无条件渲染而非缺席', () => {
    const s = summarizeLogPage(makeLogs(30, 0), 1240, 0, PAGE_SIZE);
    expect(s.failCount).toBe(0);
  });
});

/**
 * 独立复核 M3：把修复前的 JSX 整段还原后，summarizeLogPage 的断言全部存活
 * ——因为缺陷 #2 的真修复（口径标注 + 徽章无条件渲染）原本写在 JSX 里。
 * 以下断言直接锁住「渲染成什么」，M3 变异会转红。
 */
describe('buildSummaryBadges — 缺陷 #2 的真修复（#88）', () => {
  const badgesFor = (logs: ReturnType<typeof makeLogs>, total: number, offset = 0) =>
    buildSummaryBadges(summarizeLogPage(logs, total, offset, PAGE_SIZE), total);

  it('全局计数与页内计数都带口径词，读者无法再把两者混算', () => {
    const labels = badgesFor(makeLogs(30, 2), 1240).map((b) => b.label);
    expect(labels[0]).toBe('全部 1240 条');
    expect(labels.some((l) => l.startsWith('本页成功'))).toBe(true);
    expect(labels.some((l) => l.startsWith('本页失败'))).toBe(true);
    // 不得出现不带口径词的裸「成功 N」/「失败 N」
    expect(labels).not.toContain('成功 28');
    expect(labels).not.toContain('失败 2');
  });

  it('失败徽章无条件渲染：0 失败时显式存在且为中性色（#88 核心修复）', () => {
    const badges = badgesFor(makeLogs(30, 0), 1240);
    const fail = badges.find((b) => b.key === 'page-fail');
    expect(fail).toBeDefined();
    expect(fail?.label).toBe('本页失败 0');
    expect(fail?.tone).toBe('neutral');
  });

  it('有失败时失败徽章转为红色警示', () => {
    const fail = badgesFor(makeLogs(30, 2), 1240).find((b) => b.key === 'page-fail');
    expect(fail?.tone).toBe('red');
    expect(fail?.label).toBe('本页失败 2');
  });

  it('成功徽章恒为 teal，不随失败数变色', () => {
    const withFail = badgesFor(makeLogs(30, 5), 1240).find((b) => b.key === 'page-success');
    const without = badgesFor(makeLogs(30, 0), 1240).find((b) => b.key === 'page-success');
    expect(withFail?.tone).toBe('teal');
    expect(without?.tone).toBe('teal');
  });

  it('空页只留全局计数，不产出「本页 0-0」假区间', () => {
    const badges = badgesFor([], 1240, 30);
    expect(badges).toHaveLength(1);
    expect(badges[0].label).toBe('全部 1240 条');
  });

  it('非空页恒为 4 枚徽章，key 唯一', () => {
    const badges = badgesFor(makeLogs(30, 1), 1240);
    expect(badges).toHaveLength(4);
    expect(new Set(badges.map((b) => b.key)).size).toBe(4);
  });

  it('中段分页的页码范围出现在徽章文案里', () => {
    const range = badgesFor(makeLogs(30, 0), 1240, 900).find((b) => b.key === 'page-range');
    expect(range?.label).toBe('本页 901-930');
  });
});
