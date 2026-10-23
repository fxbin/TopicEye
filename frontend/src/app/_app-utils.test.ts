import { describe, expect, it } from 'vitest';
import type { ContentItem } from '@/types';
import { getContentTime } from './_app-utils';

describe('event feed time', () => {
  it('keeps a recent event at its activity time when the preferred report is older', () => {
    const item = { published_at: '2026-10-20T01:00:00Z', event_activity_at: '2026-10-23T01:00:00Z' } as ContentItem;
    expect(getContentTime(item)).toBe('2026-10-23T01:00:00Z');
    expect(item.published_at).toBe('2026-10-20T01:00:00Z');
  });
  it('preserves article-time fallback outside the event feed', () => {
    const item = { published_at: '2026-10-20T01:00:00Z', crawled_at: '2026-10-23T01:00:00Z', event_activity_at: null } as ContentItem;
    expect(getContentTime(item)).toBe(item.published_at);
    expect(getContentTime({ ...item, published_at: '' })).toBe(item.crawled_at);
  });
});
