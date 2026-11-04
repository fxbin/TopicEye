'use client';

import React, { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleAlert, Info, Loader2, Sparkles, SpellCheck, Trash2 } from 'lucide-react';
import { contentCheckApi } from '@/lib/api';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { ErrorState } from '@/components/StateView';
import { HighlightText, type HighlightHit } from './_highlight';
import { scanPhase } from './_scan-state';
import {
  AI_TRACE_LEVEL_META,
  AI_TRACE_WORD_DIMENSION_LABELS,
  SENSITIVE_CATEGORY_META,
  SENSITIVE_SEVERITY_LABELS,
  type AiTraceLevel,
  type AiTracesReport,
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

/** 一次检测的两类结果：同一批请求、同一文稿快照，一起成败、一起过期。 */
interface ScanResults {
  sensitive: SensitiveCheckResponse;
  aiTraces: AiTracesReport;
}

export default function ContentCheckPage() {
  const [text, setText] = useState('');
  const [scanning, setScanning] = useState(false);
  const [results, setResults] = useState<ScanResults | null>(null);
  /** 结果对应的文稿快照：编辑后 phase 变 stale，旧结论与旧偏移不再展示 */
  const [scannedText, setScannedText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const phase = scanPhase(scannedText, text, results);
  const current = phase.kind === 'current' ? phase.result : null;

  const stats = useMemo(() => {
    if (!current) return null;
    const byCategory = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0])) as Record<SensitiveCategory, number>;
    const bySeverity = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0])) as Record<SensitiveSeverity, number>;
    for (const hit of current.sensitive.hits) {
      byCategory[hit.category] += 1;
      bySeverity[hit.severity] += 1;
    }
    return { byCategory, bySeverity };
  }, [current]);

  /** 风险命中 + AI 痕迹命中合并渲染：红色系为风险，紫色系为写作建议。 */
  const mergedHits = useMemo<HighlightHit[]>(() => {
    if (!current) return [];
    return [...current.sensitive.hits, ...current.aiTraces.hits];
  }, [current]);

  const overLimit = text.length > MAX_TEXT_LENGTH;
  const canScan = !scanning && text.trim().length > 0 && !overLimit;

  async function handleScan() {
    setScanning(true);
    setError(null);
    try {
      const [sensitive, aiTraces] = await Promise.all([
        contentCheckApi.checkSensitive(text),
        contentCheckApi.checkAiTraces(text),
      ]);
      setResults({ sensitive, aiTraces });
      setScannedText(text);
    } catch (err) {
      setResults(null);
      setScannedText(null);
      setError(err instanceof Error ? err.message : '检测失败，请稍后重试');
    } finally {
      setScanning(false);
    }
  }

  function handleClear() {
    setText('');
    setResults(null);
    setScannedText(null);
    setError(null);
  }

  const sensitiveTotal = current?.sensitive.total ?? 0;
  const hasAnyHit = mergedHits.length > 0;

  return (
    <div className="workspace-scroll">
      <div className="mb-6">
        <h1 className="page-title mb-1.5 text-gray-900">文稿检测</h1>
        <p className="max-w-[760px] text-[13px] leading-6 text-gray-500">
          发布前粘贴文稿，检测广告法极限词、高危违禁词与平台限流词；另附 AI 痕迹启发式统计
          （AI 高频词、套话连接词、句式节奏），仅供改稿参考。命中原文高亮显示，悬停查看建议；
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
              <Button variant="ghost" onClick={handleClear} disabled={scanning || (!text && !results)}>
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
          {phase.kind === 'current' && current && stats ? (
            <>
              <Panel className="p-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-xs font-black text-gray-500">命中总数</span>
                  <span className={cx('font-mono text-2xl font-black', stats.bySeverity.high ? 'text-red-600' : 'text-teal')}>
                    {current.sensitive.total}
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

              <AiTracesPanel report={current.aiTraces} />
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
                <li>· AI 痕迹：启发式统计 AI 高频词、套话连接词与句式节奏，仅供改稿参考；</li>
                <li>· 命中按原文字符偏移高亮，悬停词条查看建议。</li>
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
            ) : sensitiveTotal === 0 ? (
              // 风险把关结论只看违禁词：AI 痕迹是写作建议，不影响「可以发布」
              <span className="flex items-center gap-1.5 text-xs font-bold text-teal">
                <CheckCircle2 size={14} />
                未发现违禁词，可以发布
              </span>
            ) : (
              <span className="text-xs text-gray-400">悬停高亮词查看分类与建议</span>
            )}
          </div>
          {phase.kind === 'stale' ? (
            <p className="text-[14px] leading-7 text-gray-400">{text}</p>
          ) : !hasAnyHit ? (
            <p className="text-[14px] leading-7 text-gray-500">{text}</p>
          ) : (
            <HighlightText text={text} hits={mergedHits} />
          )}
        </Panel>
      )}
    </div>
  );
}

/** AI 痕迹面板：三子指标 + 分档 + 综合建议，全口径标注「启发式统计」。 */
function AiTracesPanel({ report }: { report: AiTracesReport }) {
  const levelMeta = AI_TRACE_LEVEL_META[report.level];
  const rows: Array<{ key: string; label: string; detail: string; level: AiTraceLevel }> = [
    {
      key: 'buzzword',
      label: AI_TRACE_WORD_DIMENSION_LABELS.buzzword,
      detail: `${report.buzzword.hits} 处 · ${report.buzzword.density_per_kilochar} 次/千字`,
      level: report.buzzword.level,
    },
    {
      key: 'connective',
      label: AI_TRACE_WORD_DIMENSION_LABELS.connective,
      detail: `${report.connective.hits} 处 · ${report.connective.density_per_kilochar} 次/千字`,
      level: report.connective.level,
    },
    {
      key: 'rhythm',
      label: '句式节奏',
      detail:
        report.rhythm.cv === null
          ? `${report.rhythm.sentence_count} 句 · 样本不足`
          : `CV ${report.rhythm.cv} · ${report.rhythm.sentence_count} 句`,
      level: report.rhythm.level,
    },
  ];

  return (
    <Panel className="p-4">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-sm font-black text-gray-900">
          <Sparkles size={14} className="text-purple" />
          AI 痕迹
        </span>
        <Badge tone={levelMeta.badgeTone} className="rounded-sm">
          {levelMeta.label}
        </Badge>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-gray-500">
        启发式统计写作风格信号，不代表文稿来源判定。
      </p>
      <div className="mt-3 grid gap-1.5 text-[13px]">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center justify-between gap-2">
            <span className="font-bold text-gray-700">{row.label}</span>
            <span className="flex items-center gap-2">
              <span className="font-mono text-xs text-gray-400">{row.detail}</span>
              <span className={cx('font-black', AI_TRACE_LEVEL_META[row.level].text)}>
                {AI_TRACE_LEVEL_META[row.level].label}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 border-t border-gray-100 pt-2.5 text-xs leading-5 text-gray-500">{report.advice}</p>
    </Panel>
  );
}
