/**
 * 信源批量启停：选择态重算与结果反馈（#88）。
 *
 * 抽成纯函数而不是就地写进 `.tsx` 的原因：本项目 vitest 为
 * `environment: 'node'` + `include` 限定 `src` 下的 `.test.ts`，
 * `.tsx` 组件行为完全不在覆盖内（CI 五 job 也无 eslint）。而批量选择态的
 * 重算恰恰是 #88 修复中最微妙的一段逻辑——必须能回归，否则「中途新勾选项
 * 被静默丢弃」这类错误下次还会回来，且没有任何机器能发现。
 */

/** 批量操作的可见结果。tone 决定横幅配色。 */
export interface BatchResult {
  tone: 'teal' | 'red';
  text: string;
}

/**
 * 批量执行完成后重算选择态。
 *
 * 规则（缺一不可）：
 * 1. 本批失败项**保持选中**，便于操作者直接重试，不必回列表里重新勾选。
 * 2. 本批成功项**清除选中**。
 * 3. 执行期间（批量是逐条 await，期间 UI 未锁定复选框）用户新勾选的项，
 *    若不在本批快照内，必须**保留**——它们从未参与本批操作，无权被这次
 *    重算静默丢弃。
 *
 * @param prevSelection 批量结束瞬间的当前选择态
 * @param batchIds     本批操作的 id 快照（循环开始时捕获）
 * @param failedIds    本批中更新失败的 id
 */
export function recomputeSelectionAfterBatch(
  prevSelection: ReadonlySet<number>,
  batchIds: readonly number[],
  failedIds: readonly number[],
): Set<number> {
  const batch = new Set(batchIds);
  const failed = new Set(failedIds);
  const next = new Set<number>();

  for (const id of failed) {
    next.add(id);
  }
  for (const id of prevSelection) {
    if (!batch.has(id)) next.add(id);
  }
  return next;
}

/**
 * 逐条执行批量启停并收集失败项——**#88 缺陷 #1 的真修复就在这里**。
 *
 * 此前「catch 里记 failedIds」这段写在 `.tsx` 的 for 循环里，`.tsx` 在本仓库
 * 结构性不可测（无 jsdom/testing-library），独立复核的变异测试 M4 删掉
 * `failedIds.push(id)` 后 179 条测试全绿存活。把执行与收集也变成纯函数，
 * 「失败不可见」这个缺陷才真正被钉住。
 *
 * 关键语义：**单条失败不得中断整批**——修复前的循环正是这么吞掉的，
 * UI 报告「全部处理完」而实际有 N 条未改。
 *
 * @param ids      本批 id 快照（循环开始时捕获，不受执行期间用户操作影响）
 * @param update   单条更新操作，抛错即视为该条失败
 * @param onError  失败回调（用于 console 留痕等副作用），不影响返回值
 * @returns 失败 id 列表，顺序与 `ids` 一致
 */
export async function runBatchToggle(
  ids: readonly number[],
  update: (id: number) => Promise<unknown>,
  onError?: (id: number, err: unknown) => void,
): Promise<number[]> {
  const failedIds: number[] = [];
  for (const id of ids) {
    try {
      await update(id);
    } catch (err) {
      // onError 是留痕用的旁路，自身抛错绝不能中断整批——否则一个日志回调
      // 就能让「收集失败」退化成「整批中止」，反而比原缺陷更糟。
      try {
        onError?.(id, err);
      } catch {
        // 留痕失败不重抛：调用方需要的是失败 id 列表，不是异常
      }
      failedIds.push(id);
    }
  }
  return failedIds;
}

/**
 * 生成批量操作的结果反馈文案。
 *
 * 全部成功给 teal；只要有一条失败就给 red 并逐条列出失败 id——失败不可见
 * 是 #88 的原始缺陷：旧实现只 `console.error`，UI 报告「全部处理完」，
 * 实际失败的信源仍按原状态继续采集并污染内容池。
 */
export function describeBatchResult(
  total: number,
  failedIds: readonly number[],
  enabled: boolean,
): BatchResult {
  const verb = enabled ? '启用' : '停用';
  const failedCount = failedIds.length;

  if (failedCount === 0) {
    return { tone: 'teal', text: `已${verb} ${total} 个信源。` };
  }

  const succeededCount = total - failedCount;
  return {
    tone: 'red',
    text:
      `已${verb} ${succeededCount} 个信源，${failedCount} 个失败并保持选中：` +
      `${failedIds.join('、')}。请检查网络或该信源状态后重试。`,
  };
}
