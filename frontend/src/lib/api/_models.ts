/**
 * _models API objects extracted from lib/api.ts.
 * Uses request from ./_core.
 */

import { request } from './_core';
import type { EvalResult, EvalRun, LlmModelCreatePayload, LlmModelItem, LlmModelPresetCatalog, LlmModelPresetItem, ModelUsageSummary, MyLlmModelsResponse } from '@/types/models';

// ─── LLM Models API ───

export const modelsApi = {
  list(): Promise<{ models: LlmModelItem[]; total: number }> {
    return request('/models');
  },
  mine(): Promise<MyLlmModelsResponse> {
    return request('/models/me');
  },
  presets(): Promise<LlmModelPresetCatalog> {
    return request('/models/presets');
  },
  usageSummary(days = 30): Promise<ModelUsageSummary> {
    return request(`/models/usage/summary?days=${days}`);
  },
  create(data: LlmModelCreatePayload): Promise<{ id: number; name: string; message: string }> {
    return request('/models', { method: 'POST', body: JSON.stringify(data) });
  },
  update(id: number, data: Partial<LlmModelItem> & { api_key?: string }): Promise<{ message: string }> {
    return request(`/models/${id}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  delete(id: number): Promise<{ message: string }> {
    return request(`/models/${id}`, { method: 'DELETE' });
  },
  createMine(data: LlmModelCreatePayload): Promise<{ id: number; name: string; message: string }> {
    return request('/models/me', { method: 'POST', body: JSON.stringify(data) });
  },
  updateMine(id: number, data: Partial<LlmModelItem> & { api_key?: string }): Promise<{ message: string }> {
    return request(`/models/me/${id}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  deleteMine(id: number): Promise<{ message: string }> {
    return request(`/models/me/${id}`, { method: 'DELETE' });
  },
  test(id: number): Promise<{ status: string; model_name: string; response?: string; error?: string; duration_ms: number; tokens_input?: number; tokens_output?: number; cache_read_tokens?: number; cache_creation_tokens?: number }> {
    return request(`/models/${id}/test`, { method: 'POST' });
  },
  runEvaluation(data: { model_ids: number[]; prompt_type: string; custom_prompt?: string; sample_content?: string }): Promise<{ eval_run_id: string; model_count: number; message: string }> {
    return request('/models/evaluations/run', { method: 'POST', body: JSON.stringify(data) });
  },
  listEvalRuns(limit?: number): Promise<{ runs: EvalRun[]; total: number }> {
    const qs = limit ? `?limit=${limit}` : '';
    return request(`/models/evaluations/runs${qs}`);
  },
  getEvalRun(runId: string): Promise<{ eval_run_id: string; prompt_type: string; results: EvalResult[] }> {
    return request(`/models/evaluations/runs/${runId}`);
  },
  scoreEvaluation(evalId: number, quality_score: number, notes?: string): Promise<{ message: string }> {
    return request(`/models/evaluations/${evalId}/score`, { method: 'PUT', body: JSON.stringify({ quality_score, notes }) });
  },
};
