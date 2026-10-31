'use client';

import React, { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleAlert, Info, Loader2, SpellCheck, Trash2 } from 'lucide-react';
import { contentCheckApi } from '@/lib/api';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { ErrorState } from '@/components/StateView';
import { HighlightText } from './_highlight';
import { scanPhase } from './_scan-state';
import {
  SENSITIVE_CATEGORY_META,
  SENSITIVE_SEVERITY_LABELS,
  type SensitiveCategory,
  type SensitiveCheckResponse,
  type SensitiveSeverity,
} from '@/types/content-check';

const MAX_TEXT_LENGTH = 20000;

const CATEGORY_ORDER: SensitiveCategory[] = ['advertising_extreme', 'political_adult', 'platform_throttle'];
const SEVERITY_ORDER: SensitiveSeverity[] = ['high', 'medium', 'low'];

const SEVERITY_ICON: Record<SensitiveSeverity, typeof AlertTriangle> = {
  high: AlertTriangle,
  medium: CircleAlert,
  low: Info,
};

const SEVERITY_CLS: Record<SensitiveSeverity, string> = {
  high: 'text-red-600',
  medium: 'text-amber-600',
  low: 'text-gray-500',
};

export default function ContentCheckPage() {
  const [text, setText] = useState('');
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<SensitiveCheckResponse | null>(null);
  /** 结果对应的文稿快照：编辑后 phase 变 stale，旧结论与旧偏移不再展示 */
  const [scannedText, setScannedText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const phase = scanPhase(scannedText, text, result);

  const stats = useMemo(() => {
    if (!result) return null;
    const byCategory = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0])) as Record<SensitiveCategory, number>;
    const bySeverity = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0])) as Record<SensitiveSeverity, number>;
    for (const hit of result.hits) {
      byCategory[hit.category] += 1;
      bySeverity[hit.severity] += 1;
    }
    return { byCategory, bySeverity };
  }, [result]);

  const overLimit = text.length > MAX_TEXT_LENGTH;
  const canScan = !scanning && text.trim().length > 0 && !overLimit;

  async function handleScan() {
    setScanning(true);
    setError(null);
    try {
      const response = await contentCheckApi.checkSensitive(text);
      setResult(response);
      setScannedText(text);
    } catch (err) {
      setResult(null);
      setScannedText(null);
      setError(err instanceof Error ? err.message : '检测失败，请稍后重试');
    } finally {
      setScanning(false);
    }
  }

  function handleClear() {
    setText('');
    setResult(null);
    setScannedText(null);
    setError(null);
  }

  return (
    <div className="fade-in h-full overflow-y-auto px-6 py-6 lg:px-10 lg:py-8">
      <div className="mb-6">
        <div className="mb-3 inline-flex items-center gap-2 rounded-sm border border-primary-border bg-primary-light px-3 py-1.5 text-xs font-black text-primary">
          <SpellCheck size={14} />
          创作工具
        </div>
        <h1 className="mb-1.5 text-[26px] font-black text-gray-900">文稿检测</h1>
        <p className="max-w-[760px] text-[13px] leading-6 text-gray-500">
          发布前粘贴文稿，检测广告法极限词、高危违禁词与平台限流词。命中原文高亮显示，悬停查看替换建议；
          文稿只在本次检测中使用，不落库、不留存。
        </p>
      </div>

      {error && (
        <div className="mb-4">
          <ErrorState error={error} onRetry={() => void handleScan()} panel={false} />
        </div>
      )}

      <div className="grid gap-3 pb-10 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel className="flex min-h-[420px] flex-col p-5">
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setError(null); // 编辑即推翻上次的失败提示；超长提示由本地 overLimit 判定
            }}
            placeholder="把待发布的文稿粘贴到这里（最多 20000 字）……"
            spellCheck={false}
            className={cx(
              'min-h-[300px] w-full flex-1 resize-y rounded-sm border bg-gray-50 p-4 text-[14px] leading-7 text-gray-800 outline-none',
              overLimit ? 'border-red-300 focus:border-red-400' : 'border-gray-200 focus:border-primary-border',
            )}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <div className={cx('font-mono text-xs', overLimit ? 'font-bold text-red-600' : 'text-gray-400')}>
              {text.length} / {MAX_TEXT_LENGTH}
              {overLimit && ' · 超出上限，请删减后再检测'}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={handleClear} disabled={scanning || (!text && !result)}>
                <span className="flex items-center gap-1.5">
                  <Trash2 size={14} />
                  清空
                </span>
              </Button>
              <Button variant="primary" onClick={() => void handleScan()} disabled={!canScan}>
                <span className="flex items-center gap-1.5">
                  {scanning ? <Loader2 size={14} className="animate-spin" /> : <SpellCheck size={14} />}
                  {scanning ? '检测中…' : '开始检测'}
                </span>
              </Button>
            </div>
          </div>
        </Panel>

        <div className="grid content-start gap-3">
          {phase.kind === 'current' && stats ? (
            <>
              <Panel className="p-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-xs font-black text-gray-500">命中总数</span>
                  <span className={cx('font-mono text-2xl font-black', stats.bySeverity.high ? 'text-red-600' : 'text-teal')}>
                    {result?.total ?? 0}
                  </span>
                </div>
                <div className="mt-3 grid gap-1.5">
                  {SEVERITY_ORDER.map((severity) => {
                    const Icon = SEVERITY_ICON[severity];
                    const count = stats.bySeverity[severity];
                    return (
                      <div key={severity} className="flex items-center justify-between text-[13px]">
                        <span className={cx('flex items-center gap-1.5 font-bold', count ? SEVERITY_CLS[severity] : 'text-gray-400')}>
                          <Icon size={14} />
                          {SENSITIVE_SEVERITY_LABELS[severity]}
                        </span>
                        <span className={cx('font-mono font-black', count ? SEVERITY_CLS[severity] : 'text-gray-300')}>{count}</span>
                      </div>
                    );
                  })}
                </div>
              </Panel>

              {CATEGORY_ORDER.map((category) => {
                const meta = SENSITIVE_CATEGORY_META[category];
                const count = stats.byCategory[category];
                return (
                  <Panel key={category} className={cx('p-4', count === 0 && 'opacity-60')}>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-black text-gray-900">{meta.label}</span>
                      <Badge tone={count > 0 ? 'red' : 'teal'} className="rounded-sm">
                        {count > 0 ? `${count} 处` : '未命中'}
                      </Badge>
                    </div>
                    <p className="mt-1.5 text-xs leading-5 text-gray-500">{meta.description}</p>
                  </Panel>
                );
              })}
            </>
          ) : phase.kind === 'stale' ? (
            <Panel className="border-amber-border p-4">
              <div className="mb-1 flex items-center gap-2 text-xs font-black text-amber-600">
                <CircleAlert size={14} />
                结果已过期
              </div>
              <p className="text-xs leading-5 text-gray-500">
                文稿在检测后修改过，当前统计与高亮不再适用，请重新检测后再参考把关结论。
              </p>
            </Panel>
          ) : (
            <Panel className="p-4">
              <div className="mb-1 flex items-center gap-2 text-xs font-black text-gray-500">
                <Info size={14} />
                检测口径
              </div>
              <ul className="grid gap-1.5 text-xs leading-5 text-gray-500">
                <li>· 广告极限词：广告法绝对化用语与极限表述；</li>
                <li>· 高危违禁词：涉政/成人/违法基础词，建议直接删除；</li>
                <li>· 平台限流词：导流与诱导表述，容易触发降权。</li>
                <li>· 命中按原文字符偏移高亮，悬停词条查看替换建议。</li>
              </ul>
            </Panel>
          )}
        </div>
      </div>

      {phase.kind !== 'idle' && (
        <Panel className="mb-10 p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-black text-gray-900">正文高亮</span>
            {phase.kind === 'stale' ? (
              <span className="flex items-center gap-1.5 text-xs font-bold text-amber-600">
                <CircleAlert size={14} />
                文稿已修改，结果过期——请重新检测
              </span>
            ) : phase.result.total === 0 ? (
              <span className="flex items-center gap-1.5 text-xs font-bold text-teal">
                <CheckCircle2 size={14} />
                未发现违禁词，可以发布
              </span>
            ) : (
              <span className="text-xs text-gray-400">悬停高亮词查看分类与替换建议</span>
            )}
          </div>
          {phase.kind === 'stale' ? (
            <p className="text-[14px] leading-7 text-gray-400">{text}</p>
          ) : phase.result.total === 0 ? (
            <p className="text-[14px] leading-7 text-gray-500">{text}</p>
          ) : (
            <HighlightText text={text} hits={phase.result.hits} />
          )}
        </Panel>
      )}
    </div>
  );
}
