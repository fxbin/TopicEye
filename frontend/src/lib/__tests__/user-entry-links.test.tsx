import React from 'react';
import { createRequire } from 'node:module';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { FavoriteCard } from '@/app/favorites/_components';
import type { FavoriteItem } from '@/types';

const state = vi.hoisted(() => ({ novel: false }));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ currentUser: { role: 'user' }, enabledFeatures: { webnovel_module: state.novel } }) }));

const require = createRequire(import.meta.url);
const config = require('../../../next.config.js');

function renderFavorite(type: FavoriteItem['target_type']) {
  const noop = () => {};
  return renderToStaticMarkup(<FavoriteCard
    item={{ id: 1, target_type: type, target_id: 7, title: '收藏的信源', url: 'https://source.example/feed', status: 'inbox', snapshot: {} } as FavoriteItem}
    selected={false} pending={false} dragging={false} dropBefore={false} dragEnabled={false}
    creatingKey={null} editing={false} editNote="" editTags="" editPending={false}
    onSelect={noop} onStatus={noop} onRemove={noop} onGeneratePlan={noop} onOpenSavedPlan={noop}
    onStartEdit={noop} onCancelEdit={noop} onEditNote={noop} onEditTags={noop} onSaveMeta={noop}
    onDragStart={noop} onDragHover={noop} onDragEnd={noop} onDrop={noop}
  />);
}

describe('普通用户操作的目的地', () => {
  it('反馈建议保留前台路径，不重定向后台工作台', async () => {
    expect((await config.redirects()).some((r: { source: string }) => r.source === '/feedback')).toBe(false);
  });
  it('收藏信源保留原文，不误送后台或无关的个人信源列表', () => {
    const html = renderFavorite('source');
    expect(html).toContain('href="https://source.example/feed"');
    expect(html).not.toContain('/sources/me');
    expect(html).not.toContain('/admin');
  });
  it('模块关闭时小说收藏不显示不可达的榜单入口', () => {
    state.novel = false;
    expect(renderFavorite('book')).not.toContain('href="/novel"');
    state.novel = true;
    expect(renderFavorite('book')).toContain('href="/novel"');
  });
  it('内容收藏详情仍按内容ID读取选题详情', () => {
    expect(renderFavorite('content')).toContain('href="/topics/7"');
  });
});
