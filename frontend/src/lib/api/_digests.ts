/**
 * _digests API objects extracted from lib/api.ts.
 * Uses request from ./_core.
 */

import { request } from './_core';
import type { WeeklyDigest, WeeklyDigestListResponse, WeeklyDigestWeeksResponse, MonthlyDigest, MonthlyDigestListResponse, MonthlyDigestMonthsResponse } from '@/types';

// ─── Weekly Digest (周刊) API ───

export const weeklyDigestApi = {
  /** 获取本周周刊（不存在则自动生成） */
  getCurrent(): Promise<WeeklyDigest> {
    return request('/weekly-digests/current');
  },

  /** 按 week_key 获取周刊 */
  getByWeek(weekKey: string): Promise<WeeklyDigest> {
    return request(`/weekly-digests/by-week?week_key=${encodeURIComponent(weekKey)}`);
  },

  /** 获取所有有周刊的周列表 */
  listWeeks(): Promise<WeeklyDigestWeeksResponse> {
    return request('/weekly-digests/weeks');
  },

  /** 获取周刊列表 */
  list(limit: number = 8): Promise<WeeklyDigestListResponse> {
    return request(`/weekly-digests?limit=${limit}`);
  },

  /** 强制重新生成周刊 */
  generate(weekKey?: string): Promise<WeeklyDigest> {
    const query = weekKey ? `?week_key=${encodeURIComponent(weekKey)}` : '';
    return request(`/weekly-digests/generate${query}`, { method: 'POST' });
  },

  /** 获取用户在指定周的选题标记追踪（引用日报标记） */
  pickTracking(weekKey: string): Promise<{
    marks: Array<{
      pick_title: string;
      action: 'write' | 'watch' | 'skip';
      mark_date: string;
      pick_category: string | null;
      appearances_in_week: number;
      appearance_dates: string[];
      pick_source_url: string | null;
    }>;
    total: number;
    week_key: string;
    week_range: string;
  }> {
    return request(`/weekly-digests/pick-tracking?week_key=${encodeURIComponent(weekKey)}`);
  },
};

// ─── Monthly Digest (月刊) API ───

export const monthlyDigestApi = {
  /** 获取最新完整月刊（不存在则自动生成） */
  getCurrent(): Promise<MonthlyDigest> {
    return request('/monthly-digests/current');
  },

  /** 按 month_key 获取月刊 */
  getByMonth(monthKey: string): Promise<MonthlyDigest> {
    return request(`/monthly-digests/by-month?month_key=${encodeURIComponent(monthKey)}`);
  },

  /** 获取所有有月刊的月份列表 */
  listMonths(): Promise<MonthlyDigestMonthsResponse> {
    return request('/monthly-digests/months');
  },

  /** 获取月刊列表 */
  list(limit: number = 12): Promise<MonthlyDigestListResponse> {
    return request(`/monthly-digests?limit=${limit}`);
  },

  /** 强制重新生成月刊 */
  generate(monthKey?: string): Promise<MonthlyDigest> {
    const query = monthKey ? `?month_key=${encodeURIComponent(monthKey)}` : '';
    return request(`/monthly-digests/generate${query}`, { method: 'POST' });
  },
};

