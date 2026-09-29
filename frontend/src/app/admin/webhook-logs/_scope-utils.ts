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
