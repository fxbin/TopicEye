/**
 * LLM 模型配置、评测与用量统计类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

export interface LlmModelItem {
  id: number;
  owner_user_id?: number | null;
  scope?: string;
  name: string;
  provider: string;
  model_id: string;
  resolved_model: string;
  api_base: string | null;
  api_key_set: boolean;
  enabled: boolean;
  routing_group: string;
  model_family: string | null;
  channel_name: string | null;
  routing_priority: number;
  cooldown_seconds: number;
  temperature: number;
  max_tokens: number;
  requests_per_minute: number;
  description: string | null;
  cost_per_1k_input: number | null;
  cost_per_1k_output: number | null;
  cost_per_1m_input: number | null;
  cost_per_1m_input_cache_hit: number | null;
  cost_per_1m_output: number | null;
  extra_params: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LlmModelPresetItem {
  key: string;
  label: string;
  provider: string;
  model_id: string;
  model_id_placeholder?: string | null;
  api_base?: string | null;
  api_base_placeholder?: string | null;
  model_family?: string | null;
  channel_name?: string | null;
  description: string;
  recommended_for: string[];
  requires: string[];
  help: string;
  defaults: Record<string, unknown>;
}

export interface LlmModelPresetCatalog {
  defaults: Record<string, unknown>;
  parameter_help?: Record<string, {
    label: string;
    default: unknown;
    range?: number[];
    unit?: string;
    recommended?: string;
    plain: string;
    beginner?: string;
    when_to_change?: string[];
  }>;
  presets: LlmModelPresetItem[];
  help: Record<string, string>;
}

export interface MyLlmModelsResponse {
  models: LlmModelItem[];
  total: number;
  custom_ai_allowed: boolean;
}

export type LlmModelCreatePayload = Partial<LlmModelItem> & {
  api_key?: string;
  preset_key?: string;
  cost_per_1m_input?: number | null;
  cost_per_1m_input_cache_hit?: number | null;
  cost_per_1m_output?: number | null;
};

export interface EvalRun {
  eval_run_id: string;
  prompt_type: string;
  model_count: number;
  created_at: string | null;
  done_count: number;
  fail_count: number;
}

export interface EvalResult {
  id: number;
  model_id: number;
  model_name: string;
  status: string;
  response_text: string | null;
  duration_ms: number;
  tokens_input: number | null;
  tokens_output: number | null;
  quality_score: number | null;
  auto_score: number | null;
  notes: string | null;
  error_message: string | null;
  created_at: string | null;
}

export interface ModelUsageBucket {
  calls: number;
  success_calls: number;
  failed_calls: number;
  tokens_input: number;
  tokens_output: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  billable_input_tokens: number;
  estimated_cost: number;
}

export interface ModelUsageByModel extends ModelUsageBucket {
  model_id: number;
  model_name: string;
  provider: string | null;
  avg_duration_ms: number;
  cost_per_1k_input: number | null;
  cost_per_1k_output: number | null;
  cost_per_1m_input?: number | null;
  cost_per_1m_input_cache_hit?: number | null;
  cost_per_1m_output?: number | null;
}

export interface ModelUsageByPrompt extends ModelUsageBucket {
  prompt_type: string;
}

export interface ModelUsageSummary {
  days: number;
  since: string;
  total: ModelUsageBucket & {
    tokens_total: number;
    avg_duration_ms: number;
    success_rate: number;
  };
  by_model: ModelUsageByModel[];
  by_prompt: ModelUsageByPrompt[];
}