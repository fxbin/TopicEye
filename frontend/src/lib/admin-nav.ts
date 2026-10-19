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
   *
   * 2026-10-19（owner 验收反馈定稿）：「任务监控」从用户侧 /stats/jobs
   * 迁入本壳（/admin/jobs）——流水线健康信息本就属于后台；旧路径保留
   * 服务端跳转桩。清单自此前不再有壳外项。
   */
  inShell: boolean;
  /**
   * 导航分组（圆桌 2026-10-18，issue #121）：领域名词做组名（可猜中，
   * Nielsen 6「识别而非回忆」），组间顺序按操作频率排、组内按管道序。
   * 概览不归组，独立置顶。
   */
  group?: 'content' | 'eval' | 'users' | 'system';
}

export const ADMIN_NAV_GROUP_LABELS: Readonly<Record<NonNullable<AdminNavEntry['group']>, string>> = Object.freeze({
  content: '内容',
  eval: '评测',
  users: '用户',
  system: '系统',
});

export const ADMIN_NAV_ITEMS: readonly AdminNavEntry[] = [
  { id: 'dashboard', label: '概览', href: '/admin', inShell: true },
  { id: 'sources', label: '信源管理', href: '/admin/sources', inShell: true, group: 'content' },
  { id: 'contents', label: '内容管理', href: '/admin/contents', inShell: true, group: 'content' },
  { id: 'content-events', label: '事件治理', href: '/admin/content-events', inShell: true, group: 'content' },
  { id: 'mother-topics', label: '母题库', href: '/admin/mother-topics', inShell: true, group: 'content' },
  { id: 'model-eval', label: 'AI 引擎', href: '/admin/model-eval', inShell: true, group: 'eval' },
  { id: 'scoring-dashboard', label: '评分看板', href: '/admin/scoring-dashboard', inShell: true, group: 'eval' },
  { id: 'evidence', label: '可信线索', href: '/admin/evidence', inShell: true, group: 'eval' },
  { id: 'users', label: '用户管理', href: '/admin/users', inShell: true, group: 'users' },
  { id: 'feedback', label: '反馈工作台', href: '/admin/feedback', inShell: true, group: 'users' },
  { id: 'updates', label: '发版记录', href: '/admin/updates', inShell: true, group: 'users' },
  { id: 'monitor', label: '任务监控', href: '/admin/jobs', inShell: true, group: 'system' },
  { id: 'prompts', label: 'Prompt 管理', href: '/admin/prompts', inShell: true, group: 'system' },
  { id: 'webhook-logs', label: 'Webhook 日志', href: '/admin/webhook-logs', inShell: true, group: 'system' },
  { id: 'settings', label: '系统设置', href: '/admin/settings', inShell: true, group: 'system' },
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
