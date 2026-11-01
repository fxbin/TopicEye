/**
 * 首屏 feed 的查询口径（纯函数，客户端与服务端共用）。
 *
 * 首屏的参数必须与服务端直出的那次调用完全一致，否则两边的数据对不上
 * （客户端会以为服务端给的是"另一套筛选"的结果）。
 */

/**
 * 首屏每页的条数（客户端与服务端共用同一个值）。
 *
 * 为什么是 12 而不是 40：首屏要直出到 HTML 里，而 payload 与条数线性相关
 * ——实测 40 条的首屏 HTML 有 544KB（卡片标记 345KB + RSC flight 199KB），
 * 弱网下光下载就比"先拿骨架、再取数据"更慢。首屏实际只看得到 3–4 张卡片，
 * 12 条足够覆盖一屏还多留几屏的余量。
 *
 * **服务端与客户端必须用同一个值**：浏览快照（feed_snapshot）只钉住列表顺序，
 * 不钉页边界，后端按**请求里的 page_size** 切片
 * （`rows[(page-1)*page_size : page*page_size]`）。两边不一致，
 * 客户端的"加载更多"会跳过中间那几条。
 */
export const INITIAL_CONTENT_LIMIT = 12;
/** 与客户端 TIME_RANGE_HOURS['24h'] 一致 */
export const INITIAL_HOURS = 24;
/** 与客户端 tagFacets 的 limit 一致 */
export const INITIAL_TAG_FACET_LIMIT = 16;

/** 首屏列表的查询参数。与客户端首屏那次调用逐项对齐。 */
export function buildFeedQuery(limit = INITIAL_CONTENT_LIMIT, hours = INITIAL_HOURS): string {
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
