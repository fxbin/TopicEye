/**
 * 网文平台（番茄/七猫/知乎盐选）类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

export interface FanqieCategory {
  fanqie_id: string;
  name: string;
  group: 'male' | 'female';
}

export interface FanqieBook {
  book_id: string;
  url: string;
  book_name: string;
  author: string;
  abstract: string;
  thumb_uri: string;
  read_count: string;
  word_number: string;
  last_chapter_title: string;
  position: number;
  rank_type: string;
  rank_pos_diff?: number | null;
}

export interface WebnovelMovementItem {
  platform: 'fanqie' | 'qimao' | 'zhihu' | 'heiyan' | 'ishugui';
  platform_label: string;
  title: string;
  author: string;
  category: string;
  rank_type: string;
  position: number;
  change: number;
  url: string | null;
}

export interface WebnovelCategoryItem {
  category: string;
  count: number;
}

export interface WebnovelWeeklyReport {
  period: {
    start: string;
    end: string;
    days: number;
    label: string;
  };
  generated_at: string;
  summary: {
    total_items: number;
    snapshot_days: number;
    rising_count: number;
    falling_count: number;
    read_count_delta: number;
  };
  platforms: Array<{
    platform: 'fanqie' | 'qimao' | 'zhihu' | 'heiyan' | 'ishugui';
    label: string;
    item_count: number;
    rising_count: number;
    falling_count: number;
    history_days: number;
  }>;
  daily_counts: Array<{ date: string; count: number }>;
  top_risers: WebnovelMovementItem[];
  top_fallers: WebnovelMovementItem[];
  category_mix: Record<string, WebnovelCategoryItem[]>;
  notes: string[];
}

export interface QimaoBook {
  book_id: string;
  url: string;
  title: string;
  author: string;
  abstract: string;
  category1_name: string;
  category2_name: string;
  thumb_uri: string;
  words_num: string;
  collect_count: number;
  latest_chapter_title: string;
  update_time: string;
  is_over: number;
  is_continue_top: number;
  index_change: number;
  position: number;
  rank_type?: string;
}

export interface ZhihuAlbum {
  business_id: string;
  title: string;
  author: string;
  author_desc: string | null;
  abstract: string | null;
  thumb_url: string | null;
  chapter_text: string | null;
  price_yuan: string;
  price: number;
  is_exclusive: boolean;
  is_svip: boolean;
  online_time_text: string | null;
  tag: string | null;
  category1_name: string;
  category2_name: string | null;
  position: number;
  rank_pos_diff: number | null;
  url: string;
  sort_type: string;
}

export interface ZhihuCategory {
  zhihu_id: string;
  name: string;
  name_en: string | null;
  level: number;
  parent_id: string | null;
  sort: number;
  artwork: string | null;
}