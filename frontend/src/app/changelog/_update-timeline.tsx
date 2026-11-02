'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { Badge, Panel, cx } from '@/components/ui';
import { UPDATE_KIND_LABELS, UPDATE_KIND_TONES } from '@/lib/product-feedback-labels';
import type { ProductUpdateItem } from '@/types/product-feedback';
import { archiveDate } from './_release-filter';

export function ReleaseNote({ item, latest = false, searching = false }: { item: ProductUpdateItem; latest?: boolean; searching?: boolean }) {
  const [expanded, setExpanded] = useState(latest || searching);
  const date = archiveDate(item.version);
  const contentId = `release-note-${item.id}`;
  return (
    <article className="grid min-w-0 gap-3 sm:grid-cols-[100px_minmax(0,1fr)] sm:gap-6">
      <div className="flex items-center gap-2 pt-1 sm:block sm:pt-5">
        <time dateTime={date || undefined} className="font-mono text-[13px] font-medium tabular-nums text-ink-500">{item.version}</time>
        {latest && <div className="sm:mt-2"><Badge tone="primary">最近更新</Badge></div>}
      </div>
      <Panel className={cx('overflow-hidden', latest && 'border-primary-border')}>
        <div className="p-5 sm:p-6">
          <h2>
            <button type="button" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(value => !value)} className="flex w-full items-start justify-between gap-4 text-left">
              <span className="min-w-0 text-lg font-semibold leading-7 text-ink-900">{item.title || item.version}</span>
              <ChevronDown size={18} className={cx('mt-1 shrink-0 text-ink-500 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
            </button>
          </h2>
          {item.summary && <p className="mt-2 text-sm leading-7 text-ink-500">{item.summary}</p>}
          <span className="mt-3 inline-block text-xs text-ink-500">{item.items.length} 项更新</span>
        </div>
        <div id={contentId} hidden={!expanded} className="border-t border-ink-100 px-5 py-5 sm:px-6">
          <ul className="space-y-5">
            {item.items.map((entry, index) => (
              <li key={`${entry.title}-${index}`} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3">
                <Badge tone={UPDATE_KIND_TONES[entry.kind]} className="mt-0.5">{UPDATE_KIND_LABELS[entry.kind]}</Badge>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold leading-6 text-ink-900">{entry.title}</h3>
                  <p className="mt-1 text-sm leading-7 text-ink-500">{entry.description}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </Panel>
    </article>
  );
}
