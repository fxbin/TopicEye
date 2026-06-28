/**
 * 趋势（topic 曲线 + 关键词云）类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

export interface TrendPoint {
  date: string;
  topic_id: number;
  topic_name: string;
  content_count: number;
  avg_score: number;
  max_score: number;
  pick_count: number;
  top_items: { title: string; url: string; score: number }[] | null;
}

export interface TrendKeywordItem {
  keyword: string;
  count: number;
}