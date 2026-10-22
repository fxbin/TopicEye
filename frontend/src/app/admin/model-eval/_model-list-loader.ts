import { createRequestGuard } from '@/lib/request-guard';
import type { LlmModelItem } from '@/types/models';

/** Concurrent model mutations may refresh the list; only the newest read owns UI state. */
export function createModelListLoader({ fetch, onData, onError, onSettled }: {
  fetch: () => Promise<{ models: LlmModelItem[] }>;
  onData: (models: LlmModelItem[]) => void;
  onError: (error: string | null) => void;
  onSettled: () => void;
}) {
  const guard = createRequestGuard();
  return {
    invalidate: guard.invalidate,
    async refresh(): Promise<void> {
      const isCurrent = guard.begin();
      onError(null);
      try {
        const result = await fetch();
        if (isCurrent()) onData(result.models);
      } catch (error) {
        if (!isCurrent()) return;
        onError(error instanceof Error ? error.message : '模型列表刷新失败，请重试');
        // Mutation callers keep their row locked until this read settles and display current failures.
        throw error;
      } finally {
        if (isCurrent()) onSettled();
      }
    },
  };
}
