/**
 * 阅读记录（行为偏好数据）API。
 *
 * 后端 POST /read-records 为幂等 upsert：同一 (user, target_type, target_key)
 * 多次上报会累加 read_count / accumulated_ms，不新增行。
 * 前端在切换报告 / 页面隐藏 / 卸载时调用 report() 一次，不做高频心跳。
 */

import { request } from './_core';

export type ReadTargetType = 'daily_report' | 'weekly_digest' | 'monthly_digest';

export interface ReadRecordReportPayload {
  target_type: ReadTargetType;
  target_key: string;
  target_id?: number;
  duration_ms: number;
  topic_keywords?: string[];
  category?: string;
}

export interface ReadRecordResponse {
  id: number;
  user_id: number;
  target_type: string;
  target_key: string;
  target_id: number | null;
  read_count: number;
  accumulated_ms: number;
  max_progress: number;
  depth: string;
  topic_keywords: string[] | null;
  category: string | null;
  first_read_at: string;
  last_read_at: string;
  created_at: string;
  updated_at: string;
}

export const readRecordApi = {
  /** 上报一次阅读会话（幂等累加）。 */
  report(body: ReadRecordReportPayload): Promise<ReadRecordResponse> {
    return request('/read-records', { method: 'POST', body: JSON.stringify(body) });
  },
};
