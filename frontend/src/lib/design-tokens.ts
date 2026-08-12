/**
 * TopicEye Design Tokens
 *
 * Tailwind CSS is the canonical visual system. The same values are
 * defined in `src/app/globals.css` via Tailwind v4 `@theme`.
 *
 * This object is a legacy compatibility mirror for existing inline
 * style code. New UI should prefer Tailwind utilities such as
 * `bg-primary-light`, `text-primary`, `border-gray-200`, `rounded-lg`,
 * `font-sans`, and `font-mono`.
 */

export const T = {
  // Primary (Orange)
  primary: '#FF6B35',
  primaryHover: '#E85D2A',
  primaryLight: '#FFF4EE',
  primaryBorder: '#FFD0B5',

  // Teal
  teal: '#00C9A7',
  tealHover: '#00B396',
  tealLight: '#E6FAF5',
  tealBorder: '#A7F0DB',

  // Purple
  purple: '#8B5CF6',
  purpleLight: '#F0EBFF',
  purpleBorder: '#C4B5FD',

  // Amber
  amber: '#D97706',
  amberLight: '#FEF3C7',
  amberBorder: '#FCD34D',

  // Red
  red: '#EF4444',
  redLight: '#FEE2E2',

  // Grays
  gray50: '#FAFAFA',
  gray100: '#F3F4F6',
  gray200: '#E5E7EB',
  gray300: '#D1D5DB',
  gray400: '#9CA3AF',
  gray500: '#6B7280',
  gray600: '#4B5563',
  gray700: '#374151',
  gray800: '#1F2937',
  gray900: '#111827',

  // Base
  white: '#FFFFFF',
  bg: '#F7F7F8',
  text: '#1A1A2E',

  // Border Radius
  radius: 12,
  radiusMd: 10,
  radiusSm: 8,
  radiusXs: 6,

  // Font
  mono: '"DM Mono", ui-monospace, monospace',
  sans: '"DM Sans", -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
} as const;

export type DesignTokens = typeof T;

/** 推荐等级配置 */
export const LEVEL_CONFIG: Record<string, { bg: string; color: string; border: string; dot: string }> = {
  '强烈建议写': { bg: T.primaryLight, color: T.primary, border: T.primaryBorder, dot: T.primary },
  '值得观察':   { bg: T.tealLight,    color: T.teal,    border: T.tealBorder,    dot: T.teal },
  '适合深挖':   { bg: T.purpleLight,  color: T.purple,  border: T.purpleBorder,  dot: T.purple },
  '适合蹭热点': { bg: T.amberLight,   color: T.amber,   border: T.amberBorder,   dot: T.amber },
  '不建议追':   { bg: T.gray100,      color: T.gray500, border: T.gray300,       dot: T.gray400 },
  '信号不足':   { bg: T.gray50,       color: T.gray400, border: T.gray200,       dot: T.gray300 },
};

/**
 * 推荐等级配置（Tailwind class 格式）。
 *
 * 从 hex 版 LEVEL_CONFIG 派生的 class 版，供 LevelBadge / today-picks 等
 * 用 Tailwind class 渲染的场景使用。字段名与 hex 版一致（bg/color/border/dot）。
 */
export const LEVEL_CONFIG_CLASSES: Record<string, { bg: string; color: string; border: string; dot: string }> = {
  '强烈建议写': { bg: 'bg-primary-light', color: 'text-primary',   border: 'border-primary-border', dot: 'bg-primary' },
  '值得观察':   { bg: 'bg-teal-light',    color: 'text-teal',      border: 'border-teal-border',    dot: 'bg-teal' },
  '适合深挖':   { bg: 'bg-purple-light',  color: 'text-purple',    border: 'border-purple-border',  dot: 'bg-purple' },
  '适合蹭热点': { bg: 'bg-amber-light',   color: 'text-amber',     border: 'border-amber-border',   dot: 'bg-amber' },
  '不建议追':   { bg: 'bg-gray-100',     color: 'text-gray-500',  border: 'border-gray-300',        dot: 'bg-gray-400' },
  '信号不足':   { bg: 'bg-gray-50',      color: 'text-gray-400',  border: 'border-gray-200',        dot: 'bg-gray-300' },
};

/**
 * 通用图表色板（10 色，无重复）。
 *
 * 供 stats / trends / algorithm 等图表场景使用。
 * 各页若有特化配色需求（如 stats 的 BAR_COLORS 只有 8 色且含重复），
 * 可保留本地版本；通用场景应优先用 CHART_COLORS。
 */
export const CHART_COLORS: readonly string[] = [
  '#FF6B35', // primary orange
  '#00C9A7', // teal
  '#3B82F6', // blue
  '#D97706', // amber
  '#10B981', // green
  '#EF4444', // red
  '#8B5CF6', // purple
  '#06B6D4', // cyan
  '#64748B', // slate
  '#EC4899', // pink
];

/** 分类列表 */
export const CATEGORIES = ['全部', 'AI', '职场', '商业', '教育', '自媒体', '科技', '生活', '产品'] as const;
export type Category = (typeof CATEGORIES)[number];

/** 内容形态列表（双轴分类的 format 轴） */
export const CONTENT_TYPES = ['全部', '论文', '技术', '资讯', '教程', '观点', '工具', '体验', '成长', '讨论', '项目'] as const;
export type ContentType = (typeof CONTENT_TYPES)[number];

// 注：RecommendLevel 类型的唯一来源是 @/types，此处不再保留副本。
// LEVEL_CONFIG 的 key 用 as RecommendLevel[] 访问即可。

/** 平台颜色映射 */
export const PLATFORM_COLOR_MAP: Record<string, { bg: string; color: string }> = {
  '公众号': { bg: '#EEF2FF', color: '#4F46E5' },
  '小红书': { bg: '#FFF1F2', color: '#E11D48' },
  '视频号': { bg: '#ECFDF5', color: '#059669' },
  '知乎':   { bg: '#EFF6FF', color: '#2563EB' },
  '抖音':   { bg: '#F5F3FF', color: '#7C3AED' },
  'arXiv':  { bg: '#FEF3C7', color: '#B45309' },
};

/** 信源类型颜色映射 */
export const SOURCE_TYPE_COLOR_MAP: Record<string, { bg: string; color: string }> = {
  'RSS':     { bg: '#EEF2FF', color: '#4F46E5' },
  'RSSHub':  { bg: '#ECFDF5', color: '#059669' },
  'Reddit':  { bg: '#FFF7ED', color: '#C2410C' },
  '网站':    { bg: '#FEF3C7', color: '#92400E' },
  'Zhihu':   { bg: '#EFF6FF', color: '#2563EB' },
};
