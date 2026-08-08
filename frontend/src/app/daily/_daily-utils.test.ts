import { describe, it, expect } from 'vitest';
import {
  localDateString,
  formatDateTime,
  formatTimeOnly,
  parseJson,
  pickKey,
  isEnglishTitle,
  displaySourceTitle,
  marksMapFromResp,
  groupByCategory,
  EDITION_LABELS,
  CATEGORY_ORDER,
  type DailyPick,
} from './_daily-utils';

// 依赖 vitest.config.ts 里 process.env.TZ='UTC'

describe('localDateString', () => {
  it('输出 YYYY-MM-DD 格式', () => {
    const d = new Date(Date.UTC(2026, 5, 15)); // 2026-06-15
    expect(localDateString(d)).toBe('2026-06-15');
  });

  it('默认使用当前日期', () => {
    const result = localDateString();
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('formatDateTime', () => {
  it('空值返回空字符串', () => {
    expect(formatDateTime(null)).toBe('');
    expect(formatDateTime(undefined)).toBe('');
  });

  it('合法 ISO 日期格式化', () => {
    const result = formatDateTime('2026-06-15T10:30:00Z');
    expect(result).toMatch(/06\/15.*10:30/);
  });

  it('非法日期字符串回退原始值', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
  });
});

describe('formatTimeOnly', () => {
  it('空值返回空字符串', () => {
    expect(formatTimeOnly(null)).toBe('');
    expect(formatTimeOnly(undefined)).toBe('');
  });

  it('合法 ISO 日期返回 HH:MM', () => {
    const result = formatTimeOnly('2026-06-15T10:30:00Z');
    expect(result).toMatch(/^\d{2}:\d{2}$/);
  });
});

describe('parseJson', () => {
  it('合法 JSON 字符串解析', () => {
    expect(parseJson('{"a":1}')).toEqual({ a: 1 });
    expect(parseJson('[1,2,3]')).toEqual([1, 2, 3]);
  });

  it('非法 JSON 返回 null', () => {
    expect(parseJson('not json')).toBeNull();
  });

  it('非字符串值直接返回', () => {
    const obj = { a: 1 };
    expect(parseJson(obj)).toBe(obj);
    expect(parseJson(42)).toBe(42);
    expect(parseJson(null)).toBeNull();
  });
});

describe('pickKey', () => {
  it('优先使用 source_title', () => {
    expect(pickKey({ source_title: '原题', title: '观点标题' })).toBe('原题');
  });

  it('无 source_title 时回退 title', () => {
    expect(pickKey({ title: '观点标题' })).toBe('观点标题');
  });

  it('两者都无时返回空字符串', () => {
    expect(pickKey({})).toBe('');
  });
});

describe('isEnglishTitle', () => {
  it('纯英文标题返回 true', () => {
    expect(isEnglishTitle('GPT-4o Released')).toBe(true);
  });

  it('中文标题返回 false', () => {
    expect(isEnglishTitle('GPT-4o 正式发布')).toBe(false);
  });

  it('空值返回 false', () => {
    expect(isEnglishTitle(undefined)).toBe(false);
    expect(isEnglishTitle('')).toBe(false);
  });

  it('CJK 字符占比高时返回 false', () => {
    expect(isEnglishTitle('这是一些中文内容 with some English')).toBe(false);
  });
});

describe('displaySourceTitle', () => {
  it('showOriginal=true 返回英文原文', () => {
    expect(displaySourceTitle({ source_title: 'Original', source_title_zh: '原文' }, true)).toBe('Original');
  });

  it('showOriginal=false 优先返回中文翻译', () => {
    expect(displaySourceTitle({ source_title: 'Original', source_title_zh: '原文' }, false)).toBe('原文');
  });

  it('无中文翻译时回退英文原文', () => {
    expect(displaySourceTitle({ source_title: 'Original' }, false)).toBe('Original');
  });

  it('无 source_title 时返回空字符串', () => {
    expect(displaySourceTitle({}, false)).toBe('');
  });
});

describe('marksMapFromResp', () => {
  it('把 marks 数组转为 pick_title -> action 映射', () => {
    const marks = [
      { pick_title: '选题A', action: 'write' },
      { pick_title: '选题B', action: 'watch' },
    ];
    expect(marksMapFromResp(marks)).toEqual({
      '选题A': 'write',
      '选题B': 'watch',
    });
  });

  it('空数组返回空对象', () => {
    expect(marksMapFromResp([])).toEqual({});
  });
});

describe('groupByCategory', () => {
  const picks: DailyPick[] = [
    { title: 'A', reason: '', category: '模型发布', tier: 'feature' },
    { title: 'B', reason: '', category: '产品更新', tier: 'feature' },
    { title: 'C', reason: '', category: '模型发布', tier: 'brief' },
    { title: 'D', reason: '', tier: 'feature' }, // 无 category → 归入"精选选题"
  ];

  it('feature 分组：排除 brief tier', () => {
    const groups = groupByCategory(picks, 'feature');
    const allPicks = groups.flatMap(([, ps]) => ps);
    expect(allPicks).toHaveLength(3); // A, B, D
    expect(allPicks.find((p) => p.title === 'C')).toBeUndefined();
  });

  it('brief 分组：只含 brief tier', () => {
    const groups = groupByCategory(picks, 'brief');
    const allPicks = groups.flatMap(([, ps]) => ps);
    expect(allPicks).toHaveLength(1);
    expect(allPicks[0].title).toBe('C');
  });

  it('无 category 的选题归入"精选选题"', () => {
    const groups = groupByCategory(picks, 'feature');
    const defaultGroup = groups.find(([cat]) => cat === '精选选题');
    expect(defaultGroup).toBeDefined();
    expect(defaultGroup![1]).toHaveLength(1);
    expect(defaultGroup![1][0].title).toBe('D');
  });

  it('按 CATEGORY_ORDER 排序', () => {
    const groups = groupByCategory(picks, 'feature');
    const cats = groups.map(([cat]) => cat);
    // "模型发布" 在 CATEGORY_ORDER 中排第 0，"精选选题" 不在列表中排最后
    const modelIdx = cats.indexOf('模型发布');
    const defaultIdx = cats.indexOf('精选选题');
    expect(modelIdx).toBeLessThan(defaultIdx);
  });

  it('无 tier 字段视为 feature', () => {
    const noTierPicks: DailyPick[] = [
      { title: 'X', reason: '', category: '行业动态' },
    ];
    const featureGroups = groupByCategory(noTierPicks, 'feature');
    expect(featureGroups).toHaveLength(1);
    const briefGroups = groupByCategory(noTierPicks, 'brief');
    expect(briefGroups).toHaveLength(0);
  });
});

describe('EDITION_LABELS', () => {
  it('包含所有预期版本', () => {
    expect(EDITION_LABELS.noon).toBe('午间快照');
    expect(EDITION_LABELS.evening).toBe('晚间快照');
    expect(EDITION_LABELS.final).toBe('完整复盘');
  });
});

describe('CATEGORY_ORDER', () => {
  it('包含 6 个预期分类', () => {
    expect(CATEGORY_ORDER).toHaveLength(6);
    expect(CATEGORY_ORDER).toContain('模型发布');
    expect(CATEGORY_ORDER).toContain('开源项目');
  });
});
