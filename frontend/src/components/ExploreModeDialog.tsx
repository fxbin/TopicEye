'use client';

import React, { useState, useCallback } from 'react';
import { ArrowRight, Compass, HelpCircle, Lightbulb, Loader2, Target, X, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { creationApi } from '@/lib/api';
import { Button, Panel, cx } from '@/components/ui';
import CreationPlanDisplay, { type CreationPlan } from '@/components/CreationPlanDisplay';
import { useDialogFocus } from '@/components/useDialogFocus';

// ── Types ────────────────────────────────────────────────────────────

interface Assumption {
  assumption: string;
  challenge: string;
  direction: string;
  unique_value: string;
  pitfall: string;
}

interface ExploreResult {
  assumptions: Assumption[];
  _meta?: { content_id: number; phase: string };
  error?: string;
}

interface FocusResult {
  question: string;
  dimension: string;
  round: number;
  can_converge: boolean;
  reason: string;
  _meta?: { content_id: number; phase: string };
  error?: string;
}

interface QAPair {
  question: string;
  user_answer: string;
}

type Step = 'idle' | 'exploring' | 'choosing' | 'focusing' | 'converging' | 'done';

// ── Platform config ──────────────────────────────────────────────────

const PLATFORMS: Array<{ id: string; name: string; icon: LucideIcon }> = [
  { id: 'xiaohongshu', name: '小红书', icon: Lightbulb },
  { id: 'wechat', name: '公众号', icon: ArrowRight },
  { id: 'short_video', name: '短视频', icon: Zap },
];

// ── Component ─────────────────────────────────────────────────────────

interface ExploreModeDialogProps {
  contentId: number;
  onClose: () => void;
}

export default function ExploreModeDialog({ contentId, onClose }: ExploreModeDialogProps) {
  const { dialogRef, onKeyDown } = useDialogFocus<HTMLDivElement>(true, onClose);
  const [step, setStep] = useState<Step>('idle');
  const [error, setError] = useState<string | null>(null);

  // Explore state
  const [assumptions, setAssumptions] = useState<Assumption[]>([]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  // Focus state
  const [focusQa, setFocusQa] = useState<QAPair[]>([]);
  const [currentQuestion, setCurrentQuestion] = useState<string>('');
  const [currentDimension, setCurrentDimension] = useState<string>('');
  const [focusRound, setFocusRound] = useState(1);
  const [canConverge, setCanConverge] = useState(false);
  const [userAnswer, setUserAnswer] = useState('');
  const [userRedirect, setUserRedirect] = useState('');

  // Converge state
  const [platform, setPlatform] = useState<string | null>(null);
  const [finalPlan, setFinalPlan] = useState<CreationPlan | null>(null);

  // ── Step 1: Explore ────────────────────────────────────────────────

  const handleExplore = useCallback(async () => {
    setStep('exploring');
    setError(null);
    try {
      const result = (await creationApi.exploreDirections(contentId)) as unknown as ExploreResult;
      if (result.error) {
        setError(result.error);
        setStep('idle');
        return;
      }
      if (!result.assumptions || result.assumptions.length === 0) {
        setError('AI 未返回有效方向，请重试');
        setStep('idle');
        return;
      }
      setAssumptions(result.assumptions);
      setStep('choosing');
    } catch (err) {
      setError(err instanceof Error ? err.message : '探索失败');
      setStep('idle');
    }
  }, [contentId]);

  // ── Step 2: Focus ──────────────────────────────────────────────────

  const handleSelectDirection = useCallback(async (idx: number) => {
    setSelectedIdx(idx);
    setStep('focusing');
    setError(null);
    setFocusQa([]);
    setFocusRound(1);
    setCanConverge(false);

    const selected = assumptions[idx];
    try {
      const result = (await creationApi.focusQuestions({
        content_id: contentId,
        selected_direction: selected.direction,
        unique_value: selected.unique_value,
        pitfall: selected.pitfall,
        focus_round: 1,
      })) as unknown as FocusResult;

      if (result.error) {
        setError(result.error);
        setStep('choosing');
        return;
      }
      setCurrentQuestion(result.question);
      setCurrentDimension(result.dimension);
      setCanConverge(result.can_converge);
    } catch (err) {
      setError(err instanceof Error ? err.message : '追问失败');
      setStep('choosing');
    }
  }, [contentId, assumptions]);

  const handleSubmitAnswer = useCallback(async () => {
    if (!userAnswer.trim() || selectedIdx === null) return;
    const selected = assumptions[selectedIdx];
    const newQa: QAPair = { question: currentQuestion, user_answer: userAnswer };
    const updatedQa = [...focusQa, newQa];
    setFocusQa(updatedQa);
    setUserAnswer('');

    const nextRound = focusRound + 1;
    try {
      const result = (await creationApi.focusQuestions({
        content_id: contentId,
        selected_direction: selected.direction,
        unique_value: selected.unique_value,
        pitfall: selected.pitfall,
        focus_round: nextRound,
        previous_qa: updatedQa as unknown as Array<Record<string, unknown>>,
        user_redirect: userRedirect.trim() || undefined,
      })) as unknown as FocusResult;

      if (result.error) {
        setError(result.error);
        return;
      }
      setUserRedirect('');
      setCurrentQuestion(result.question);
      setCurrentDimension(result.dimension);
      setFocusRound(nextRound);
      setCanConverge(result.can_converge);
    } catch (err) {
      setError(err instanceof Error ? err.message : '追问失败');
    }
  }, [userAnswer, userRedirect, selectedIdx, assumptions, contentId, currentQuestion, focusQa, focusRound]);

  // ── Step 3: Converge ───────────────────────────────────────────────

  const handleConverge = useCallback(async (plat: string) => {
    if (selectedIdx === null) return;
    setPlatform(plat);
    setStep('converging');
    setError(null);

    const selected = assumptions[selectedIdx];
    try {
      const result = (await creationApi.convergePlan({
        content_id: contentId,
        platform: plat,
        selected_direction: selected.direction,
        focus_answers: focusQa as unknown as Array<Record<string, unknown>>,
      })) as unknown as CreationPlan & { error?: string };

      if (result.error) {
        setError(result.error);
        setStep('focusing');
        return;
      }
      setFinalPlan(result);
      setStep('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : '方案生成失败');
      setStep('focusing');
    }
  }, [selectedIdx, assumptions, contentId, focusQa]);

  // ── Render ─────────────────────────────────────────────────────────

  const isLoading = step === 'exploring' || step === 'converging';
  const selected = selectedIdx !== null ? assumptions[selectedIdx] : null;

  return (
    <>
      <div aria-hidden="true" onClick={onClose} className="fixed inset-0 z-[999] bg-black/20" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="explore-mode-dialog-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="fixed inset-x-4 top-1/2 z-[1000] max-h-[85vh] w-auto max-w-2xl -translate-y-1/2 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-xl md:left-1/2 md:-translate-x-1/2"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <Compass size={16} className="text-primary" />
            <span id="explore-mode-dialog-title" className="text-sm font-bold text-gray-900">探索模式</span>
            <StepIndicator step={step} />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="关闭探索模式"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          {error && (
            <div className="mb-3 rounded bg-red-light px-3 py-2 text-[13px] text-red">
              {error}
            </div>
          )}

          {/* Step 0: idle — start button */}
          {step === 'idle' && (
            <div className="py-6 text-center">
              <p className="mb-4 text-[13px] text-gray-500">
                AI 先挑战常见假设，生成差异化创作方向，再逐轮追问帮你把模糊直觉变成可操作方案。
              </p>
              <Button type="button" variant="primary" onClick={handleExplore}>
                <Compass size={14} />
                开始探索
              </Button>
            </div>
          )}

          {/* Step 1: exploring — loading */}
          {step === 'exploring' && (
            <div className="py-8 text-center text-[13px] text-gray-400">
              <Loader2 size={24} className="mx-auto mb-3 animate-spin" />
              正在挑战领域假设，生成创作方向...
            </div>
          )}

          {/* Step 1b: choosing — show directions */}
          {step === 'choosing' && assumptions.length > 0 && (
            <div>
              <SectionLabel icon={Lightbulb}>选择一个方向</SectionLabel>
              <div className="space-y-2.5">
                {assumptions.map((a, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => handleSelectDirection(i)}
                    className={cx(
                      'w-full rounded-md border p-3 text-left transition hover:border-primary',
                      i === selectedIdx ? 'border-primary bg-primary-light/40' : 'border-gray-200 bg-white',
                    )}
                  >
                    <div className="mb-1 text-[13px] font-bold text-gray-900">{a.direction}</div>
                    <div className="space-y-0.5 text-[11px] text-gray-500">
                      <div><span className="font-semibold text-gray-600">假设：</span>{a.assumption}</div>
                      <div><span className="font-semibold text-gray-600">挑战：</span>{a.challenge}</div>
                      <div><span className="font-semibold text-teal-text">价值：</span>{a.unique_value}</div>
                      <div><span className="font-semibold text-red">陷阱：</span>{a.pitfall}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: focusing — Socratic Q&A */}
          {step === 'focusing' && selected && (
            <div>
              <SectionLabel icon={HelpCircle}>
                追问 · 第 {focusRound} 轮 · {dimensionLabel(currentDimension)}
              </SectionLabel>

              {/* Previous Q&A history */}
              {focusQa.length > 0 && (
                <div className="mb-3 space-y-1.5">
                  {focusQa.map((qa, i) => (
                    <div key={i} className="rounded bg-gray-50 px-2.5 py-1.5 text-[12px]">
                      <div className="text-gray-500">Q：{qa.question}</div>
                      <div className="text-gray-800">A：{qa.user_answer}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Current question */}
              <div className="mb-3 rounded-md border border-primary-border bg-primary-light/30 px-3 py-2.5">
                <div className="text-[13px] font-semibold text-gray-900">{currentQuestion}</div>
              </div>

              {/* Answer input */}
              <textarea
                value={userAnswer}
                onChange={(e) => setUserAnswer(e.target.value)}
                placeholder="输入你的回答..."
                rows={2}
                className="mb-2 w-full resize-none rounded border border-gray-200 px-3 py-2 text-[13px] focus:border-primary outline-none"
              />

              {/* Redirect input */}
              <input
                value={userRedirect}
                onChange={(e) => setUserRedirect(e.target.value)}
                placeholder="（可选）方向不对？在这里说你想换的方向"
                className="mb-3 w-full rounded border border-gray-200 px-3 py-1.5 text-[12px] text-gray-500 focus:border-primary outline-none"
              />

              <div className="flex items-center justify-between">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleSubmitAnswer}
                  disabled={!userAnswer.trim()}
                  className="text-[13px]"
                >
                  <ArrowRight size={13} />
                  提交回答
                </Button>
                {canConverge && (
                  <span className="text-[12px] font-semibold text-teal-text">
                    ✓ 可以生成方案了
                  </span>
                )}
              </div>

              {/* Converge: platform selection */}
              {canConverge && (
                <div className="mt-4 border-t border-gray-100 pt-3">
                  <SectionLabel icon={Target}>选择平台，生成方案</SectionLabel>
                  <div className="flex gap-2">
                    {PLATFORMS.map((p) => {
                      const Icon = p.icon;
                      return (
                        <Button
                          key={p.id}
                          type="button"
                          variant="primary"
                          onClick={() => handleConverge(p.id)}
                          className="flex-1 text-[13px]"
                        >
                          <Icon size={13} />
                          {p.name}
                        </Button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 3: converging — loading */}
          {step === 'converging' && (
            <div className="py-8 text-center text-[13px] text-gray-400">
              <Loader2 size={24} className="mx-auto mb-3 animate-spin" />
              正在生成带置信度标注的创作方案...
            </div>
          )}

          {/* Step 4: done — show plan */}
          {step === 'done' && finalPlan && (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <span className="rounded bg-teal-light px-2 py-0.5 text-[11px] font-bold text-teal-text">
                  探索模式 · 完成
                </span>
                {platform && (
                  <span className="text-[12px] text-gray-500">
                    平台：{PLATFORMS.find((p) => p.id === platform)?.name || platform}
                  </span>
                )}
              </div>
              <CreationPlanDisplay plan={finalPlan} platform={platform || ''} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────

function StepIndicator({ step }: { step: Step }) {
  const steps: Array<{ key: Step; label: string }> = [
    { key: 'exploring', label: '探索' },
    { key: 'focusing', label: '聚焦' },
    { key: 'converging', label: '收敛' },
  ];
  const activeIdx = steps.findIndex((s) => s.key === step || (step === 'choosing' && s.key === 'exploring') || (step === 'done' && s.key === 'converging'));

  return (
    <span className="ml-2 inline-flex items-center gap-1">
      {steps.map((s, i) => (
        <React.Fragment key={s.key}>
          <span
            className={cx(
              'text-[11px] font-semibold',
              i <= activeIdx ? 'text-primary' : 'text-gray-300',
            )}
          >
            {s.label}
          </span>
          {i < steps.length - 1 && <span className="text-gray-200">→</span>}
        </React.Fragment>
      ))}
    </span>
  );
}

function SectionLabel({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-[12px] font-bold text-gray-700">
      <Icon size={13} className="text-primary" />
      {children}
    </div>
  );
}

function dimensionLabel(dim: string): string {
  const labels: Record<string, string> = {
    audience: '目标受众',
    conflict: '核心冲突',
    differentiation: '差异化',
  };
  return labels[dim] || dim;
}
