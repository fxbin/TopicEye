import { describe, expect, it } from 'vitest';
import { annotateExtracted, mergeSelectedKeywords, parseKeywordText } from './_keyword-extract';

describe('parseKeywordText', () => {
  it('切分规则与页面现有保存逻辑一致（英文逗号 + trim + 丢空串）', () => {
    expect(parseKeywordText('AI工具, ChatGPT , 效率')).toEqual(['AI工具', 'ChatGPT', '效率']);
    expect(parseKeywordText('  ')).toEqual([]);
    expect(parseKeywordText('单关键词')).toEqual(['单关键词']);
    expect(parseKeywordText('a,,b,')).toEqual(['a', 'b']);
  });

  it('中文逗号不切分，保持与现有保存口径一致', () => {
    expect(parseKeywordText('AI工具，效率')).toEqual(['AI工具，效率']);
  });
});

describe('annotateExtracted', () => {
  it('标记已在关键词框里的词（不分大小写）', () => {
    const annotated = annotateExtracted(['AI工具', 'ai工具', '新能源车'], 'ai工具, 充电桩');
    expect(annotated).toEqual([
      { keyword: 'AI工具', alreadyPresent: true },
      { keyword: 'ai工具', alreadyPresent: true },
      { keyword: '新能源车', alreadyPresent: false },
    ]);
  });

  it('关键词框为空时全部是新词', () => {
    const annotated = annotateExtracted(['A', 'B'], '');
    expect(annotated.every(item => !item.alreadyPresent)).toBe(true);
  });
});

describe('mergeSelectedKeywords', () => {
  it('一个都没勾时原样返回同一个字符串', () => {
    const current = 'AI工具, 充电桩';
    expect(mergeSelectedKeywords(current, [])).toBe(current);
  });

  it('新词追加在后，保留原有顺序，用逗号空格拼接', () => {
    expect(mergeSelectedKeywords('AI工具, 充电桩', ['新能源车', '比亚迪'])).toBe(
      'AI工具, 充电桩, 新能源车, 比亚迪',
    );
  });

  it('已有的词不会重复加入（不分大小写）', () => {
    expect(mergeSelectedKeywords('AI工具, 充电桩', ['ai工具', '新能源车'])).toBe(
      'AI工具, 充电桩, 新能源车',
    );
  });

  it('勾选的全是已有词时返回值不变', () => {
    const current = 'AI工具, 充电桩';
    expect(mergeSelectedKeywords(current, ['充电桩', 'AI工具'])).toBe(current);
  });

  it('关键词框为空时直接拼接新词', () => {
    expect(mergeSelectedKeywords('', ['新能源车', '比亚迪'])).toBe('新能源车, 比亚迪');
  });

  it('勾选里的空白词被忽略，全空白时返回值不变', () => {
    const current = 'AI工具';
    expect(mergeSelectedKeywords(current, ['', '   ', ''])).toBe(current);
    expect(mergeSelectedKeywords(current, ['', '新能源车'])).toBe('AI工具, 新能源车');
  });
});
