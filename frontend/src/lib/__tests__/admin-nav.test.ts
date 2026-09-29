import { describe, it, expect } from 'vitest';
import {
  ADMIN_NAV_ITEMS,
  ADMIN_PAGE_LABELS,
  ADMIN_IN_SHELL_PATHS,
  ADMIN_FALLBACK_LABEL,
  findAdminPageLabel,
} from '@/lib/admin-nav';

/**
 * #88 回归：管理后台导航清单与面包屑映射的一致性。
 *
 * 旧实现（修复前）：AdminSidebar 维护 15 项，AdminTopBar 另有一份 10 条的
 * ADMIN_PAGE_LABELS。prompts / scoring-dashboard / evidence / webhook-logs
 * 四页无映射。注意真实症状是顶栏显示「**概览**」而非「管理」——旧实现里
 * `/admin` 是前缀匹配键，`/admin/prompts` 先命中 `/admin/` 落成「概览」。
 *
 * 现在映射由清单派生，因此这些断言能防止同类漏项复发。
 */

describe('ADMIN_NAV_ITEMS 结构不变式', () => {
  it('id 唯一', () => {
    const ids = ADMIN_NAV_ITEMS.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('href 唯一', () => {
    const hrefs = ADMIN_NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('每一项都有非空 label', () => {
    for (const item of ADMIN_NAV_ITEMS) {
      expect(item.label.length).toBeGreaterThan(0);
    }
  });

  /**
   * 独立复核 M7：结构性不变量（唯一性/派生一致）锁不住**字面值**——
   * 把 `updates` 的 label+href 同时改掉，179 条测试无一报警。
   * 这里把 15 项逐字锁死：改导航必须是有意识的动作，并同步改这条期望。
   */
  it('15 项字面值逐项锁死（改导航必须同步改本表）', () => {
    const actual = ADMIN_NAV_ITEMS.map((i) => [i.id, i.label, i.href, i.inShell]);
    expect(actual).toEqual([
      ['dashboard', '概览', '/admin', true],
      ['monitor', '监控大盘', '/dashboard', false],
      ['sources', '信源管理', '/admin/sources', true],
      ['contents', '内容管理', '/admin/contents', true],
      ['content-events', '内容事件治理', '/admin/content-events', true],
      ['users', '用户管理', '/admin/users', true],
      ['model-eval', 'AI 引擎', '/admin/model-eval', true],
      ['mother-topics', '系统母题模板库', '/admin/mother-topics', true],
      ['updates', '发版记录', '/admin/updates', true],
      ['prompts', 'Prompt 管理', '/admin/prompts', true],
      ['scoring-dashboard', '评分看板', '/admin/scoring-dashboard', true],
      ['evidence', '可信线索', '/admin/evidence', true],
      ['feedback', '反馈工作台', '/admin/feedback', true],
      ['webhook-logs', 'Webhook 日志', '/admin/webhook-logs', true],
      ['settings', '系统设置', '/admin/settings', true],
    ]);
  });
});

describe('面包屑映射与清单一致（#88 核心不变量）', () => {
  it('壳内每一项都有面包屑映射——缺项即红', () => {
    const missing = ADMIN_IN_SHELL_PATHS.filter((href) => !ADMIN_PAGE_LABELS[href]);
    expect(missing).toEqual([]);
  });

  it('映射表不含任何壳外路径（监控大盘由 window.open 单独打开）', () => {
    expect(ADMIN_PAGE_LABELS['/dashboard']).toBeUndefined();
  });

  it('壳内 14 项、壳外 1 项（/dashboard 监控大盘）', () => {
    expect(ADMIN_IN_SHELL_PATHS).toHaveLength(14);
    expect(ADMIN_NAV_ITEMS).toHaveLength(15);
    expect(ADMIN_NAV_ITEMS.filter((i) => !i.inShell).map((i) => i.href)).toEqual(['/dashboard']);
  });

  it('#88 修复的四个页面都有真实页面名，不再回退到「管理」', () => {
    expect(findAdminPageLabel('/admin/prompts')).toBe('Prompt 管理');
    expect(findAdminPageLabel('/admin/scoring-dashboard')).toBe('评分看板');
    expect(findAdminPageLabel('/admin/evidence')).toBe('可信线索');
    expect(findAdminPageLabel('/admin/webhook-logs')).toBe('Webhook 日志');
  });

  it('映射表的 label 与清单 label 逐项一致（不是两份各写各的）', () => {
    for (const item of ADMIN_NAV_ITEMS.filter((i) => i.inShell)) {
      expect(ADMIN_PAGE_LABELS[item.href]).toBe(item.label);
    }
  });
});

describe('findAdminPageLabel', () => {
  it('精确匹配', () => {
    expect(findAdminPageLabel('/admin')).toBe('概览');
    expect(findAdminPageLabel('/admin/users')).toBe('用户管理');
  });

  it('子路径按最长前缀匹配', () => {
    expect(findAdminPageLabel('/admin/sources/123')).toBe('信源管理');
    expect(findAdminPageLabel('/admin/model-eval/history')).toBe('AI 引擎');
  });

  it('最长前缀：/admin 不吞掉更具体的子路径', () => {
    // '/admin' 是所有 /admin/* 的前缀，必须让更长的键先命中
    expect(findAdminPageLabel('/admin/sources')).not.toBe('概览');
    expect(findAdminPageLabel('/admin/sources')).toBe('信源管理');
  });

  it('未知路径回退到兜底文案', () => {
    expect(findAdminPageLabel('/admin/does-not-exist')).toBe(ADMIN_FALLBACK_LABEL);
    expect(findAdminPageLabel('/totally/unknown')).toBe(ADMIN_FALLBACK_LABEL);
  });

  it('壳外路径（监控大盘）不在壳内时也走兜底', () => {
    expect(findAdminPageLabel('/dashboard')).toBe(ADMIN_FALLBACK_LABEL);
  });
});
