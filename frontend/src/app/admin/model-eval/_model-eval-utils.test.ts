/**
 * catalogParamPrefill 单测（issue #221）。
 *
 * 覆盖：
 * - 未命中目录返回空补丁（表单值原样）
 * - 命中时预填上下文窗口 / 输出上限 / 三个价格
 * - 目录字段缺失（null）时保留表单已填值（回归：此前 context_window 会被清空）
 */
import { describe, expect, it } from 'vitest';
import type { ModelCatalogModelItem } from '@/lib/api';
import { catalogParamPrefill } from './_model-eval-utils';

function catalogItem(overrides: Partial<ModelCatalogModelItem> = {}): ModelCatalogModelItem {
  return {
    provider: 'zhipuai',
    model_id: 'glm-4.7',
    name: 'GLM-4.7',
    context_window: 200_000,
    max_output_tokens: 32_768,
    cost_per_1m_input: 0.6,
    cost_per_1m_output: 2.2,
    cost_per_1m_cache_read: 0.06,
    supports_tool_call: true,
    supports_structured_output: true,
    supports_reasoning: true,
    input_modalities: null,
    output_modalities: null,
    open_weights: false,
    status: 'ga',
    release_date: null,
    last_updated: null,
    ...overrides,
  };
}

const prevForm = {
  context_window: null,
  max_tokens: 2000,
  cost_per_1m_input: '',
  cost_per_1m_input_cache_hit: '',
  cost_per_1m_output: '',
};

describe('catalogParamPrefill', () => {
  it('returns an empty patch when no catalog match', () => {
    expect(catalogParamPrefill(null, prevForm)).toEqual({});
    expect(catalogParamPrefill(undefined, prevForm)).toEqual({});
  });

  it('prefills context window, output cap and prices from the catalog', () => {
    expect(catalogParamPrefill(catalogItem(), prevForm)).toEqual({
      context_window: 200_000,
      max_tokens: 32_768,
      cost_per_1m_input: '0.6',
      cost_per_1m_input_cache_hit: '0.06',
      cost_per_1m_output: '2.2',
    });
  });

  it('keeps already-filled form values when catalog fields are missing', () => {
    const filled = {
      ...prevForm,
      context_window: 65_536,
      max_tokens: 8_192,
      cost_per_1m_input: '1',
      cost_per_1m_input_cache_hit: '0.1',
      cost_per_1m_output: '3',
    };
    const sparse = catalogItem({
      context_window: null,
      max_output_tokens: null,
      cost_per_1m_input: null,
      cost_per_1m_output: null,
      cost_per_1m_cache_read: null,
    });
    expect(catalogParamPrefill(sparse, filled)).toEqual(filled);
  });

  it('fills only what the catalog knows on partially-documented models', () => {
    const sparse = catalogItem({
      context_window: 131_072,
      max_output_tokens: null,
      cost_per_1m_input: null,
      cost_per_1m_output: null,
      cost_per_1m_cache_read: null,
    });
    expect(catalogParamPrefill(sparse, prevForm)).toEqual({
      context_window: 131_072,
      max_tokens: 2000,
      cost_per_1m_input: '',
      cost_per_1m_input_cache_hit: '',
      cost_per_1m_output: '',
    });
  });
});
