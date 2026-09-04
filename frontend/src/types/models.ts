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

// ── 模型目录（models.dev 缓存，仅用于表单预填与参考展示） ──

export interface ModelCatalogProviderItem {
  /** models.dev provider id（精选下拉的 value），如 zhipuai */
  id: string;
  /** resolve_litellm_model 拼路由用的 provider 值，如 zhipu / openai */
  litellm_provider: string;
  display_name: string;
  group: string;
  group_label: string;
  model_count: number;
  default_api_base: string | null;
}

export interface ModelCatalogProvidersResponse {
  groups: { key: string; label: string; providers: ModelCatalogProviderItem[] }[];
  others: ModelCatalogProviderItem[];
  featured_count: number;
  total_providers: number;
  fetched_at: string | null;
}

export interface ModelCatalogModelItem {
  provider: string;
  model_id: string;
  name: string | null;
  context_window: number | null;
  max_output_tokens: number | null;
  cost_per_1m_input: number | null;
  cost_per_1m_output: number | null;
  cost_per_1m_cache_read: number | null;
  supports_tool_call: boolean | null;
  supports_structured_output: boolean | null;
  supports_reasoning: boolean | null;
  input_modalities: string[] | null;
  output_modalities: string[] | null;
  open_weights: boolean | null;
  status: string | null;
  release_date: string | null;
  last_updated: string | null;
}

export interface ModelCatalogModelsResponse {
  provider: string;
  requested_provider: string;
  items: ModelCatalogModelItem[];
  total: number;
  limit: number;
  offset: number;
  fetched_at: string | null;
}

export interface ModelCatalogRefreshResponse {
  ok: boolean;
  providers: number;
  models: number;
  deleted_stale: number;
  fetched_at: string;
}