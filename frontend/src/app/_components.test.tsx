import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

/**
 * 回归 #208：首页内容卡片的「更多反馈」下拉菜单被卡片裁掉。
 *
 * 菜单是绝对定位（absolute）浮层，挂在卡片最后一行按钮组的下方。
 * 卡片容器一旦带 overflow-hidden，超出卡片边界的菜单就会被裁掉，
 * 表现为「只剩贴着卡片下边缘的一条白边」，五个选项一个都点不到。
 *
 * 这里锁两件事：
 * 1. 承载下拉菜单的卡片不得裁剪溢出（overflow-hidden）。
 * 2. 菜单本身完整渲染五个反馈选项。
 */

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/components/ClientLayout', () => ({
  useAppContext: () => ({ currentUser: null, openReader: vi.fn() }),
}));

import { EditorialItem, FeedbackMenu } from './_components';
import type { ContentItem } from '@/types';

const item = {
  id: 42,
  title: '测试选题',
  source_id: 7,
  source_name: 'Hacker News Front Page',
  source_type: 'RSS',
  published_at: '2026-11-01T10:00:00Z',
  crawled_at: '2026-11-01T10:00:00Z',
  category: '科技',
  url: 'https://example.com/a',
} as ContentItem;

function cardHtml() {
  return renderToStaticMarkup(
    React.createElement(EditorialItem, {
      item,
      isFav: false,
      onToggleFav: vi.fn(),
      onIgnore: vi.fn(),
      time: '8 分钟前',
      timeLabel: '',
      onShowAnalysis: vi.fn(),
      onStartWorkflow: vi.fn(),
      workflowPending: false,
    }),
  );
}

describe('内容卡片的反馈菜单', () => {
  it('卡片容器不裁剪溢出，否则绝对定位的下拉菜单会被切掉', () => {
    const html = cardHtml();
    // 卡片根节点是 <section id="topic-item-…">
    const cardTag = html.match(/<section[^>]*id="topic-item-42"[^>]*>/)?.[0] ?? '';
    expect(cardTag).toBeTruthy();
    expect(cardTag).not.toMatch(/overflow-(hidden|clip)/);
  });

  it('下拉菜单完整列出五个反馈选项', () => {
    const html = renderToStaticMarkup(
      React.createElement(FeedbackMenu, {
        activeFeedback: null,
        pending: false,
        onSelect: vi.fn(),
      }),
    );
    for (const label of ['精选好文', '有价值', '不感兴趣', '不相关', '过时了']) {
      expect(html).toContain(label);
    }
  });

  it('菜单是绝对定位浮层，脱离文档流展开在按钮下方', () => {
    const html = renderToStaticMarkup(
      React.createElement(FeedbackMenu, {
        activeFeedback: null,
        pending: false,
        onSelect: vi.fn(),
      }),
    );
    expect(html).toContain('absolute');
    expect(html).toContain('top-full');
  });
});
