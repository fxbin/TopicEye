import { describe, expect, it } from 'vitest';
import type { ContentItem, TopicInfo } from '@/types';
import { groupPickItems } from './_grouping';

const item = (id: number, topic_id: number | null = null) => ({ id, topic_id }) as ContentItem;
const topic = (id: number, best_score = 80) => ({ id, best_score }) as TopicInfo;

describe('精选分组可用性与完整性', () => {
  it('没有分组资料时保留全部文章供列表展示', () => {
    const items = [item(1), item(2, 99)];
    const result = groupPickItems(items, []);
    expect(result.sortedTopics).toEqual([]);
    expect(result.standaloneItems).toEqual(items);
  });
  it('筛选后不再有成员的话题不算可用分组', () => {
    expect(groupPickItems([item(1)], [topic(2)]).sortedTopics).toEqual([]);
  });
  it('真实分组按最高评分排列，孤儿话题文章仍在其他精选中', () => {
    const items = [item(1, 2), item(2, 3), item(3, 99), item(4)];
    const topics = [topic(2, 70), topic(3, 90), topic(4)];
    const { sortedTopics, topicMap, standaloneItems } = groupPickItems(items, topics);
    expect(sortedTopics.map(t => t.id)).toEqual([3, 2]);
    expect(standaloneItems.map(i => i.id)).toEqual([3, 4]);
    expect([...sortedTopics.flatMap(t => topicMap.get(t.id)!), ...standaloneItems].map(i => i.id).sort()).toEqual([1, 2, 3, 4]);
    expect(topics.map(t => t.id)).toEqual([2, 3, 4]);
  });
  it('追加页补齐话题资料后文章进入真实组，不重复展示', () => {
    const items = [item(1, 99)];
    expect(groupPickItems(items, []).standaloneItems).toEqual(items);
    const result = groupPickItems(items, [topic(99)]);
    expect(result.standaloneItems).toEqual([]);
    expect(result.topicMap.get(99)).toEqual(items);
    expect(result.sortedTopics.map(t => t.id)).toEqual([99]);
  });
});
