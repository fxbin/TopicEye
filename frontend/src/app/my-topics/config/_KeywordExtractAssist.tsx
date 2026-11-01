'use client';

/**
 * 关键词 AI 提取辅助（issue #187）。
 *
 * 用户用一句话描述想看的内容 → 调 extract-keywords 拿候选词 → 勾选 →
 * 「加入 N 个关键词」只改表单里的关键词框文本，不发任何保存请求；
 * 落库仍走表单既有的「创建/保存」按钮。
 */

import React, { useId, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Button, cx } from '@/components/ui';
import { FieldLabel } from '@/components/form';
import { motherTopicsApi } from '@/lib/api';
import { annotateExtracted, mergeSelectedKeywords, type AnnotatedKeyword } from './_keyword-extract';

const DESCRIPTION_MAX_LENGTH = 500;

export default function KeywordExtractAssist({
  keywordsText,
  onApply,
}: {
  /** 表单里当前的关键词框文本（逗号拼接） */
  keywordsText: string;
  /** 应用勾选结果：接收合并后的新文本 */
  onApply: (nextKeywordsText: string) => void;
}) {
  const inputId = useId();
  const [description, setDescription] = useState('');
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<AnnotatedKeyword[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const selectedNewCount = candidates.filter(c => !c.alreadyPresent && selected[c.keyword]).length;

  const handleExtract = async () => {
    const trimmed = description.trim();
    if (!trimmed || extracting) return;
    setExtracting(true);
    setExtractError(null);
    setCandidates([]);
    setSelected({});
    try {
      const result = await motherTopicsApi.extractKeywords(trimmed);
      const annotated = annotateExtracted(result.keywords, keywordsText);
      setCandidates(annotated);
      // 新词默认勾选；已有的词标「已有」且不可勾选
      setSelected(
        Object.fromEntries(annotated.filter(c => !c.alreadyPresent).map(c => [c.keyword, true])),
      );
    } catch (err) {
      // 失败只提示，不动已填的关键词；后端 detail 已带手动填词的出路文案
      setExtractError(err instanceof Error ? err.message : '关键词提取失败，请稍后重试');
    } finally {
      setExtracting(false);
    }
  };

  const handleApply = () => {
    const chosen = candidates
      .filter(c => !c.alreadyPresent && selected[c.keyword])
      .map(c => c.keyword);
    if (chosen.length === 0) return;
    onApply(mergeSelectedKeywords(keywordsText, chosen));
    setCandidates([]);
    setSelected({});
  };

  return (
    <div className="rounded-xs border border-gray-200 bg-gray-50/60 p-3">
      <FieldLabel htmlFor={inputId}>用一句话描述你想看的内容</FieldLabel>
      <textarea
        id={inputId}
        value={description}
        onChange={e => setDescription(e.target.value)}
        maxLength={DESCRIPTION_MAX_LENGTH}
        rows={2}
        placeholder="如：我想看 AI 工具和新能源车相关的内容"
        className="w-full resize-y rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
      />
      <div className="mt-0.5 flex items-center justify-between">
        <span className="text-[11px] text-gray-400">AI 从描述里提取候选关键词，勾选后加入，也可直接手填</span>
        <span className="text-[11px] text-gray-400">{description.length}/{DESCRIPTION_MAX_LENGTH}</span>
      </div>

      <Button
        type="button"
        onClick={handleExtract}
        disabled={extracting || !description.trim()}
        variant="secondary"
        className="mt-1.5 min-h-0 px-3 py-1.5 text-xs font-medium"
      >
        <Sparkles size={13} />
        {extracting ? '提取中...' : 'AI 提取关键词'}
      </Button>

      {extractError && (
        <p role="alert" className="m-0 mt-2 text-xs leading-5 text-red">
          {extractError}
        </p>
      )}

      {candidates.length > 0 && (
        <div className="mt-2.5">
          <div className="mb-1.5 text-xs text-gray-500">
            勾选要加入的关键词（标「已有」的已在关键词框里，不会重复加入）：
          </div>
          <div className="flex flex-wrap gap-1.5">
            {candidates.map(candidate => (
              <label
                key={candidate.keyword}
                className={cx(
                  'inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs',
                  candidate.alreadyPresent && 'cursor-default border-gray-100 bg-gray-50 text-gray-400',
                )}
              >
                <input
                  type="checkbox"
                  className="accent-primary"
                  checked={!candidate.alreadyPresent && Boolean(selected[candidate.keyword])}
                  disabled={candidate.alreadyPresent}
                  onChange={() =>
                    setSelected(prev => ({ ...prev, [candidate.keyword]: !prev[candidate.keyword] }))
                  }
                />
                <span>{candidate.keyword}</span>
                {candidate.alreadyPresent && <span className="text-[10px]">已有</span>}
              </label>
            ))}
          </div>
          <Button
            type="button"
            onClick={handleApply}
            disabled={selectedNewCount === 0}
            variant="primary"
            className="mt-2.5 min-h-0 px-3 py-1.5 text-xs font-medium"
          >
            加入 {selectedNewCount} 个关键词
          </Button>
        </div>
      )}
    </div>
  );
}
