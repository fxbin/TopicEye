/**
 * 刊物种属词族 —— 全站唯一真相源（#132，命名圆桌 2026-10-20 定稿「情报正族」）。
 *
 * 公式 [时间/范围]+情报；与站点 tagline「创作者选题情报站」同族（家族感）。
 * 组串两模板：
 * - 报头眉题：只放种属词（EDITION_LABELS[key]），品牌由主标题「选题雷达」承担
 * - 单走场景（推送卡片/邮件主题）：editionTitle(key) =「选题雷达 · {种属}」双段拼，品牌在场
 *
 * 后端镜像 backend/app/core/edition_naming.py，由 scripts/check_edition_naming.py
 * 对账锁同步（模式同 check_scoring_mirror）。
 *
 * 注意：与 app/daily/_daily-utils.ts 的 SNAPSHOT_EDITION_LABELS（日报快照生命周期轴，
 * 午间/晚间/完整复盘）是两个概念，勿混用。
 */
export const EDITION_LABELS = {
  daily: '今日情报',
  /**
   * 日期中性形式：历史期出刊用。报头支持 ?date= 深链历史期，
   * 「今日情报」配历史日期会自相矛盾（#132 复审补的边界，圆桌未覆盖）。
   */
  daily_neutral: '每日情报',
  weekly: '每周情报',
  monthly: '每月情报',
  /** 特刊预留位：特刊产品化时启用（圆桌 hc-002）。 */
  special: '专题情报',
} as const;

export type EditionKey = keyof typeof EDITION_LABELS;

/**
 * 报头眉题用词：当日期「今日情报」，历史期（?date= 深链）用日期中性的
 * 「每日情报」——否则历史期报头会出现「今日情报 / 2026-09-01」自相矛盾。
 */
export function dailyEditionLabel(reportDate?: string | null): string {
  if (!reportDate) return EDITION_LABELS.daily_neutral;
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  return reportDate === iso ? EDITION_LABELS.daily : EDITION_LABELS.daily_neutral;
}
