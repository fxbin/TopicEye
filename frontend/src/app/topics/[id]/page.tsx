'use client';

import React, { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import { LEVEL_CONFIG } from '@/lib/design-tokens';
import { useAppContext } from '@/components/ClientLayout';
import { contentsApi, analysesApi } from '@/lib/api';
import { Button, Panel } from '@/components/ui';
import { useContentFavoriteStates } from '@/hooks/useContentFavoriteStates';
import type { ContentItem, ContentAnalysis, RecommendLevel } from '@/types';
import { explainRecommendation } from '@/lib/recommendation';
import { timeAgo, extractTags, extractCreatorAngles, extractRiskNotes, extractTitleSuggestions, extractKeyPoints } from '@/lib/utils';
import SectionTitle from '@/components/SectionTitle';
import ScoreCard from '@/components/ScoreCard';
import TopicHeaderCard from '@/components/TopicHeaderCard';
import TopicCreationGenerator from '@/components/TopicCreationGenerator';

// ── Page Component ──

export default function TopicDetailPage() {
  const router = useRouter();
  const params = useParams();
  const { favoritePendingIds, toggleFavorite } = useAppContext();

  const [item, setItem] = useState<ContentItem | null>(null);
  const [analysis, setAnalysis] = useState<ContentAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const contentId = Number(params.id);
  const contentFavoriteState = useContentFavoriteStates(Number.isFinite(contentId) ? [contentId] : []);

  // Fetch content + analysis
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      setLoading(true);
      setError(null);
      setItem(null);
      setAnalysis(null);

      try {
        const content = await contentsApi.get(contentId);
        if (cancelled) return;
        setItem(content);

        if (content.analysis) {
          setAnalysis(content.analysis);
        } else {
          try {
            const a = await analysesApi.getAnalysis(contentId);
            if (!cancelled) setAnalysis(a);
          } catch {
            // No analysis yet
          }
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : '加载失败';
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    if (Number.isInteger(contentId) && contentId > 0) {
      fetchData();
    } else {
      setError('内容编号无效');
      setLoading(false);
    }

    return () => { cancelled = true; };
  }, [contentId]);

  // Handlers
  const isFav = item ? contentFavoriteState.isFavorited(item.id) : false;
  const favoritePending = item ? favoritePendingIds.has(item.id) : false;

  const handleToggleFavorite = async () => {
    if (!item || favoritePending) return;
    try {
      const isFavorited = await toggleFavorite(item.id, { throwOnError: true });
      setItem(prev => prev ? { ...prev, is_favorited: isFavorited } : prev);
      contentFavoriteState.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '收藏状态更新失败');
    }
  };

  // ── Render: Loading ──
  if (loading) {
    return (
      <div className="h-full overflow-y-auto px-4 py-6 sm:px-8 sm:py-8 lg:px-10">
        <div className="max-w-[760px]">
          <Panel className="mb-5 p-8">
            <div className="mb-4 flex gap-2.5">
              <div className="h-6 w-20 rounded-full bg-gray-100" />
              <div className="h-6 w-12 rounded bg-gray-100" />
            </div>
            <div className="mb-3 h-7 w-4/5 rounded-xs bg-gray-100" />
            <div className="mb-3 h-7 w-3/5 rounded-xs bg-gray-100" />
            <div className="flex gap-4">
              <div className="h-4 w-[60px] rounded bg-gray-100" />
              <div className="h-4 w-20 rounded bg-gray-100" />
            </div>
          </Panel>
          {[1, 2, 3].map(i => (
            <Panel key={i} className="mb-5 p-7">
              <div className="mb-4 h-4 w-[30%] rounded bg-gray-100" />
              <div className="mb-2 h-3.5 w-full rounded bg-gray-50" />
              <div className="mb-2 h-3.5 w-[90%] rounded bg-gray-50" />
              <div className="h-3.5 w-3/4 rounded bg-gray-50" />
            </Panel>
          ))}
          <div className="mt-5 text-center text-[13px] text-gray-400">
            加载中...
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Error ──
  if (error || !item) {
    return (
      <div className="h-full overflow-y-auto px-4 py-6 sm:px-8 sm:py-8 lg:px-10">
        <div className="max-w-[760px]">
          <Button
            type="button"
            onClick={() => router.push('/')}
            variant="ghost"
            className="mb-6 min-h-0 px-0 py-1 text-[13px]"
          >
            <ArrowLeft size={15} strokeWidth={2} /> 返回
          </Button>
          <Panel className="border-red/20 bg-red-light p-8 text-center">
            <AlertTriangle size={34} className="mx-auto mb-3 text-red" strokeWidth={1.9} />
            <div className="mb-2 text-base font-semibold text-gray-800">
              内容加载失败
            </div>
            <div className="mb-5 text-sm text-gray-500">
              {error || '未找到该内容'}
            </div>
            <Button
              type="button"
              onClick={() => window.location.reload()}
              variant="secondary"
              className="text-[13px] font-medium"
            >
              重新加载
            </Button>
          </Panel>
        </div>
      </div>
    );
  }

  // ── Derived data ──
  const tags = extractTags(item, analysis);
  const recommendation = explainRecommendation(analysis);
  const level: RecommendLevel = recommendation.level;
  const levelCfg = LEVEL_CONFIG[level] || LEVEL_CONFIG['不建议追'];
  const angles = extractCreatorAngles(analysis);
  const riskNotes = extractRiskNotes(analysis);
  const titleSuggestions = extractTitleSuggestions(analysis);
  const keyPoints = extractKeyPoints(analysis);

  return (
    <div className="fade-in h-full overflow-y-auto px-4 py-6 sm:px-8 sm:py-8 lg:px-10">
      {/* Back */}
      <Button
        type="button"
        onClick={() => router.push('/')}
        variant="ghost"
        className="mb-6 min-h-0 px-0 py-1 text-[13px]"
      >
        <ArrowLeft size={15} strokeWidth={2} /> 返回今日选题
      </Button>

      <div className="max-w-[760px]">
        {/* Header Card */}
        <TopicHeaderCard
          item={item}
          analysis={analysis}
          level={level}
          tags={tags}
          isFav={isFav}
          favoritePending={favoritePending}
          onToggleFavorite={handleToggleFavorite}
          timeAgoStr={item.published_at ? timeAgo(item.published_at) : ''}
        />

        {/* Scores */}
        {analysis && (
          <Panel className="mb-5 p-7">
            <SectionTitle>评分概览</SectionTitle>
            <div className="grid gap-6 sm:grid-cols-3">
              <ScoreCard label="热度分" value={analysis.hot_score ?? 0} desc="当前传播热度" />
              <ScoreCard label="创作价值" value={analysis.creator_score ?? 0} desc="值得创作的程度" />
              <ScoreCard label="风险分" value={analysis.risk_score ?? 0} desc="内容风险等级" isRisk />
            </div>

            {/* Curation score bar */}
            {analysis.curation_score != null && analysis.curation_score > 0 && (
              <div className="mt-5 border-t border-gray-100 pt-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-500">精选评分</span>
                  <span className="font-mono text-xs font-semibold text-primary">
                    {Math.round(analysis.curation_score)} 分
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-gray-100">
                  <div
                    style={{
                      height: '100%',
                      width: `${Math.min(100, analysis.curation_score)}%`,
                    }}
                    className="rounded-full bg-primary transition-[width] duration-500"
                  />
                </div>
              </div>
            )}
          </Panel>
        )}

        {/* AI Summary */}
        {analysis?.summary && (
          <Panel className="mb-5 p-7">
            <SectionTitle>AI 摘要</SectionTitle>
            <p className="text-sm leading-8 text-gray-600">{analysis.summary}</p>
          </Panel>
        )}

        {/* Key Points */}
        {keyPoints.length > 0 && (
          <Panel className="mb-5 p-7">
            <SectionTitle>核心要点</SectionTitle>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {keyPoints.map((point, i) => (
                <li key={i} className="flex items-start gap-2 text-sm leading-6 text-gray-700">
                  <span className="shrink-0 font-bold text-primary">•</span>
                  {point}
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {/* Recommendation Reason */}
        {analysis?.recommended_reason && (
          <Panel className="mb-5 p-7" style={{ background: levelCfg.bg, borderColor: levelCfg.border }}>
            <SectionTitle>推荐理由</SectionTitle>
            <p className="text-sm leading-8 text-gray-700">{analysis.recommended_reason}</p>
          </Panel>
        )}

        <Panel className="mb-5 p-7">
          <SectionTitle>算法判断</SectionTitle>
          <p className="text-sm leading-8 text-gray-700">{recommendation.reason}</p>
          {recommendation.signals.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {recommendation.signals.map((signal) => (
                <span key={signal} className="rounded-sm bg-gray-100 px-2.5 py-1 text-xs font-bold text-gray-500">
                  {signal}
                </span>
              ))}
            </div>
          )}
        </Panel>

        {/* Creator Angles */}
        {angles.length > 0 && (
          <Panel className="mb-5 p-7">
            <SectionTitle>可切入角度</SectionTitle>
            <div className="flex flex-col gap-2.5">
              {angles.map((angle, i) => (
                <div key={i} className="flex items-start gap-3 rounded-sm bg-gray-50 px-4 py-3">
                  <span className="mt-px flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-white">
                    {i + 1}
                  </span>
                  <span className="text-sm leading-6 text-gray-700">{angle}</span>
                </div>
              ))}
            </div>
          </Panel>
        )}

        {/* Title Suggestions */}
        {titleSuggestions.length > 0 && (
          <Panel className="mb-5 p-7">
            <SectionTitle>备选标题建议</SectionTitle>
            <div className="flex flex-col gap-2">
              {titleSuggestions.map((title, i) => (
                <div key={i} className="rounded-sm border-l-[3px] border-primary bg-gray-50 px-3.5 py-2.5 text-sm leading-6 text-gray-700">
                  {title}
                </div>
              ))}
            </div>
          </Panel>
        )}

        {/* Risk Notes */}
        {riskNotes.length > 0 && (
          <Panel className="mb-5 border-red/20 bg-red-light p-7">
            <SectionTitle>风险提示</SectionTitle>
            <ul className="flex list-none flex-col gap-2">
              {riskNotes.map((note, i) => (
                <li key={i} className="flex items-start gap-2 text-[13px] leading-6 text-red">
                  <span className="shrink-0 font-bold text-red">!</span>
                  {note}
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {/* Creation Plan Generator */}
        {analysis && <TopicCreationGenerator key={contentId} contentId={contentId} />}

        {/* No analysis hint */}
        {!analysis && (
          <Panel className="mb-5 border-amber-border bg-amber-light p-7">
            <SectionTitle>AI 分析</SectionTitle>
            <p className="text-sm leading-8 text-gray-600">
              该内容尚未完成 AI 分析。评分、摘要和创作建议将在分析完成后显示。
            </p>
          </Panel>
        )}

        {/* Spacer at bottom */}
        <div className="h-10" />
      </div>
    </div>
  );
}
