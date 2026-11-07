export const PICKS_VIEWS = [
  { value: 'picks', label: '精选内容' },
  { value: 'topics', label: '话题线索' },
  { value: 'keywords', label: '高频热词' },
] as const;
export type PicksView = typeof PICKS_VIEWS[number]['value'];
export const SNAPSHOT_WINDOWS = [3, 7, 14, 30] as const;

export function readPicksView(value: string | null | undefined): PicksView {
  return PICKS_VIEWS.find(view => view.value === value)?.value ?? 'picks';
}

export function readSnapshotDays(value: string | null | undefined): number {
  const days = Number(value);
  return SNAPSHOT_WINDOWS.some(window => window === days) ? days : 7;
}

export function picksViewHref(view: PicksView, current?: URLSearchParams): string {
  const params = new URLSearchParams(current);
  if (view === 'picks') params.delete('view');
  else params.set('view', view);
  const query = params.toString();
  return `/today-picks${query ? `?${query}` : ''}`;
}
