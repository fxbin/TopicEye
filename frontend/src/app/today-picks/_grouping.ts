import type { ContentItem, TopicInfo } from '@/types';

/** 只有同时具备文章和话题资料的组才可展示；缺资料的文章留在独立列表。 */
export function groupPickItems(items: ContentItem[], topics: TopicInfo[]) {
  const topicMap = new Map<number | null, ContentItem[]>();
  const knownTopicIds = new Set(topics.map(topic => topic.id));
  const standaloneItems: ContentItem[] = [];
  for (const item of items) {
    const id = item.topic_id ?? null;
    if (!topicMap.has(id)) topicMap.set(id, []);
    topicMap.get(id)!.push(item);
    if (id === null || !knownTopicIds.has(id)) standaloneItems.push(item);
  }
  const sortedTopics = topics
    .filter(topic => topicMap.has(topic.id))
    .sort((a, b) => b.best_score - a.best_score);
  return { topicMap, sortedTopics, standaloneItems };
}
