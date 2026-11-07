import { describe, it, expect } from 'vitest';
import type { AuthUser } from '@/types';
import {
  NAV_SPACES,
  accessRedirect,
  loginHref,
  sanitizeReturnTo,
  USER_ONLY_PATHS,
  ADMIN_ONLY_PATHS,
  isAdmin,
  canAccessNavItem,
  visibleNavSpaces,
  requiredAccessForPath,
  canAccessPath,
  type NavItem,
} from '@/lib/navigation';

const adminUser = { role: 'admin' } as unknown as AuthUser;
const normalUser = { role: 'user' } as unknown as AuthUser;

const allItems = NAV_SPACES.flatMap((s) => s.items);
const itemById = (id: string): NavItem => {
  const found = allItems.find((i) => i.id === id);
  if (!found) throw new Error(`nav item not found: ${id}`);
  return found;
};

describe('isAdmin', () => {
  it('区分 admin / user / 未登录', () => {
    expect(isAdmin(adminUser)).toBe(true);
    expect(isAdmin(normalUser)).toBe(false);
    expect(isAdmin(null)).toBe(false);
  });
});

describe('canAccessNavItem', () => {
  it('公开项对任何人可见（含未登录）', () => {
    expect(canAccessNavItem(itemById('trending'), null)).toBe(true);
  });

  it('user 项要求登录', () => {
    const daily = itemById('daily');
    expect(canAccessNavItem(daily, null)).toBe(false);
    expect(canAccessNavItem(daily, normalUser)).toBe(true);
  });

  it('admin 项仅管理员可见', () => {
    const adminConsole = itemById('admin-console');
    expect(canAccessNavItem(adminConsole, normalUser)).toBe(false);
    expect(canAccessNavItem(adminConsole, adminUser)).toBe(true);
  });

  it('feature 未开启时即便是管理员也不可见', () => {
    const fanqie = itemById('fanqie'); // feature: webnovel_module
    expect(canAccessNavItem(fanqie, adminUser)).toBe(false);
    expect(canAccessNavItem(fanqie, adminUser, { webnovel_module: true })).toBe(true);
  });
});

describe('requiredAccessForPath', () => {
  it('按路径归类访问级别', () => {
    expect(requiredAccessForPath('/login')).toBe('public');
    expect(requiredAccessForPath('/admin/sources')).toBe('admin');
    expect(requiredAccessForPath('/daily')).toBe('user');
    expect(requiredAccessForPath('/some-unknown-path')).toBe('public');
  });
});

describe('canAccessPath', () => {
  it('公开路径无需登录', () => {
    expect(canAccessPath('/login', null)).toBe(true);
    expect(canAccessPath('/oauth/callback', null)).toBe(true);
    expect(canAccessPath('/', null)).toBe(true);
  });

  it('user 路径要求登录', () => {
    expect(canAccessPath('/daily', null)).toBe(false);
    expect(canAccessPath('/daily', normalUser)).toBe(true);
  });

  it('admin 路径仅管理员可进', () => {
    expect(canAccessPath('/admin', normalUser)).toBe(false);
    expect(canAccessPath('/admin', adminUser)).toBe(true);
  });

  it('feature 未开启的路径被守卫拦截', () => {
    expect(canAccessPath('/novel', normalUser)).toBe(false);
    expect(canAccessPath('/novel', normalUser, { webnovel_module: true })).toBe(true);
  });

  it('子路径按前缀匹配（/admin/sources/xxx 视为 /admin/sources）', () => {
    expect(canAccessPath('/admin/sources/123', adminUser)).toBe(true);
    expect(canAccessPath('/admin/sources/123', normalUser)).toBe(false);
  });
});

