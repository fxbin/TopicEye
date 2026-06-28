/**
 * 用户问题反馈与产品更新类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

export type IssueFeedbackSeverity = 'low' | 'medium' | 'high' | 'critical';
export type IssueFeedbackStatus = 'open' | 'triaged' | 'in_progress' | 'fixed' | 'closed';
export type ProductUpdateKind = 'roadmap' | 'release' | 'fix' | 'improvement';
export type ProductUpdateStatus = 'planned' | 'in_progress' | 'shipped';

export interface IssueFeedbackItem {
  id: number;
  user_id: number | null;
  title: string;
  description: string;
  area: string;
  severity: IssueFeedbackSeverity;
  status: IssueFeedbackStatus;
  resolution_note?: string | null;
  fixed_at?: string | null;
  created_at: string;
  updated_at: string;
  reporter_email?: string | null;
  reporter_name?: string | null;
}

export interface IssueFeedbackListResponse {
  items: IssueFeedbackItem[];
  total: number;
  open_count: number;
  fixed_count: number;
}

export interface ProductUpdateEntry {
  title: string;
  description: string;
  kind: ProductUpdateKind;
}

export interface ProductUpdateItem {
  /** 1 个版本 = 1 记录; items[] 装该版本的全部更新 */
  id: number;
  version: string;
  status: ProductUpdateStatus;
  target_date?: string | null;
  shipped_at?: string | null;
  items: ProductUpdateEntry[];
  created_by_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProductUpdateListResponse {
  items: ProductUpdateItem[];
  total: number;
}