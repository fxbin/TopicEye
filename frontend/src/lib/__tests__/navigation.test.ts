import { describe, it, expect } from 'vitest';
import type { AuthUser } from '@/types';
import {
  NAV_SPACES,
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
    const sources = itemById('sources');
    expect(canAccessNavItem(sources, normalUser)).toBe(false);
    expect(canAccessNavItem(sources, adminUser)).toBe(true);
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
    expect(canAccessPath('/admin/sources', normalUser)).toBe(false);
    expect(canAccessPath('/admin/sources', adminUser)).toBe(true);
  });

  it('feature 未开启的路径被守卫拦截', () => {
    expect(canAccessPath('/novel', normalUser)).toBe(false);
    expect(canAccessPath('/novel', normalUser, { webnovel_module: true })).toBe(true);
  });

  it('子路径按前缀匹配（/sources/xxx 视为 /sources）', () => {
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
    expect(USER_ONLY_PATHS).toContain('/profile');
    expect(USER_ONLY_PATHS).toContain('/daily');
  });
});
