/**
 * Daily Report & Creation API — 日报与创作方案。
 *
 * 从 _domains.ts 拆出。
 */

import { request } from './_core';
import type { PaginatedResponse, YesterdayTrackingData } from '@/types';

export interface WebhookDeliveryLogItem {
  id: number;
  alert_key: string;
  event_type: string;
  title: string;
  severity: string;
  webhook_url_preview: string;
  status_code: number | null;
  success: boolean;
  error_message: string | null;
  response_preview: string | null;
  duration_ms: number;
  created_at: string | null;
}

export const dailyReportApi = {
  /** 获取今日日报（不存在则自动生成） */
  getToday(): Promise<Record<string, unknown>> {
    return request('/daily-reports/today');
  },

  /** 按日期查询单个日报 */
  getByDate(date: string): Promise<Record<string, unknown>> {
    return request(`/daily-reports/by-date?date=${encodeURIComponent(date)}`);
  },

  /** 选题 sparkline 趋势数据（按标题关键词查询近 N 小时内容流入速率） */
  sparkline(title: string, hours: number = 48, bucketHours: number = 2): Promise<{
    points: Array<{ ts: string; count: number; baseline?: number }>;
    keywords: string[];
    total: number;
    window_hours: number;
  }> {
    return request(
      `/daily-reports/sparkline?title=${encodeURIComponent(title)}&hours=${hours}&bucket_hours=${bucketHours}`,
    );
  },

  /** 获取用户的选题标记 */
  listPickMarks(reportDate?: string): Promise<{
    marks: Array<{
      report_date: string;
      pick_title: string;
      action: 'write' | 'watch' | 'skip';
      pick_category: string | null;
      pick_source_url: string | null;
    }>;
    total: number;
  }> {
    return request(
      `/daily-reports/pick-marks${reportDate ? `?report_date=${reportDate}` : ''}`,
    );
  },

  /** 创建/更新选题标记 */
  markPick(body: {
    report_date: string;
    pick_title: string;
    action: 'write' | 'watch' | 'skip';
    pick_category?: string;
    pick_source_url?: string;
  }): Promise<{ status: string; action: string }> {
    return request('/daily-reports/pick-marks', { method: 'POST', body: JSON.stringify(body) });
  },

  /** 删除选题标记 */
  unmarkPick(reportDate: string, pickTitle: string): Promise<{ status: string }> {
    return request(
      `/daily-reports/pick-marks?report_date=${encodeURIComponent(reportDate)}&pick_title=${encodeURIComponent(pickTitle)}`,
      { method: 'DELETE' },
    );
  },

  /** 获取有日报的日期列表 */
  listDates(): Promise<{ dates: Array<{ report_date: string; weekday: string; takeaway: string | null; status: string }> }> {
    return request('/daily-reports/dates');
  },

  /** 获取最近一段时间的日报状态地图 */
  calendar(days: number = 30): Promise<{
    days: Array<{
      report_date: string;
      weekday: string;
      status: string;
      edition: string | null;
      generated_at: string | null;
      cutoff_at: string | null;
      takeaway: string | null;
      content_count: number;
      analyzed_count: number;
      topic_count: number;
      has_report: boolean;
      can_generate: boolean;
      is_today: boolean;
    }>;
    total_days: number;
    done_count: number;
    error_count: number;
    missing_count: number;
    generating_count: number;
  }> {
    return request(`/daily-reports/calendar?days=${days}`);
  },

  /** 日报列表 */
  list(limit: number = 7): Promise<{ items: Record<string, unknown>[]; total: number }> {
    return request(`/daily-reports?limit=${limit}`);
  },

  /** 强制重新生成今日日报 */
  regenerate(): Promise<Record<string, unknown>> {
    return request('/daily-reports/generate', { method: 'POST' });
  },

  /** 生成指定日报版本 */
  generateVersion(params: { target_date?: string; edition?: string; cutoff_at?: string; force?: boolean } = {}): Promise<Record<string, unknown>> {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k, String(v)])
    ).toString();
    return request(`/daily-reports/generate-version${query ? `?${query}` : ''}`, { method: 'POST' });
  },

  /** 手动推送日报到 webhook（管理员） */
  pushWebhook(date: string, edition?: string): Promise<{ sent: boolean; message: string }> {
    const params = new URLSearchParams({ date });
    if (edition) params.set('edition', edition);
    return request(`/daily-reports/push-webhook?${params}`, { method: 'POST' });
  },

  /** 获取 webhook 推送日志（管理员） */
  listWebhookLogs(params?: { event_type?: string; limit?: number; offset?: number }): Promise<{
    items: WebhookDeliveryLogItem[];
    total: number;
    limit: number;
    offset: number;
  }> {
    const qs = new URLSearchParams();
    if (params?.event_type) qs.set('event_type', params.event_type);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const query = qs.toString();
    return request(`/daily-reports/webhook-logs${query ? '?' + query : ''}`);
  },

  /** 昨日追踪（公共日报）：昨日 top picks 的 24h 热度 delta + lifecycle 验证 */
  getYesterdayTracking(reportDate: string): Promise<YesterdayTrackingData> {
    return request(`/daily-reports/yesterday-tracking?report_date=${encodeURIComponent(reportDate)}`);
  },

  // ── /me series: user-owned private daily reports (T2) ──

  /** 获取今日我的专属日报（不存在则自动生成；需 Pro+） */
  getMyToday(): Promise<Record<string, unknown>> {
    return request('/daily-reports/me/today');
  },

  /** 按日期查询我的日报 */
  getMyByDate(date: string): Promise<Record<string, unknown>> {
    return request(`/daily-reports/me/by-date?date=${encodeURIComponent(date)}`);
  },

  /** 获取我的日报日期列表 */
  listMyDates(): Promise<{ dates: Array<{ report_date: string; weekday: string; takeaway: string | null; status: string }> }> {
    return request('/daily-reports/me/dates');
  },

  /** 强制重新生成我的今日日报 */
  regenerateMy(): Promise<Record<string, unknown>> {
    return request('/daily-reports/me/generate', { method: 'POST' });
  },

  /** 昨日追踪（我的日报，Pro+）：额外返回 your_marked（昨日 write/watch 标记的今日进展） */
  getMyYesterdayTracking(reportDate: string): Promise<YesterdayTrackingData> {
    return request(`/daily-reports/me/yesterday-tracking?report_date=${encodeURIComponent(reportDate)}`);
  },
};

