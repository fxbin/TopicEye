/**
 * Webhook 日志页的口径摘要（#88）。
 *
 * 本模块存在的唯一理由是守住一条不变量：**页内计数与全局 total 必须分开表述**。
 *
 * 旧实现里 `successCount` / `failCount` 只统计当前页 PAGE_SIZE 行，却与全局
 * `total` 并排渲染成同款 Badge，读者会把「本页 2 失败」除以「共 1240 条」
 * 读成 0.16% 失败率——而真相是第 5 页可能还躺着 40 条。Webhook 是产品交付
 * 通道，这个读数错了等于对交付健康度撒谎。
 *
 * 另一个不变量：失败数为 0 时**显式渲染 0**，而不是让徽章整枚消失。
 * 徽章的缺席本身就在制造错误信念。
 */

/** 判定成功/失败所需的最小日志形状。 */
export interface LogOutcome {
  success: boolean;
}

export interface LogPageSummary {
  /** 当前页首条在全局中的序号（1-based）；空页为 0。 */
  pageStart: number;
  /** 当前页末条在全局中的序号（1-based）；空页为 0。 */
  pageEnd: number;
  /** 当前页成功数。 */
  successCount: number;
  /** 当前页失败数。 */
  failCount: number;
  hasPrev: boolean;
  hasNext: boolean;
  currentPage: number;
  totalPages: number;
}

/**
 * 计算当前分页的口径摘要。
 *
 * 全部计数只对**当前页**求和，total 只参与分页边界计算，两条口径不相加。
 */
export function summarizeLogPage(
  logs: readonly LogOutcome[],
  total: number,
  offset: number,
  pageSize: number,
): LogPageSummary {
  let successCount = 0;
  for (const log of logs) {
    if (log.success) successCount += 1;
  }

  return {
    pageStart: logs.length === 0 ? 0 : offset + 1,
    pageEnd: logs.length === 0 ? 0 : offset + logs.length,
    successCount,
    failCount: logs.length - successCount,
    hasPrev: offset > 0,
    hasNext: offset + pageSize < total,
    currentPage: Math.floor(offset / pageSize) + 1,
    totalPages: Math.ceil(total / pageSize) || 1,
  };
}

/** 顶部徽章的呈现描述。tone 为 null 表示该徽章不渲染。 */
export interface SummaryBadge {
  key: string;
  label: string;
  tone: 'neutral' | 'teal' | 'red';
  icon: 'check' | 'x' | 'none';
}

/**
 * 构建顶部徽章组——**#88 缺陷 #2 的真修复就在这里**。
 *
 * 此前该修复写在 JSX 里，`.tsx` 在本仓库结构性不可测（无 jsdom/testing-library），
 * 独立复核的变异测试 M3 把整段 JSX 还原成修复前形态后 179 条测试全绿存活。
 * 把「渲染成什么」也变成纯函数，修复才真正被钉住。
 *
 * 三条硬规则（每条都对应一个曾经的错误信念）：
 * 1. 全局计数与页内计数**视觉分层**且都带口径词（「全部」/「本页」），不得并排同款。
 * 2. 成功/失败徽章**无条件渲染**——0 失败显式写 0，徽章的缺席本身就是错误信念。
 * 3. 空页不产出「本页 0-0」这种假区间，只留全局计数。
 */
export function buildSummaryBadges(
  summary: LogPageSummary,
  total: number,
): SummaryBadge[] {
  const badges: SummaryBadge[] = [
    { key: 'total', label: `全部 ${total} 条`, tone: 'neutral', icon: 'none' },
  ];

  if (summary.pageEnd === 0) return badges;

  badges.push({
    key: 'page-range',
    label: `本页 ${summary.pageStart}-${summary.pageEnd}`,
    tone: 'neutral',
    icon: 'none',
  });
  badges.push({
    key: 'page-success',
    label: `本页成功 ${summary.successCount}`,
    tone: 'teal',
    icon: 'check',
  });
  badges.push({
    key: 'page-fail',
    label: `本页失败 ${summary.failCount}`,
    tone: summary.failCount > 0 ? 'red' : 'neutral',
    icon: 'x',
  });
  return badges;
}
