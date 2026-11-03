'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAppContext } from '@/components/ClientLayout';
import { analysesApi, contentsApi, feedbackApi, type FeedbackType, type ScoringFlowResponse, type ScoringFlowSample } from '@/lib/api';
import {
  AlgorithmHeader,
  DiagnosticsPanel,
  FlowErrorPanel,
  DecisionOverview,
  MixList,
  PathPanel,
  SampleList,
  SummaryGrid,
} from './components';
import { startContentWorkflow } from '@/lib/workflow';

const DEFAULT_HOURS = 24;
const ANALYSIS_POLL_INTERVAL_MS = 3000;
const ANALYSIS_POLL_MAX_ATTEMPTS = 20;

type FlowFetchOptions = {
  silent?: boolean;
};

type AnalysisPollState = {
  jobId?: string | null;
  queuedIds: Set<number>;
  baselineAnalyzedTotal: number;
  attempts: number;
};

function formatWindow(hours: number) {
  return hours >= 168 ? `${hours / 24} 天` : `${hours} 小时`;
}

export default function AlgorithmPage() {
  const router = useRouter();
  const { currentUser, favorites, favoritePendingIds, toggleFavorite } = useAppContext();
  const [hours, setHours] = useState(DEFAULT_HOURS);
  const [data, setData] = useState<ScoringFlowResponse | null>(null);
  const [selected, setSelected] = useState<ScoringFlowSample | undefined>();
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [feedbacking, setFeedbacking] = useState(false);
  const [createPendingId, setCreatePendingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analysisNotice, setAnalysisNotice] = useState<string | null>(null);
  const requestSeqRef = useRef(0);
  const analysisPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const analysisPollStateRef = useRef<AnalysisPollState | null>(null);
  const scheduleAnalysisPollRef = useRef<((pollState: AnalysisPollState) => void) | null>(null);

  const clearAnalysisPolling = useCallback(() => {
    if (analysisPollTimerRef.current) {
      clearTimeout(analysisPollTimerRef.current);
      analysisPollTimerRef.current = null;
    }
    analysisPollStateRef.current = null;
  }, []);

  const fetchFlow = useCallback(async (options: FlowFetchOptions = {}) => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    if (!options.silent) setLoading(true);
    setError(null);
    try {
      const result = await contentsApi.scoringFlow({ hours, limit: 160 });
      if (requestSeq !== requestSeqRef.current) return;
      setData(result);
      setSelected((prev) => result.samples.find((s) => s.id === prev?.id) || result.samples[0]);
      return result;
    } catch (err) {
      if (requestSeq !== requestSeqRef.current) return;
      setError(err instanceof Error ? err.message : '算法流程加载失败');
      return null;
    } finally {
      if (requestSeq === requestSeqRef.current && !options.silent) setLoading(false);
    }
  }, [hours]);

  useEffect(() => { void fetchFlow(); }, [fetchFlow]);

  useEffect(() => () => {
    clearAnalysisPolling();
  }, [clearAnalysisPolling]);

  const isAnalysisPollingSettled = useCallback((result: ScoringFlowResponse, pollState: AnalysisPollState) => {
    const hasQueuedSample = result.samples.some((sample) => pollState.queuedIds.has(sample.id));
    const analyzedTotal = result.diagnostics?.analyzed_total ?? 0;
    return hasQueuedSample || analyzedTotal > pollState.baselineAnalyzedTotal;
  }, []);

  const scheduleAnalysisPoll = useCallback((pollState: AnalysisPollState) => {
    if (analysisPollTimerRef.current) {
      clearTimeout(analysisPollTimerRef.current);
    }
    analysisPollStateRef.current = pollState;
    analysisPollTimerRef.current = setTimeout(() => {
      analysisPollTimerRef.current = null;
      void (async () => {
        const current = analysisPollStateRef.current;
        if (!current) return;

        if (current.jobId) {
          try {
            const job = await analysesApi.getJob(current.jobId);
            if (job.status === 'SUCCESS' || job.status === 'PARTIAL') {
              clearAnalysisPolling();
              await fetchFlow({ silent: true });
              setAnalysisNotice(
                job.failed_count > 0
                  ? `后台分析已完成 ${job.analyzed_count} 条，${job.failed_count} 条失败或待重试，评分流程已刷新。`
                  : `后台分析完成 ${job.analyzed_count} 条，评分流程已刷新。`
              );
              return;
            }
            if (job.status === 'FAILED' || job.status === 'EXPIRED') {
              clearAnalysisPolling();
              await fetchFlow({ silent: true });
              setAnalysisNotice('后台分析未完成，失败内容会在冷却后自动重试；评分流程已刷新当前状态。');
              return;
            }
          } catch {
            // If the process-local job record is unavailable, fall back to scoring-flow polling below.
          }
        }

        const result = await fetchFlow({ silent: true });
        if (!result) {
          if (current.attempts + 1 >= ANALYSIS_POLL_MAX_ATTEMPTS) {
            clearAnalysisPolling();
            setAnalysisNotice('后台分析仍未完成，请稍后手动刷新评分流程。');
            return;
          }
          scheduleAnalysisPollRef.current?.({ ...current, attempts: current.attempts + 1 });
          return;
        }

        if (isAnalysisPollingSettled(result, current)) {
          clearAnalysisPolling();
          setAnalysisNotice('后台分析完成，评分流程已刷新。');
          return;
        }

        if (current.attempts + 1 >= ANALYSIS_POLL_MAX_ATTEMPTS) {
          clearAnalysisPolling();
          setAnalysisNotice('后台分析耗时较长，已停止自动刷新；稍后可手动刷新评分流程。');
          return;
        }

        scheduleAnalysisPollRef.current?.({ ...current, attempts: current.attempts + 1 });
      })();
    }, ANALYSIS_POLL_INTERVAL_MS);
  }, [clearAnalysisPolling, fetchFlow, isAnalysisPollingSettled]);

  useEffect(() => {
    scheduleAnalysisPollRef.current = scheduleAnalysisPoll;
  }, [scheduleAnalysisPoll]);

  const handleHoursChange = useCallback((nextHours: number) => {
    clearAnalysisPolling();
    setAnalysisNotice(null);
    setHours(nextHours);
  }, [clearAnalysisPolling]);

  const handleAnalyzePending = useCallback(async () => {
    setAnalyzing(true);
    setError(null);
    setAnalysisNotice(null);
    try {
      const baselineAnalyzedTotal = data?.diagnostics?.analyzed_total ?? 0;
      const result = await analysesApi.analyzePending({ limit: 1, hours });
      const queuedCount = result.queued_ids?.length ?? 0;
      const skippedCount = result.skipped_inflight_ids?.length ?? 0;
      const analyzedCount = result.analyzed_ids?.length ?? 0;
      const windowText = formatWindow(hours);
      setAnalysisNotice(
        queuedCount > 0
          ? `已提交最近 ${windowText}内 ${queuedCount} 条内容到后台分析，页面会持续刷新评分流程。`
          : skippedCount > 0
            ? `最近 ${windowText}内 ${skippedCount} 条内容已在后台分析中，页面会继续跟踪刷新。`
          : analyzedCount > 0
            ? `已同步分析最近 ${windowText}内 ${analyzedCount} 条内容，正在刷新评分流程。`
          : '当前窗口没有可分析的待处理内容。'
      );
      const flow = await fetchFlow();
      if (queuedCount > 0 || skippedCount > 0) {
        const pollState = {
          jobId: result.job_id,
          queuedIds: new Set(result.queued_ids || []),
          baselineAnalyzedTotal,
          attempts: 0,
        };
        if (flow && isAnalysisPollingSettled(flow, pollState)) {
          setAnalysisNotice('后台分析完成，评分流程已刷新。');
        } else {
          scheduleAnalysisPoll(pollState);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '最近内容分析失败');
    } finally {
      setAnalyzing(false);
    }
  }, [data, fetchFlow, hours, isAnalysisPollingSettled, scheduleAnalysisPoll]);

  const handleFeedback = useCallback(async (sample: ScoringFlowSample, type: FeedbackType) => {
    setFeedbacking(true);
    setError(null);
    try {
      await feedbackApi.submit(sample.id, type, 'algorithm-flow');
      await fetchFlow();
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈提交失败');
    } finally {
      setFeedbacking(false);
    }
  }, [fetchFlow]);

  const setSampleFavorite = useCallback((id: number, isFavorited: boolean) => {
    setData((prev) => prev ? {
      ...prev,
      samples: prev.samples.map((sample) => (
        sample.id === id ? { ...sample, is_favorited: isFavorited } : sample
      )),
    } : prev);
    setSelected((prev) => prev?.id === id ? { ...prev, is_favorited: isFavorited } : prev);
  }, []);

  const handleFavorite = useCallback(async (sample: ScoringFlowSample) => {
    setError(null);
    try {
      const isFavorited = await toggleFavorite(sample.id, { throwOnError: true });
      setSampleFavorite(sample.id, isFavorited);
    } catch (err) {
      setError(err instanceof Error ? err.message : '收藏操作失败');
    }
  }, [setSampleFavorite, toggleFavorite]);

  const handleCreate = useCallback(async (sample: ScoringFlowSample) => {
    setError(null);
    setCreatePendingId(sample.id);
    try {
      await startContentWorkflow({
        contentId: sample.id,
        title: sample.title,
        isFavorited: favorites.has(sample.id) || Boolean(sample.is_favorited),
        toggleFavorite,
        router,
      });
      setSampleFavorite(sample.id, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '进入创作台失败');
    } finally {
      setCreatePendingId(null);
    }
  }, [favorites, router, setSampleFavorite, toggleFavorite]);

  const selectedForPanel = useMemo(
    () => selected ? { ...selected, is_favorited: selected.is_favorited || favorites.has(selected.id) } : undefined,
    [favorites, selected],
  );

  return (
    <div className="workspace-scroll">
      <div className="mx-auto max-w-[1200px]">
        <AlgorithmHeader
          hours={hours}
          loading={loading}
          onHoursChange={handleHoursChange}
          onRefresh={() => void fetchFlow()}
        />

        {error && data && (
          <div className="mb-4 rounded-sm border border-red/20 bg-red-light px-4 py-3 text-sm text-red">
            刷新失败，当前继续显示上次结果：{error}
          </div>
        )}

        {loading && !data ? (
          <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-400">
            加载算法流程...
          </div>
        ) : error && !data ? (
          <FlowErrorPanel
            message={error}
            loading={loading}
            onRetry={() => void fetchFlow()}
          />
        ) : data ? (
          <>
            <SummaryGrid data={data} />
            <DecisionOverview data={data} />
            <details className="mb-4 rounded-sm border border-gray-200 bg-white p-4" open={!data.scored}>
              <summary className="cursor-pointer text-sm font-medium text-gray-600">数据范围与高级诊断</summary>
              <DiagnosticsPanel
                data={data}
                onHoursChange={handleHoursChange}
                onAnalyzePending={currentUser?.role === 'admin' ? handleAnalyzePending : undefined}
                analyzing={analyzing}
                analysisNotice={analysisNotice}
              />
            </details>

            <div className="mt-4 grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px] 2xl:grid-cols-[240px_minmax(0,1fr)_340px]">
              <div className="order-3 min-w-0 space-y-4 lg:col-start-1 lg:row-start-2 2xl:order-none 2xl:col-start-1 2xl:row-start-1">
                <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-1">
                  <MixList title="类别混排压力" items={data.category_mix} tone="purple" />
                  <MixList title="来源混排压力" items={data.source_mix} tone="teal" />
                </div>
              </div>
              <div className="order-1 min-w-0 lg:col-start-1 lg:row-start-1 2xl:order-none 2xl:col-start-2 2xl:row-start-1">
                <SampleList samples={data.samples} selectedId={selected?.id} onSelect={setSelected} />
              </div>
              <div className="order-2 min-w-0 lg:sticky lg:top-4 lg:col-start-2 lg:row-span-2 lg:row-start-1 2xl:order-none 2xl:col-start-3 2xl:row-start-1">
                <PathPanel
                  sample={selectedForPanel}
                  onFeedback={handleFeedback}
                  onFavorite={handleFavorite}
                  onCreate={handleCreate}
                  feedbacking={feedbacking}
                  favoritePending={selected ? favoritePendingIds.has(selected.id) : false}
                  createPending={selected ? createPendingId === selected.id : false}
                />
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
