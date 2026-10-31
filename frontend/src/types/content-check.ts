/**
 * 文稿检测（违禁词/广告法极限词）前端类型。
 *
 * 与 backend/app/schemas/content_check.py 对齐（snake_case 保持后端字段名）。
 * start/end 是原文字符偏移（Unicode codepoint 坐标），前端高亮必须按
 * codepoint 切分（Array.from），不能直接用 UTF-16 下标切片。
 */

export type SensitiveCategory = 'advertising_extreme' | 'political_adult' | 'platform_throttle';

export type SensitiveSeverity = 'high' | 'medium' | 'low';

export interface SensitiveHit {
  word: string;
  category: SensitiveCategory;
  severity: SensitiveSeverity;
  start: number;
  end: number;
  suggestion?: string | null;
}

export interface SensitiveCheckResponse {
  total: number;
  hits: SensitiveHit[];
}

/** 分类展示口径：导航侧栏之外唯一的分类数据源（与后端 category 一一对应）。 */
export const SENSITIVE_CATEGORY_META: Record<SensitiveCategory, { label: string; description: string }> = {
  advertising_extreme: {
    label: '广告极限词',
    description: '广告法绝对化用语与极限表述，发布前建议逐条改写',
  },
  political_adult: {
    label: '高危违禁词',
    description: '涉政/成人/违法高危词，普通文稿建议直接删除',
  },
  platform_throttle: {
    label: '平台限流词',
    description: '导流、诱导与营销词，容易触发平台降权或限流',
  },
};

export const SENSITIVE_SEVERITY_LABELS: Record<SensitiveSeverity, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
};