describe('visibleNavSpaces', () => {
  it('未登录仅保留含公开项的分区', () => {
    const ids = visibleNavSpaces(null).map((s) => s.id);
    expect(ids).toEqual(['discover', 'today', 'account']);
  });

  it('管理员可见全部分区', () => {
    const ids = visibleNavSpaces(adminUser).map((s) => s.id);
    expect(ids).toContain('review');
    expect(ids).toContain('create');
    expect(ids).toContain('manage');
  });

  it('feature 开关控制受限项是否出现', () => {
    const createOff = visibleNavSpaces(adminUser).find((s) => s.id === 'create');
    expect(createOff?.items.some((i) => i.id === 'fanqie')).toBe(false);
    const createOn = visibleNavSpaces(adminUser, { webnovel_module: true }).find((s) => s.id === 'create');
    expect(createOn?.items.some((i) => i.id === 'fanqie')).toBe(true);
  });
});

describe('派生路径集合', () => {
  it('ADMIN_ONLY_PATHS / USER_ONLY_PATHS 覆盖关键路径', () => {
    expect(ADMIN_ONLY_PATHS).toContain('/admin/contents');
    expect(ADMIN_ONLY_PATHS).toContain('/admin/model-eval');
    // #121：任务统计从用户侧迁入后台，权限随之收紧
    expect(ADMIN_ONLY_PATHS).toContain('/admin/jobs');
    expect(requiredAccessForPath('/admin/jobs')).toBe('admin');
    expect(USER_ONLY_PATHS).toContain('/profile');
    expect(USER_ONLY_PATHS).toContain('/daily');
  });
});

describe('登录与权限拦截去向', () => {
  it('普通用户反馈入口与个人历史同属前台', () => {
    expect(itemById('feedback').href).toBe('/feedback');
    expect(canAccessNavItem(itemById('feedback'), normalUser)).toBe(true);
    expect(canAccessNavItem(itemById('feedback'), null)).toBe(false);
    expect(requiredAccessForPath('/feedback')).toBe('user');
    expect(accessRedirect('/feedback', normalUser)).toBeNull();
  });
  it('未登录时保留路径和查询参数以便登录后回跳', () => {
    expect(accessRedirect('/daily', null, {}, '?scope=mine&date=2026-11-03')).toBe('/login?returnTo=%2Fdaily%3Fscope%3Dmine%26date%3D2026-11-03');
    expect(accessRedirect('/feedback', null)).toBe('/login?returnTo=%2Ffeedback');
  });
  it('已登录但功能关闭或权限不足时不会误送登录', () => {
    expect(accessRedirect('/novel', normalUser, {})).toBe('/');
    expect(accessRedirect('/admin/feedback', normalUser)).toBe('/');
    expect(accessRedirect('/novel', normalUser, { webnovel_module: true })).toBeNull();
    expect(accessRedirect('/admin/feedback', adminUser)).toBeNull();
  });
});

describe('操作要求登录后的回跳', () => {
  it('保留原页面和筛选条件并拒绝站外地址', () => {
    expect(loginHref('/trending?category=tech')).toBe('/login?returnTo=%2Ftrending%3Fcategory%3Dtech');
    expect(loginHref('//evil.example')).toBe('/login?returnTo=%2F');
    expect(loginHref()).toBe('/login?returnTo=%2F');
  });
});

describe('登录回跳地址安全', () => {
  it.each(['/\n/evil.example', '/\t/evil.example', '/\r/evil.example', '//evil.example', '/\\evil.example', '/\u0000/evil.example', '/x\u007f'])('拒绝浏览器可能归一化为站外的输入 %j', value => {
    expect(sanitizeReturnTo(value)).toBe('/');
    expect(new URL(sanitizeReturnTo(value), 'https://topiceye.example').origin).toBe('https://topiceye.example');
  });
  it('保留正常站内路径和 OAuth 参数', () => {
    expect(sanitizeReturnTo('/mcp/authorize?request_id=abc&scope=read')).toBe('/mcp/authorize?request_id=abc&scope=read');
  });
});

describe('精选与材料入口收敛', () => {
  it('各角色只保留一个精选入口', () => {
    for (const user of [null, normalUser, adminUser]) {
      const items = visibleNavSpaces(user).flatMap(space => space.items);
      expect(items.filter(item => item.href === '/today-picks')).toHaveLength(1);
      expect(items.some(item => item.href === '/trends')).toBe(false);
    }
  });
});
