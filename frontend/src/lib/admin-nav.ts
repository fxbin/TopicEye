/**
 * 管理后台导航清单 —— 侧边栏与顶栏面包屑的唯一数据源。
 *
 * 存在理由（#88）：此前 `AdminSidebar` 维护 15 项导航，`AdminTopBar` 另有一份
 * 10 条的 `ADMIN_PAGE_LABELS`。两份目录互相矛盾，导致 4 个页面的顶栏回退显示
 * 兜底文案「管理」——顶栏说错了话，操作者与侧边栏自相矛盾。
 *
 * 现在面包屑映射由本清单**派生**而非手写：只要清单里有 `inShell` 的项，
 * 面包屑就必然有映射，该类漏项在结构上不可复发。
 *
 * 症状更正（独立复核发现，实现者原记有误）：修复前那 4 个无映射的页面
 * 顶栏显示的是「**概览**」而不是「管理」——旧实现里 `/admin` 本身就是
 * 前缀匹配键，`/admin/prompts` 先命中 `/admin/` 落成「概览」，压根走不到
 * 兜底文案。真实症状比原记录更严重：不是显示泛化文案，而是谎称在概览页。
 *
 * 图标是渲染关注点，留在 AdminSidebar（此处不 import React 组件，保证本模块
 * 保持纯逻辑、可在 node 环境直接测）。
 */

export interface AdminNavEntry {
  id: string;
  label: string;
  href: string;
  /**
   * 是否在 admin 壳内渲染并出现在面包屑里。
   * `/dashboard`（监控大盘）由侧边栏 `window.open` 在新标签页打开，
   * 脱离本壳，因此不参与面包屑映射。
   */
  inShell: boolean;
}

export const ADMIN_NAV_ITEMS: readonly AdminNavEntry[] = [
  { id: 'dashboard', label: '概览', href: '/admin', inShell: true },
  { id: 'monitor', label: '监控大盘', href: '/dashboard', inShell: false },
  { id: 'sources', label: '信源管理', href: '/admin/sources', inShell: true },
  { id: 'contents', label: '内容管理', href: '/admin/contents', inShell: true },
  { id: 'content-events', label: '内容事件治理', href: '/admin/content-events', inShell: true },
  { id: 'users', label: '用户管理', href: '/admin/users', inShell: true },
  { id: 'model-eval', label: 'AI 引擎', href: '/admin/model-eval', inShell: true },
  { id: 'mother-topics', label: '系统母题模板库', href: '/admin/mother-topics', inShell: true },
  { id: 'updates', label: '发版记录', href: '/admin/updates', inShell: true },
  { id: 'prompts', label: 'Prompt 管理', href: '/admin/prompts', inShell: true },
  { id: 'scoring-dashboard', label: '评分看板', href: '/admin/scoring-dashboard', inShell: true },
  { id: 'evidence', label: '可信线索', href: '/admin/evidence', inShell: true },
  { id: 'feedback', label: '反馈工作台', href: '/admin/feedback', inShell: true },
  { id: 'webhook-logs', label: 'Webhook 日志', href: '/admin/webhook-logs', inShell: true },
  { id: 'settings', label: '系统设置', href: '/admin/settings', inShell: true },
];

/** 壳内路由 → 页面名。由清单派生，不手写第二份。 */
export const ADMIN_PAGE_LABELS: Readonly<Record<string, string>> = Object.freeze(
  Object.fromEntries(ADMIN_NAV_ITEMS.filter((i) => i.inShell).map((i) => [i.href, i.label])),
);

/** 壳内全部路由，测试用它做「清单 ↔ 面包屑」一一对应核对。 */
export const ADMIN_IN_SHELL_PATHS: readonly string[] = ADMIN_NAV_ITEMS.filter(
  (i) => i.inShell,
).map((i) => i.href);

/** 未知路径的兜底文案。 */
export const ADMIN_FALLBACK_LABEL = '管理';

/** admin 壳根路由。概览页只有它自己一个路径，没有任何子页。 */
const SHELL_ROOT = '/admin';

/**
 * 由 pathname 解析顶栏面包屑的页面名。
 *
 * 先精确匹配，再按**最长前缀**匹配子路径，最后回退到兜底文案。
 *
 * 壳根 `/admin` 参与前缀匹配会吞掉一切：`/admin/任何未知路径` 都会被判成
 * 「概览」，让顶栏对不存在的页面说错话。概览无子页，故它只做精确匹配。
 */
export function findAdminPageLabel(pathname: string): string {
  const exact = ADMIN_PAGE_LABELS[pathname];
  if (exact) return exact;

  const sorted = Object.keys(ADMIN_PAGE_LABELS)
    .filter((key) => key !== SHELL_ROOT)
    .sort((a, b) => b.length - a.length);
  for (const key of sorted) {
    if (pathname.startsWith(`${key}/`)) return ADMIN_PAGE_LABELS[key];
  }
  return ADMIN_FALLBACK_LABEL;
}
