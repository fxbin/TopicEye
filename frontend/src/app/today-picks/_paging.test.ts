import { describe, expect, it } from 'vitest';
import type { ContentItem, TopicInfo } from '@/types';
import {
  PICK_PAGE_SIZE,
  hasMorePicks,
  mergePickPage,
  mergePickTopics,
  nextPickOffset,
} from './_paging';

function item(id: number): ContentItem {
  return { id, title: `item ${id}` } as ContentItem;
}

function topic(id: number): TopicInfo {
  return { id, name: `topic ${id}`, best_score: 100 } as TopicInfo;
}

describe('今日选题滚动加载分页', () => {
  it('每页条数与后端 limit 一致', () => {
    expect(PICK_PAGE_SIZE).toBe(40);
  });

  it('把后端返回的一页并入已加载列表', () => {
    const merged = mergePickPage([item(1), item(2)], [item(3), item(4)]);
    expect(merged.map((i) => i.id)).toEqual([1, 2, 3, 4]);
  });

  it('追加时按 id 去重，不产生重复卡片', () => {
    // 翻页窗口内新内容入库会让 offset 位移，后一页可能重复上一页的条目
    const merged = mergePickPage([item(1), item(2), item(3)], [item(3), item(4)]);
    expect(merged.map((i) => i.id)).toEqual([1, 2, 3, 4]);
  });

  it('已加载条目的位置不被后续页改写', () => {
    const first = [item(1), item(2), item(3)];
    const merged = mergePickPage(first, [item(4), item(5)]);
    expect(merged.slice(0, 3)).toEqual(first);
  });

  it('空页不改变已加载列表', () => {
    const first = [item(1)];
    expect(mergePickPage(first, [])).toBe(first);
  });

  it('追加页引入的新话题被合并进来', () => {
    // 后端每页只返回该页涉及的话题；话题视图按话题列表分组渲染，
    // 漏合并会让追加页的条目在话题视图下消失
    const merged = mergePickTopics([topic(1)], [topic(2)]);
    expect(merged.map((t) => t.id)).toEqual([1, 2]);
  });

  it('话题按 id 去重，不产生重复分组', () => {
    const merged = mergePickTopics([topic(1), topic(2)], [topic(2), topic(3)]);
    expect(merged.map((t) => t.id)).toEqual([1, 2, 3]);
  });

  it('空话题页不改变已加载话题', () => {
    const first = [topic(1)];
    expect(mergePickTopics(first, [])).toBe(first);
  });

  it('下一批 offset 用实际已加载条数', () => {
    expect(nextPickOffset(40)).toBe(40);
    expect(nextPickOffset(120)).toBe(120);
  });

  it('优先用后端给的 has_more 判断是否还有后续', () => {
    // 服务端口径为准：它基于入选池的准确总数
    expect(hasMorePicks(40, 100, true)).toBe(true);
    expect(hasMorePicks(40, 100, false)).toBe(false);
  });

  it('没有 has_more 时退回按已加载条数与总数比较', () => {
    expect(hasMorePicks(40, 100)).toBe(true);
    expect(hasMorePicks(100, 100)).toBe(false);
  });
});
