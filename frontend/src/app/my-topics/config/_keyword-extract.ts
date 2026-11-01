/**
 * 关键词 AI 提取辅助的纯逻辑（issue #187）。
 *
 * 关键词框在表单里是一个逗号拼接的字符串，保存时按英文逗号切分
 * （见 page.tsx 的 NewTopicForm / TopicCard）。这里的切分、合并规则
 * 与那条既有路径保持一致，不引入第二套口径。
 */

/** 与页面现有保存逻辑一致：按英文逗号切分、去首尾空白、丢空串。 */
export function parseKeywordText(text: string): string[] {
  return text.split(',').map(k => k.trim()).filter(Boolean);
}

/** 提取结果条目：alreadyPresent = 该词已在关键词框里（不分大小写）。 */
export interface AnnotatedKeyword {
  keyword: string;
  alreadyPresent: boolean;
}

/** 给每个提取结果标出是否已在关键词框里。 */
export function annotateExtracted(extracted: string[], currentText: string): AnnotatedKeyword[] {
  const present = new Set(parseKeywordText(currentText).map(k => k.toLowerCase()));
  return extracted.map(keyword => ({
    keyword,
    alreadyPresent: present.has(keyword.trim().toLowerCase()),
  }));
}

/**
 * 把勾选的关键词合并进关键词框文本。
 * - 一个都没勾（或勾的全是已有词）时原样返回同一个字符串，不改动；
 * - 不分大小写去重：已有词不会重复加入；
 * - 保留原有顺序，新词追加在后，用 ', ' 拼接。
 */
export function mergeSelectedKeywords(currentText: string, selected: string[]): string {
  if (selected.length === 0) return currentText;

  const existing = parseKeywordText(currentText);
  const seen = new Set(existing.map(k => k.toLowerCase()));
  const additions: string[] = [];
  for (const keyword of selected) {
    const trimmed = keyword.trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    additions.push(trimmed);
  }
  if (additions.length === 0) return currentText;
  return [...existing, ...additions].join(', ');
}
