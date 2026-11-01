import HomeFeed from './_home-feed';
import { fetchInitialFeed } from '@/lib/server-feed';
import { prefetchInitialData } from '@/lib/server-prefetch';

/**
 * 首页（服务端组件）。
 *
 * 首屏要用的数据在这里一次取好（内容列表 / 分类 / 标签分面），直接进首屏 HTML：
 * 首页原本整页是客户端组件，内容列表在 useEffect 里才拉，首屏最大文本块
 * （第一张选题卡的标题）必须等「JS bundle → hydration → 客户端取数 → 渲染」
 * 才画得出来，LCP 被整条客户端链路拖着。
 *
 * prefetchInitialData 与根布局共用（React cache()），拿 userId 用来判断
 * "用户变了要重新取数"，不会多打一次后端；它本来就被布局 await 过，
 * 这里再取不增加首屏延迟。
 */
export default async function HomePage() {
  const { user } = await prefetchInitialData();
  const feed = await fetchInitialFeed({ userId: user?.id ?? null });
  return <HomeFeed initialFeed={feed} />;
}
