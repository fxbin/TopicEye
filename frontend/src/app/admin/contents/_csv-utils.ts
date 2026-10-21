/**
 * 内容列表 CSV 导出（#124 回归：从 page.tsx 抽出成可测纯函数）。
 *
 * 缺陷回顾：原实现把 BOM 与换行写成了**双反斜杠字面量**
 * （`'\\uFEFF'` / `'\\n'`），产出的是两字符的 `\uFEFF` 与 `\n` 字面量，
 * 不是 BOM 字符与换行符——Excel 打开是一整行。BOM 用单反斜杠
 * （`'\uFEFF'`）与真换行（`'\n'`）。
 *
 * 本文件只负责「行 → CSV 文本」，下载动作留在页面层（依赖 DOM）。
 */

/** CSV 字段转义：含逗号/引号/换行时用双引号包裹，内部引号成对。 */
export function escapeCsvField(value: unknown): string {
  if (value === null || value === undefined) return '';
  const s = String(value);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * 生成带 BOM 的 CSV 文本。
 *
 * - 行分隔用真换行 `\n`
 * - 开头加 UTF-8 BOM（\uFEFF），让 Excel 正确识别中文
 */
export function buildContentsCsv(
  headers: readonly string[],
  rows: readonly (readonly unknown[])[],
): string {
  const body = [headers, ...rows].map((row) => row.map(escapeCsvField).join(',')).join('\n');
  return `\uFEFF${body}`;
}
