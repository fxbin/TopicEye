'use client';

import React, { useState } from 'react';
import { BookOpen, Loader2, PenLine, Video, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { creationApi } from '@/lib/api';
import { Button, Panel } from '@/components/ui';
import type { ContentAnalysis } from '@/types';
import CreationPlanDisplay from '@/components/CreationPlanDisplay';
import RelationPanel from '@/components/RelationPanel';

interface AnalysisPanelProps {
  analysis: ContentAnalysis & { _content_id?: number };
  onClose: () => void;
}

export default function AnalysisPanel({ analysis, onClose }: AnalysisPanelProps) {
  const { currentUser } = useAppContext();
  const contentId = analysis.content_id || 0;
  const [creationPlan, setCreationPlan] = useState<Record<string, unknown> | null>(null);
  const [generating, setGenerating] = useState(false);
  const [activePlatform, setActivePlatform] = useState<string | null>(null);
  const platforms: Array<{ id: string; label: string; icon: LucideIcon }> = [
    { id: 'xiaohongshu', label: '小红书图文', icon: BookOpen },
    { id: 'short_video', label: '短视频脚本', icon: Video },
  ];

  const handleGenerate = async (platform: string) => {
    if (!contentId) return;
    setActivePlatform(platform);
    setGenerating(true);
    try {
      const plan = await creationApi.generatePlan(contentId, platform);
      setCreationPlan(plan);
    } catch (err) {
      console.error('Failed to generate plan:', err);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 z-[999] bg-black/20" />
      <div className="fixed bottom-0 right-0 top-0 z-[1000] w-[520px] max-w-[90vw] overflow-y-auto bg-white p-8 shadow-[-4px_0_24px_rgba(0,0,0,0.1)]">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-lg font-bold text-gray-900">AI 分析报告</h2>
          <button type="button" onClick={onClose} className="cursor-pointer border-0 bg-transparent p-1 text-gray-400 hover:text-gray-600" title="关闭">
            <X size={18} strokeWidth={2} />
          </button>
        </div>

        <div className="mb-6">
          <h3 className="mb-3 text-[13px] font-semibold text-gray-700">精选评分</h3>
          {[
            { label: '精选分', value: analysis.curation_score || 0, color: '#FF6B35' },
            { label: '信息密度', value: analysis.info_density || 0, color: '#8B5CF6' },
            { label: '可操作性', value: analysis.actionability || 0, color: '#3B82F6' },
            { label: '来源权威', value: analysis.source_weight || 0, color: '#10B981' },
          ].map((s) => (
            <div key={s.label} className="mb-2 flex items-center gap-2.5">
              <span className="w-16 text-xs text-gray-500">{s.label}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                <div className="h-full rounded-full" style={{ width: `${s.value}%`, background: s.color }} />
              </div>
              <span className="w-6 text-right text-xs font-semibold text-gray-700">{Math.round(s.value || 0)}</span>
            </div>
          ))}
        </div>

        <div className="mb-6">
          <h3 className="mb-3 text-[13px] font-semibold text-gray-700">多维评分</h3>
          {[
            { label: '质量', value: analysis.quality_score, color: '#10B981' },
            { label: '热度', value: analysis.hot_score, color: '#EF4444' },
            { label: '新鲜度', value: analysis.freshness_score, color: '#3B82F6' },
            { label: '创作价值', value: analysis.creator_score, color: '#FF6B35' },
            { label: '爆文潜力', value: analysis.viral_score, color: '#F59E0B' },
            { label: '风险', value: analysis.risk_score, color: '#6B7280' },
          ].map((s) => (
            <div key={s.label} className="mb-2 flex items-center gap-2.5">
              <span className="w-16 text-xs text-gray-500">{s.label}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                <div className="h-full rounded-full" style={{ width: `${s.value}%`, background: s.color }} />
              </div>
              <span className="w-6 text-right text-xs font-semibold text-gray-700">{Math.round(s.value || 0)}</span>
            </div>
          ))}
        </div>

        {analysis.summary && (
          <div className="mb-6">
            <h3 className="mb-2 text-[13px] font-semibold text-gray-700">内容摘要</h3>
            <p className="text-[13px] leading-7 text-gray-600">{analysis.summary}</p>
          </div>
        )}
        {analysis.key_points != null && analysis.key_points.length > 0 && (
          <div className="mb-6">
            <h3 className="mb-2 text-[13px] font-semibold text-gray-700">核心观点</h3>
            {analysis.key_points.map((point, i) => (
              <div key={i} className="mb-2 border-l-[3px] border-primary pl-3">
                <span className="text-[13px] leading-6 text-gray-600">{point}</span>
              </div>
            ))}
          </div>
        )}
        {analysis.creator_angles != null && analysis.creator_angles.length > 0 && (
          <div className="mb-6">
            <h3 className="mb-2 text-[13px] font-semibold text-gray-700">创作角度</h3>
            {analysis.creator_angles.map((angle, i) => (
              <div key={i} className="mb-2 border-l-[3px] border-teal pl-3">
                <span className="text-[13px] leading-6 text-gray-600">{angle}</span>
              </div>
            ))}
          </div>
        )}
        {analysis.title_suggestions != null && analysis.title_suggestions.length > 0 && (
          <div className="mb-6">
            <h3 className="mb-2 text-[13px] font-semibold text-gray-700">建议标题</h3>
            {analysis.title_suggestions.map((title, i) => (
              <div key={i} className="mb-1.5 text-[13px] leading-7 text-gray-600">
                <span className="font-semibold text-primary">{i + 1}.</span> {title}
              </div>
            ))}
          </div>
        )}

        {currentUser && (
          <Panel className="mt-7 border-primary-border/60 bg-primary-light/40 p-5">
            <h3 className="mb-1 flex items-center gap-2 text-sm font-bold text-gray-900">
              <PenLine size={15} strokeWidth={2} />
              生成创作方案
            </h3>
            <p className="mb-3.5 text-xs text-gray-500">基于该内容生成平台专属创作方案</p>

            <div className="mb-4 flex gap-2">
              {platforms.map((p) => {
                const Icon = p.icon;
                const active = activePlatform === p.id && creationPlan;
                return (
                  <Button
                    key={p.id}
                    type="button"
                    onClick={() => handleGenerate(p.id)}
                    disabled={generating}
                    variant={active ? 'primary' : 'secondary'}
                    className="flex-1 px-2 py-2.5 text-xs font-semibold"
                  >
                    <Icon size={14} strokeWidth={2} />
                    {p.label}
                  </Button>
                );
              })}
            </div>

            {generating && (
              <div className="p-6 text-center text-[13px] text-gray-400">
                <Loader2 size={20} strokeWidth={2} className="mx-auto mb-2 animate-spin" />
                创作方案生成中...
              </div>
            )}

            {creationPlan && !generating && (
              <CreationPlanDisplay plan={creationPlan} platform={activePlatform || ''} />
            )}
          </Panel>
        )}

        {/* Related content */}
        {contentId > 0 && (
          <RelationPanel contentId={contentId} />
        )}
      </div>
    </>
  );
}
