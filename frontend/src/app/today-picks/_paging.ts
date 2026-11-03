/**
 * Today picks 滚动加载的纯逻辑（无 React 依赖）。
 *
 * 从 app/today-picks/page.tsx 抽出，便于单测锁住分页语义：
 * - PICK_PAGE_SIZE：每页条数（后端 limit）
 * - mergePickPage：把后端返回的一页并入已加载列表
 * - nextPickOffset：算出下一批要请求的 offset
 * - hasMorePicks：判断是否还有后续内容
 *
 * 分页口径（#218）：后端按 offset 切片，返回的是同一条稳定序列的下一段，
 * 所以这里只需要按 id 去重追加，已加载条目的位置不会被后续页改写。
 */

import type { ContentItem, TopicInfo } from '@/types';

/** 每页条数。与后端 limit 一一对应。 */
export const PICK_PAGE_SIZE = 40;

/**
 * 把后端返回的一页并入已加载列表。
 *
 * 按 id 去重：翻页窗口内可能有新内容入库导致 offset 位移，后一页会重复出现
 * 上一页已加载的条目；去重后再追加，保证列表不出现重复卡片。
 */
export function mergePickPage(existing: ContentItem[], incoming: ContentItem[]): ContentItem[] {
  if (incoming.length === 0) return existing;
  const seen = new Set(existing.map((item) => item.id));
  const merged = [...existing];
  for (const item of incoming) {
    if (!seen.has(item.id)) {
      merged.push(item);
      seen.add(item.id);
    }
  }
  return merged;
}

/**
 * 把后端返回的一页话题并入已加载话题列表。
 *
 * 后端每页只返回该页条目涉及的话题。话题视图按话题列表分组渲染，所以追加页
 * 引入的新话题必须合并进来，否则这些话题下的条目会因没有对应分组而丢失。
 * 同 id 的话题以先到的为准，避免重复分组。
 */
export function mergePickTopics(existing: TopicInfo[], incoming: TopicInfo[]): TopicInfo[] {
  if (incoming.length === 0) return existing;
  const seen = new Set(existing.map((topic) => topic.id));
  const merged = [...existing];
  for (const topic of incoming) {
    if (!seen.has(topic.id)) {
      merged.push(topic);
      seen.add(topic.id);
    }
  }
  return merged;
}

/**
 * 下一批要请求的 offset。
 *
 * 用已加载条数而不是「已请求条数」：如果某一页因为入库位移导致去重后少了几条，
 * 用请求条数会跳过没拿到的内容，用实际已加载条数则能补回来。
 */
export function nextPickOffset(loadedCount: number): number {
  return loadedCount;
}

/**
 * 是否还有后续内容。
 *
 * 优先用后端给的 has_more（它基于服务端入选池的准确口径）；
 * 没有该字段时退回「已加载条数 < 总数」判断。
 */
export function hasMorePicks(loadedCount: number, total: number, serverHasMore?: boolean): boolean {
  if (typeof serverHasMore === 'boolean') return serverHasMore;
  return loadedCount < total;
}
