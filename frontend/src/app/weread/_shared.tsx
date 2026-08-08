/**
 * 微信读书书架页共享资产 barrel。
 *
 * 原始 1304 行文件已按职责拆分为 4 个子模块：
 * - _weread-utils.ts：常量、类型、纯工具函数
 * - _weread-cards.tsx：卡片组件（BookCard, DiscoverBookCard, BookDetailPanel, StatCard）
 * - _weread-charts.tsx：图表组件（StatusDonut, TopNBars, ProgressHistogram, CompletionFunnel, NoteDensityScatter, WeeklyPulse）
 * - _weread-stats.tsx：数据拉取组件（BestBookmarksSection, ReadingStatsCard, ShelfComparison）
 *
 * 本文件仅做 re-export，保持 page.tsx 与 _tabs.tsx 的 import 路径不变。
 */

export {
  SHELF_PAGE_SIZE,
  WEREAD_FALLBACK_URL,
  SORT_OPTIONS,
  GROUP_OPTIONS,
  parseWeReadMeta,
  getReadingStatus,
  wereadSearchUrl,
  wereadBookUrl,
  isPausedReading,
} from './_weread-utils';

export type {
  WeReadMeta,
  SortKey,
  SortOrder,
  GroupKey,
} from './_weread-utils';

export {
  BookCard,
  DiscoverBookCard,
  BookDetailPanel,
  StatCard,
} from './_weread-cards';

export {
  CHART_COLORS,
  StatusDonut,
  TopNBars,
  ProgressHistogram,
  CompletionFunnel,
  NoteDensityScatter,
  WeeklyPulse,
} from './_weread-charts';

export {
  BestBookmarksSection,
  ReadingStatsCard,
  ShelfComparison,
} from './_weread-stats';
