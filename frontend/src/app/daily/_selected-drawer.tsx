'use client';

/**
 * 今日已选抽屉（一期补行动闭环）。
 *
 * 把 fire-and-forget 的「已选」标记汇总成一个可见抽屉：
 * - 列出今日 write 标记的选题，带「进 plan」入口；
 * - 顶部显示「今日已选 N」+「共 M 个标记」；
 * - 空态引导回榜单。
 *
 * 结构复刻 ReaderDrawer：overlay + 右侧滑出 + Esc/点遮罩关闭。
 */

import React, { useEffect } from 'react';
import { ExternalLink, Inbox, ListChecks, Target, X } from 'lucide-react';
import { cx } from '@/components/ui';

type MarkAction = 'write' | 'watch' | 'skip';

interface PickLike {
  title: string;
  source_title?: string;
  source_url?: string;
  category?: string;
  platforms?: string[];
}

function pickKey(pick: PickLike): string {
  return pick.source_title || pick.title || '';
}

export default function SelectedDrawer({
  open,
  onClose,
  picks,
  pickMarks,
}: {
  open: boolean;
  onClose: () => void;
  picks: PickLike[];
  pickMarks: Record<string, MarkAction>;
}) {
  // Esc 关闭（与 ReaderDrawer 一致）
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // 按 pickKey 建立索引，方便从 marks 反查 pick 详情
  const pickByKey = new Map<string, PickLike>();
  for (const p of picks) {
    const key = pickKey(p);
    if (key) pickByKey.set(key, p);
  }

  const writeKeys = Object.entries(pickMarks)
    .filter(([, a]) => a === 'write')
    .map(([k]) => k);
  const watchKeys = Object.entries(pickMarks)
    .filter(([, a]) => a === 'watch')
    .map(([k]) => k);
  const totalMarks = Object.keys(pickMarks).length;

  if (!open) return null;

  return (
    <>
      {/* 遮罩 */}
      <div
        className="fixed inset-0 z-40 bg-black/40 transition-opacity duration-300"
        onClick={onClose}
        aria-hidden
      />
      {/* 抽屉面板 */}
      <aside
        className={cx(
          'fixed right-0 top-0 z-50 flex h-full w-full max-w-[560px] flex-col bg-[#F7F8FA] shadow-2xl transition-transform duration-300',
        )}
        role="dialog"
        aria-label="今日已选"
      >
        {/* 头部 */}
        <header className="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-3.5">
          <div className="flex items-center gap-2">
            <ListChecks size={17} className="text-primary" strokeWidth={2.2} />
            <div>
              <div className="text-sm font-black text-gray-900">
                今日已选 <span className="text-primary">{writeKeys.length}</span>
              </div>
              {totalMarks > writeKeys.length && (
                <div className="text-[11px] text-gray-400">共 {totalMarks} 个标记</div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-xs text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </header>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* 已选（write）列表 */}
          <section className="mb-5">
            <div className="mb-2 text-[11px] font-bold text-gray-500">
              已选选题（{writeKeys.length}）
            </div>
            {writeKeys.length === 0 ? (
              <EmptyHint text="今日还没选选题，去榜单点「已选」标记想写的。" />
            ) : (
              <ul className="space-y-2">
                {writeKeys.map((key) => {
                  const pick = pickByKey.get(key);
                  return (
                    <li
                      key={key}
                      className="rounded-sm border border-gray-200 bg-white px-3 py-2.5"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="min-w-0 flex-1 text-[13px] font-bold leading-snug text-gray-800">
                          {pick?.title || key}
                        </span>
                        {pick?.category && (
                          <span className="shrink-0 rounded-xs bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-gray-500">
                            {pick.category}
                          </span>
                        )}
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <a
                          href="/plan"
                          className="inline-flex items-center gap-1 rounded-xs bg-primary px-2.5 py-1 text-[11px] font-bold text-white hover:bg-primary-hover"
                        >
                          <Target size={11} /> 进 plan
                        </a>
                        {pick?.source_url && (
                          <a
                            href={pick.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded-xs border border-gray-200 px-2 py-1 text-[11px] font-bold text-gray-500 hover:text-gray-700"
                          >
                            <ExternalLink size={11} /> 原文
                          </a>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* 观察（watch）列表 */}
          {watchKeys.length > 0 && (
            <section>
              <div className="mb-2 text-[11px] font-bold text-gray-500">
                观察中（{watchKeys.length}）
              </div>
              <ul className="space-y-1">
                {watchKeys.map((key) => {
                  const pick = pickByKey.get(key);
                  return (
                    <li
                      key={key}
                      className="flex items-center gap-2 rounded-xs bg-white px-3 py-1.5"
                    >
                      <span className="min-w-0 flex-1 truncate text-[12px] text-gray-600">
                        {pick?.title || key}
                      </span>
                      {pick?.source_url && (
                        <a
                          href={pick.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-gray-300 hover:text-gray-500"
                        >
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="grid place-items-center rounded-sm border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-[12px] text-gray-400">
      <div>
        <Inbox size={26} className="mx-auto mb-2 text-gray-300" strokeWidth={1.8} />
        {text}
      </div>
    </div>
  );
}
