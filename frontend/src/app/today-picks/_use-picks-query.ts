import { useCallback } from 'react';
import { useFetch } from '@/hooks/useFetch';
import { contentsApi } from '@/lib/api';
import { PICK_PAGE_SIZE } from './_paging';

/** A response belongs to both its filters and the account that requested it. */
export function usePicksQuery(userId: number | null, category: string, contentType: string, timeRange: string) {
  const scope = JSON.stringify([userId, category, contentType, timeRange]);
  const buildParams = useCallback((offset: number) => ({
    ...(category ? { category } : {}),
    ...(contentType ? { content_type: contentType } : {}),
    time_range: timeRange,
    limit: PICK_PAGE_SIZE,
    offset,
  }), [category, contentType, timeRange]);
  const fetchPicks = useCallback(async () => ({
    ...await contentsApi.todayPicks(buildParams(0)), scope,
  }), [buildParams, scope]);
  const query = useFetch(fetchPicks, [scope]);
  return { ...query, data: query.data?.scope === scope ? query.data : null, scope, buildParams };
}
