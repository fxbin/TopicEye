import { describe, it, expect } from 'vitest';
import {
  getFavoriteTargetKey,
  getContentFavoriteKey,
  favoriteItemToTargetKey,
} from '@/lib/favorites';
import type { FavoriteItem } from '@/types';

describe('getFavoriteTargetKey', () => {
  it('uses target_key when provided', () => {
    expect(getFavoriteTargetKey({ target_type: 'source', target_key: 'rss://example.com' }))
      .toBe('source:rss://example.com');
  });

  it('trims whitespace in target_key', () => {
    expect(getFavoriteTargetKey({ target_type: 'source', target_key: '  abc  ' }))
      .toBe('source:abc');
  });

  it('falls back to target_id when target_key is empty', () => {
    expect(getFavoriteTargetKey({ target_type: 'content', target_id: 42 }))
      .toBe('content:42');
  });

  it('falls back to target_id when target_key is null', () => {
    expect(getFavoriteTargetKey({ target_type: 'content', target_id: 7, target_key: null }))
      .toBe('content:7');
  });

  it('falls back to target_id when target_key is undefined', () => {
    expect(getFavoriteTargetKey({ target_type: 'topic_group', target_id: 99 }))
      .toBe('topic_group:99');
  });

  it('prefers target_key over target_id', () => {
    expect(getFavoriteTargetKey({ target_type: 'source', target_id: 1, target_key: 'key-1' }))
      .toBe('source:key-1');
  });

  it('throws when neither target_key nor target_id is provided', () => {
    expect(() => getFavoriteTargetKey({ target_type: 'content' }))
      .toThrow('target_id or target_key is required');
  });

  it('throws when target_id is null and target_key is empty', () => {
    expect(() => getFavoriteTargetKey({ target_type: 'content', target_id: null, target_key: '' }))
      .toThrow('target_id or target_key is required');
  });

  it('handles empty string target_key (falls back to target_id)', () => {
    expect(getFavoriteTargetKey({ target_type: 'content', target_id: 5, target_key: '' }))
      .toBe('content:5');
  });
});

describe('getContentFavoriteKey', () => {
  it('generates content key from id', () => {
    expect(getContentFavoriteKey(123)).toBe('content:123');
  });

  it('generates content key for id 0', () => {
    expect(getContentFavoriteKey(0)).toBe('content:0');
  });
});

describe('favoriteItemToTargetKey', () => {
  it('extracts key from item with target_key', () => {
    const item = {
      id: 1,
      target_type: 'source' as const,
      target_id: null,
      target_key: 'rss://feed.xml',
      title: 'Test',
      status: 'researching' as const,
      created_at: '',
      updated_at: '',
      user_id: 1,
      position: 0,
    } as FavoriteItem;
    expect(favoriteItemToTargetKey(item)).toBe('source:rss://feed.xml');
  });

  it('extracts key from item with target_id', () => {
    const item = {
      id: 2,
      target_type: 'content' as const,
      target_id: 55,
      target_key: '',
      title: 'Test',
      status: 'researching' as const,
      created_at: '',
      updated_at: '',
      user_id: 1,
      position: 0,
    } as FavoriteItem;
    expect(favoriteItemToTargetKey(item)).toBe('content:55');
  });
});
