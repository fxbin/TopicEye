/** Apply one response to the current run, preserving concurrent scores. */
export function applyEvaluationScore<T extends { id: number; quality_score: number | null }>(
  current: { eval_run_id: string; results: T[] } | null,
  runId: string,
  evalId: number,
  score: number,
) {
  if (!current || current.eval_run_id !== runId) return current;
  return { ...current, results: current.results.map((item) => item.id === evalId ? { ...item, quality_score: score } : item) };
}
