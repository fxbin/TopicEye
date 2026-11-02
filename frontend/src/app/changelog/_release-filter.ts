import type { ProductUpdateItem, ProductUpdateKind } from '@/types/product-feedback';

export function archiveDate(version: string): string | null {
  return /^\d{4}\.\d{2}\.\d{2}$/.test(version) ? version.replaceAll('.', '-') : null;
}

export function filterReleaseNotes(records: ProductUpdateItem[], query: string, kind: 'all' | ProductUpdateKind) {
  const normalize = (value: string) => value.toLocaleLowerCase().replaceAll('-', '.').trim();
  const needle = normalize(query);
  return records
    .filter(record => record.status === 'shipped')
    .filter(record => kind === 'all' || record.items.some(entry => entry.kind === kind))
    .filter(record => !needle || [record.version, record.title, record.summary, ...record.items.flatMap(entry => [entry.title, entry.description])].some(value => value && normalize(value).includes(needle)))
    .sort((a, b) => b.version.localeCompare(a.version, 'zh-CN', { numeric: true }) || b.id - a.id);
}
