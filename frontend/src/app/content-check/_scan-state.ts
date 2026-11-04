/**
 * 文稿检测的结果时效判定（从 page.tsx 拆出的纯逻辑，便于测试）。
 *
 * 合同：检测结果只对「检测那一刻的文稿快照」有效（scannedText）。用户编辑后：
 * - 不得继续展示「未发现违禁词，可以发布」之类的把关结论（干净检测后追加极限词会结论反转）；
 * - 不得用旧偏移在新文本上高亮（范围内错位，_highlight.tsx 的越界/重叠防御挡不住）。
 * 页面渲染必须以 phase 为准：只有 current 才展示统计与高亮，stale 只提示重新检测。
 *
 * result 泛型化：敏感词与 AI 痕迹两类结果共用同一快照合同（同一批请求、同一
 * 份文稿），页面把两者合并成一个对象传入。
 */

export type ScanPhase<T> =
  | { kind: 'idle' }
  | { kind: 'current'; result: T }
  | { kind: 'stale'; result: T };

/** scannedText 是结果对应的文稿快照；与当前文本一致才算 current（撤销回原文同样有效）。 */
export function scanPhase<T>(scannedText: string | null, currentText: string, result: T | null): ScanPhase<T> {
  if (!result) return { kind: 'idle' };
  if (scannedText === null || scannedText !== currentText) return { kind: 'stale', result };
  return { kind: 'current', result };
}
