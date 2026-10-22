import { describe, it, expect } from 'vitest';
import { buildContentsCsv, escapeCsvField } from './_csv-utils';

/**
 * #124 回归：CSV 导出的 BOM 与换行此前写成双反斜杠字面量
 * （`'\\uFEFF'` / `'\\n'`），Excel 打开是一整行、BOM 失效。
 * 缺陷只有落成测试才算关闭（AGENTS.md：教训必须机器化）。
 */
describe('escapeCsvField', () => {
  it('null/undefined → 空串', () => {
    expect(escapeCsvField(null)).toBe('');
    expect(escapeCsvField(undefined)).toBe('');
  });

  it('普通值原样', () => {
    expect(escapeCsvField('选题雷达')).toBe('选题雷达');
    expect(escapeCsvField(42)).toBe('42');
  });

  it('含逗号/引号/换行 → 双引号包裹，内部引号成对', () => {
    expect(escapeCsvField('a,b')).toBe('"a,b"');
    expect(escapeCsvField('说"引号"')).toBe('"说""引号"""');
    expect(escapeCsvField('第一行\n第二行')).toBe('"第一行\n第二行"');
  });
});

describe('buildContentsCsv', () => {
  it('以 UTF-8 BOM 开头（Excel 识别中文的前提）', () => {
    const csv = buildContentsCsv(['标题'], [['选题雷达']]);
    expect(csv.charCodeAt(0)).toBe(0xfeff);
    expect(csv.startsWith('\uFEFF')).toBe(true);
  });

  it('行间是真换行，不是字面量 \\n', () => {
    const csv = buildContentsCsv(['ID', '标题'], [[1, '第一篇'], [2, '第二篇']]);
    expect(csv).not.toContain('\\n'); // 反斜杠+n 的字面量
    const lines = csv.replace(/^\uFEFF/, '').split('\n');
    expect(lines).toEqual(['ID,标题', '1,第一篇', '2,第二篇']);
  });

  it('换行数 = 行数 - 1', () => {
    const csv = buildContentsCsv(['A'], [['1'], ['2'], ['3']]);
    const body = csv.replace(/^\uFEFF/, '');
    expect(body.split('\n')).toHaveLength(4); // 表头 + 3 行
  });

  it('含逗号的字段被正确引号包裹且不破坏列数', () => {
    const csv = buildContentsCsv(['ID', '标题'], [[1, '标题, 含逗号']]);
    const row = csv.replace(/^\uFEFF/, '').split('\n')[1];
    expect(row).toBe('1,"标题, 含逗号"');
  });
});
