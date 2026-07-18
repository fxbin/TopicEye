'use client';

/**
 * Sources page 3 个模态对话框。
 *
 * - AddSourceModal       添加信源模态
 * - BatchImportModal     批量导入模态（含预览面板）
 * - EditSourceModal      编辑信源模态
 *
 * 从 page.tsx 抽出约 148 行 JSX，减少主页面体积。
 */

import React from 'react';
import { Upload } from 'lucide-react';
import { Badge, Button, Panel } from '@/components/ui';
import SourceForm, { type FormState } from '@/components/SourceForm';
import type { BackendSource } from '@/components/SourceRow';
import { sourceTypeLabel } from '@/lib/source-sync-board';
import type { SourceBatchImportItem } from '@/lib/api';

export function AddSourceModal({
  form,
  setForm,
  submitting,
  onCreate,
  onClose,
}: {
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  submitting: boolean;
  onCreate: () => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}>
      <Panel onClick={(e) => e.stopPropagation()} className="w-full max-w-[480px] p-8 shadow-2xl">
        <h2 className="mb-6 text-xl font-black text-gray-900">添加信源</h2>
        <SourceForm form={form} setForm={setForm} />
        <div className="mt-7 flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting} className="px-5">
            取消
          </Button>
          <Button type="button" variant="primary" onClick={onCreate} disabled={submitting || !form.name.trim()} className="px-5">
            {submitting ? '提交中…' : '添加'}
          </Button>
        </div>
      </Panel>
    </div>
  );
}

export function BatchImportModal({
  batchImportContent,
  setBatchImportContent,
  batchImportCategory,
  setBatchImportCategory,
  batchImportPreview,
  batchImportPreviewing,
  batchImporting,
  fileInputRef,
  onPreview,
  onImport,
  onClose,
}: {
  batchImportContent: string;
  setBatchImportContent: (v: string) => void;
  batchImportCategory: string;
  setBatchImportCategory: (v: string) => void;
  batchImportPreview: SourceBatchImportItem[];
  batchImportPreviewing: boolean;
  batchImporting: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onPreview: () => void;
  onImport: () => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}
    >
      <Panel onClick={(event) => event.stopPropagation()} className="flex max-h-[86vh] w-full max-w-[860px] flex-col overflow-hidden p-0 shadow-2xl">
        <div className="border-b border-gray-100 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="mb-1 text-xl font-black text-gray-900">批量导入信源</h2>
              <p className="text-xs leading-5 text-gray-500">
                支持粘贴信源配置、JSON 数组、Markdown 链接清单或 OPML 内容；先预览重复项，再确认写入。
              </p>
            </div>
            <Button type="button" variant="ghost" onClick={onClose} className="min-h-8 px-2">
              ×
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="border-r border-gray-100 p-5">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <input
                value={batchImportCategory}
                onChange={(event) => setBatchImportCategory(event.target.value)}
                placeholder="导入分类"
                className="h-9 w-44 rounded-sm border border-gray-200 px-3 text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
              />
              <Button type="button" variant="secondary" onClick={() => fileInputRef.current?.click()}>
                <Upload size={15} />
                选择文件
              </Button>
              <Button type="button" variant="primary" onClick={onPreview} disabled={batchImportPreviewing || !batchImportContent.trim()}>
                {batchImportPreviewing ? '预览中…' : '解析预览'}
              </Button>
            </div>
            <textarea
              value={batchImportContent}
              onChange={(event) => {
                setBatchImportContent(event.target.value);
              }}
              placeholder={'粘贴 JSON / Markdown / OPML 信源配置，或类似：\n- [OpenAI Blog](https://openai.com/blog/rss.xml)\n- https://example.com/feed.xml'}
              className="h-[420px] w-full resize-none rounded-sm border border-gray-200 bg-gray-50 p-3 font-mono text-xs leading-6 text-gray-700 outline-none transition focus:border-primary-border focus:bg-white focus:ring-2 focus:ring-primary-light"
            />
          </div>

          <div className="flex min-h-0 flex-col p-5">
            <div className="mb-3 grid grid-cols-3 gap-2">
              <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                <div className="text-[10px] text-gray-400">识别</div>
                <div className="font-mono text-xl font-black text-gray-900">{batchImportPreview.length}</div>
              </div>
              <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                <div className="text-[10px] text-gray-400">可导入</div>
                <div className="font-mono text-xl font-black text-teal">{batchImportPreview.filter((item) => !item.duplicate).length}</div>
              </div>
              <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                <div className="text-[10px] text-gray-400">重复</div>
                <div className="font-mono text-xl font-black text-amber">{batchImportPreview.filter((item) => item.duplicate).length}</div>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto rounded-sm border border-gray-100">
              {batchImportPreview.length === 0 ? (
                <div className="p-6 text-center text-xs leading-6 text-gray-400">
                  解析后会在这里显示信源名称、类型和重复状态。
                </div>
              ) : batchImportPreview.map((item) => (
                <div key={item.url} className="border-b border-gray-100 p-3 last:border-b-0">
                  <div className="mb-1 flex items-start justify-between gap-2">
                    <div className="min-w-0 truncate text-[13px] font-black text-gray-800">{item.name}</div>
                    <Badge tone={item.duplicate ? 'amber' : 'teal'} className="shrink-0 py-0.5">
                      {item.duplicate ? '重复' : '新增'}
                    </Badge>
                  </div>
                  <div className="break-all font-mono text-[11px] leading-5 text-gray-400">{item.url}</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{sourceTypeLabel(item.source_type)}</span>
                    <span className="rounded bg-primary-light px-1.5 py-0.5 text-[10px] text-primary">{item.category}</span>
                    {item.platform && <span className="rounded bg-teal-light px-1.5 py-0.5 text-[10px] text-teal">{item.platform}</span>}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={onClose} disabled={batchImporting}>
                取消
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={onImport}
                disabled={batchImporting || batchImportPreview.filter((item) => !item.duplicate).length === 0}
              >
                {batchImporting ? '导入中…' : '确认导入'}
              </Button>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function EditSourceModal({
  form,
  setForm,
  submitting,
  onUpdate,
  onClose,
}: {
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  submitting: boolean;
  onUpdate: () => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}>
      <Panel onClick={(e) => e.stopPropagation()} className="w-full max-w-[480px] p-8 shadow-2xl">
        <h2 className="mb-6 text-xl font-black text-gray-900">编辑信源</h2>
        <SourceForm form={form} setForm={setForm} />
        <div className="mt-7 flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting} className="px-5">
            取消
          </Button>
          <Button type="button" variant="primary" onClick={onUpdate} disabled={submitting || !form.name.trim()} className="px-5">
            {submitting ? '保存中…' : '保存'}
          </Button>
        </div>
      </Panel>
    </div>
  );
}