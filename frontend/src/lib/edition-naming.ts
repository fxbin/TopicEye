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
  weekly: '每周情报',
  monthly: '每月情报',
  /** 特刊预留位：特刊产品化时启用（圆桌 hc-002）。 */
  special: '专题情报',
} as const;

export type EditionKey = keyof typeof EDITION_LABELS;

/** 单走场景组串：品牌在场（推送卡片/邮件主题等无报头主标题的场合）。 */
export function editionTitle(key: EditionKey): string {
  return `选题雷达 · ${EDITION_LABELS[key]}`;
}
