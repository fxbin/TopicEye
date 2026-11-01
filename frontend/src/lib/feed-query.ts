/**
 * 首屏 feed 的查询口径（纯函数，客户端与服务端共用）。
 *
 * 一个数：**一页多少条**。服务端直出首屏、客户端「加载更多」、后端分页切片
 * 全都用它——浏览快照（feed_snapshot）把 page_size 绑进了摘要（见
 * `ContentListCacheParams.key`），所以同一次浏览里 page_size 必须始终一致，
 * 不一致会被后端判成"内容顺序已更新"而 409。
 *
 * 为什么是 40：这是改造前的行为，不改它。首页首屏整页直出到 HTML（gzip 后
 * 约 95KB、1 个阶段），比改造前"先拿 31KB 空壳、再下 200KB JS、再取 188KB
 * API"的 3 段链路（约 236KB）更快，而用户看到的条数与交互完全不变。
 */

/** 一页的条数：服务端首屏直出、客户端「加载更多」、后端分页切片共用 */
export const FEED_PAGE_SIZE = 40;

/** 与客户端 TIME_RANGE_HOURS['24h'] 一致 */
export const INITIAL_HOURS = 24;

/** 与客户端 tagFacets 的 limit 一致 */
export const INITIAL_TAG_FACET_LIMIT = 16;

/** 首屏列表的查询参数。与客户端首屏那次调用逐项对齐。 */
export function buildFeedQuery(limit = FEED_PAGE_SIZE, hours = INITIAL_HOURS): string {
  return new URLSearchParams({
    page_size: String(limit),
    hours: String(hours),
    include_trend_sources: 'false',
    group_events: 'true',
    stable_feed: 'true',
  }).toString();
}

/** 标签分面的查询参数。与客户端首屏那次调用对齐。 */
export function buildTagFacetQuery(hours = INITIAL_HOURS, limit = INITIAL_TAG_FACET_LIMIT): string {
  return new URLSearchParams({
    hours: String(hours),
    limit: String(limit),
  }).toString();
}