export const creationApi = {
  /** 生成创作方案（快速模式） */
  generatePlan(contentId: number, platform: string): Promise<Record<string, unknown>> {
    return request('/creation/plan', {
      method: 'POST',
      body: JSON.stringify({ content_id: contentId, platform }),
    });
  },

  /** 获取可用平台列表 */
  listPlatforms(): Promise<Record<string, unknown>> {
    return request('/creation/platforms');
  },

  /** 探索期：假设挑战 + 方向生成（探索模式 Step 1） */
  exploreDirections(contentId: number): Promise<Record<string, unknown>> {
    return request('/creation/explore', {
      method: 'POST',
      body: JSON.stringify({ content_id: contentId }),
    });
  },

  /** 聚焦期：苏格拉底追问（探索模式 Step 2） */
  focusQuestions(params: {
    content_id: number;
    selected_direction: string;
    unique_value?: string;
    pitfall?: string;
    focus_round: number;
    previous_qa?: Array<Record<string, unknown>>;
    user_redirect?: string;
  }): Promise<Record<string, unknown>> {
    return request('/creation/focus', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 收敛期：结构化方案输出（探索模式 Step 3） */
  convergePlan(params: {
    content_id: number;
    platform: string;
    selected_direction: string;
    focus_answers: Array<Record<string, unknown>>;
  }): Promise<Record<string, unknown>> {
    return request('/creation/converge', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
};
