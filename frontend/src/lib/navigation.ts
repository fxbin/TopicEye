import {
  BarChart3,
  BookOpen,
  Bookmark,
  Library,
  Rocket,
  BrainCircuit,
  CalendarDays,
  ClipboardList,
  Crosshair,
  Flame,
  Gem,
  GitBranch,
  Lightbulb,
  MessageSquareWarning,
  Newspaper,
  RadioTower,
  Search,
  Settings,
  Star,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import type { AuthUser } from '@/types';

export type NavAccess = 'public' | 'user' | 'admin';

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  access: NavAccess;
  countKey?: 'topics' | 'todayPicks' | 'favorites' | 'sources';
  /** 功能模块开关 key。若设置且对应 flag !== true，菜单项不渲染、路由被守卫拦截 */
  feature?: string;
}

export interface NavSpace {
  id: string;
  label: string;
  items: NavItem[];
}

export const NAV_SPACES: NavSpace[] = [
  {
    id: 'discover',
    label: '发现',
    items: [
      { id: 'lfv', label: '低粉爆文', href: '/low-follower-viral', icon: Flame, access: 'public' },
      { id: 'trending', label: '趋势雷达', href: '/trending', icon: Search, access: 'public' },
      { id: 'trends', label: '趋势追踪', href: '/trends', icon: TrendingUp, access: 'public' },
    ],
  },
  {
    id: 'today',
    label: '今日',
    items: [
      { id: 'today', label: '今日选题', href: '/', icon: Lightbulb, access: 'public', countKey: 'topics' },
      { id: 'picks', label: '当日精选', href: '/today-picks', icon: Star, access: 'public', countKey: 'todayPicks' },
    ],
  },
  {
    id: 'review',
    label: '复盘',
    items: [
      { id: 'daily', label: '日报', href: '/daily', icon: Newspaper, access: 'user' },
      { id: 'weekly', label: '周刊', href: '/weekly', icon: ClipboardList, access: 'user' },
      { id: 'monthly', label: '月刊', href: '/monthly', icon: CalendarDays, access: 'user' },
      { id: 'stats', label: '数据统计', href: '/stats', icon: BarChart3, access: 'user' },
    ],
  },
  {
    id: 'create',
    label: '创作',
    items: [
      { id: 'my-sources', label: '我的信源', href: '/sources/me', icon: RadioTower, access: 'user', countKey: 'sources' },
      { id: 'my-topics', label: '我的母题', href: '/my-topics', icon: Crosshair, access: 'user' },
      { id: 'favorites', label: '收藏夹', href: '/favorites', icon: Bookmark, access: 'user', countKey: 'favorites' },
      { id: 'algorithm', label: '算法流程', href: '/algorithm', icon: GitBranch, access: 'user' },
      { id: 'fanqie', label: '网文雷达', href: '/novel', icon: BookOpen, access: 'user', feature: 'webnovel_module' },
      { id: 'weread', label: '微信读书', href: '/weread', icon: Library, access: 'user' },
    ],
  },
  {
    id: 'account',
    label: '账户',
    items: [
      { id: 'plans', label: '权益规划', href: '/plans', icon: Gem, access: 'public' },
      { id: 'changelog', label: '更新记录', href: '/changelog', icon: Rocket, access: 'public' },
    ],
  },
  {
    id: 'manage',
    label: '管理',
    items: [
      { id: 'sources', label: '信源管理', href: '/sources', icon: RadioTower, access: 'admin', countKey: 'sources' },
      { id: 'model-eval', label: 'AI 引擎', href: '/model-eval', icon: BrainCircuit, access: 'admin' },
      { id: 'system-settings', label: '系统设置', href: '/admin/settings', icon: Settings, access: 'admin' },
      { id: 'changelog-mgmt', label: '发版记录', href: '/admin/updates', icon: Rocket, access: 'admin' },
      { id: 'feedback-mgmt', label: '反馈工作台', href: '/feedback', icon: MessageSquareWarning, access: 'admin' },
    ],
  },
];

const EXTRA_USER_ONLY_PATHS = ['/profile'];
const EXTRA_ADMIN_ONLY_PATHS = ['/contents', '/mother-topics/config', '/admin/updates'];

// 显式声明的公开路径（未登录可访问）。OAuth 回调页必须在此列，
// 否则未登录态进来会被路由守卫踢去 /login，丢失 URL fragment 里的 token。
const PUBLIC_PATHS = ['/login', '/oauth/callback'];

function uniquePaths(paths: string[]): string[] {
  return Array.from(new Set(paths));
}

function navPathsForAccess(access: NavAccess): string[] {
  return NAV_SPACES.flatMap((space) => space.items)
    .filter((item) => item.access === access)
    .map((item) => item.href);
}

export const USER_ONLY_PATHS = uniquePaths([...navPathsForAccess('user'), ...EXTRA_USER_ONLY_PATHS]);
export const ADMIN_ONLY_PATHS = uniquePaths([...navPathsForAccess('admin'), ...EXTRA_ADMIN_ONLY_PATHS]);

export function isAdmin(user: AuthUser | null): boolean {
  return user?.role === 'admin';
}

/** 检查某 feature 是否已启用。enabledFeatures 未加载时默认视为关（安全侧） */
function isFeatureEnabled(feature: string | undefined, enabledFeatures?: Record<string, boolean>): boolean {
  if (!feature) return true;  // 无 feature 关联 → 不受开关约束
  return Boolean(enabledFeatures?.[feature]);
}

export function canAccessNavItem(item: NavItem, user: AuthUser | null, enabledFeatures?: Record<string, boolean>): boolean {
  if (!isFeatureEnabled(item.feature, enabledFeatures)) return false;
  if (item.access === 'public') return true;
  if (item.access === 'admin') return isAdmin(user);
  return Boolean(user);
}

export function visibleNavSpaces(user: AuthUser | null, enabledFeatures?: Record<string, boolean>): NavSpace[] {
  return NAV_SPACES
    .map((space) => ({
      ...space,
      items: space.items.filter((item) => canAccessNavItem(item, user, enabledFeatures)),
    }))
    .filter((space) => space.items.length > 0);
}

function matchesPath(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** 找到匹配当前路径的 NavItem（用于 feature 守卫） */
function navItemForPath(pathname: string): NavItem | undefined {
  for (const space of NAV_SPACES) {
    for (const item of space.items) {
      if (matchesPath(pathname, item.href)) return item;
    }
  }
  return undefined;
}

export function requiredAccessForPath(pathname: string, enabledFeatures?: Record<string, boolean>): NavAccess {
  // feature 关闭的路径直接返回 'user'（让守卫把已登录用户踢回首页，未登录去登录页）
  // 这里返回 user 是为了让 canAccessPath 的 fallthrough 逻辑处理，真正的拦截在 canAccessPath
  if (PUBLIC_PATHS.some((href) => matchesPath(pathname, href))) return 'public';
  if (ADMIN_ONLY_PATHS.some((href) => matchesPath(pathname, href))) return 'admin';
  if (USER_ONLY_PATHS.some((href) => matchesPath(pathname, href))) return 'user';
  return 'public';
}

export function canAccessPath(pathname: string, user: AuthUser | null, enabledFeatures?: Record<string, boolean>): boolean {
  // feature 守卫：路径关联了未启用的 feature → 不可访问
  const item = navItemForPath(pathname);
  if (item && !isFeatureEnabled(item.feature, enabledFeatures)) return false;

  const access = requiredAccessForPath(pathname, enabledFeatures);
  if (access === 'public') return true;
  if (access === 'admin') return isAdmin(user);
  return Boolean(user);
}
