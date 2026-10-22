import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { FavoriteCard } from './_components';
import type { FavoriteItem, FavoriteStatus } from '@/types';

function card(status: FavoriteStatus, editPending = false) {
  const item: FavoriteItem = { id: 1, user_id: 1, target_type: 'content', target_id: 101, target_key: '101', title: '测试选题', status, position: 1, created_at: '2026-10-22T00:00:00Z', updated_at: '2026-10-22T00:00:00Z' };
  return renderToStaticMarkup(React.createElement(FavoriteCard, {
    item, selected: false, pending: false, dragging: false, dropBefore: false, dragEnabled: false,
    creatingKey: null, editing: false, editNote: '', editTags: '', editPending,
    onSelect: vi.fn(), onStatus: vi.fn(), onRemove: vi.fn(), onGeneratePlan: vi.fn(), onOpenSavedPlan: vi.fn(),
    onStartEdit: vi.fn(), onCancelEdit: vi.fn(), onEditNote: vi.fn(), onEditTags: vi.fn(), onSaveMeta: vi.fn(),
    onDragStart: vi.fn(), onDragHover: vi.fn(), onDragEnd: vi.fn(), onDrop: vi.fn(),
  }));
}

describe('favorite card action semantics', () => {
  it.each<FavoriteStatus>(['inbox', 'researching', 'drafting', 'archived'])('announces permanent deletion for %s items', (status) => {
    const html = card(status);
    expect(html).toContain('aria-label="删除收藏"');
    expect(html).not.toContain('aria-label="归档收藏"');
    expect(html).toContain('aria-label="「测试选题」的创作状态"');
  });

  it('prevents opening another note editor while a note is being saved', () => {
    const html = card('inbox', true);
    const noteButton = [...html.matchAll(/<button([^>]*)>([\s\S]*?)<\/button>/g)].find(([, , content]) => content.includes('备注'));
    expect(noteButton?.[1]).toContain('disabled=""');
  });
});
