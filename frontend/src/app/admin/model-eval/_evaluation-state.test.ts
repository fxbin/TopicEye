import { describe, expect, it } from 'vitest';
import { applyEvaluationScore } from './_evaluation-state';

const run = () => ({ eval_run_id: 'run-A', results: [{ id: 1, quality_score: null as number | null }, { id: 2, quality_score: null as number | null }] });
describe('evaluation response ownership', () => {
  it.each([[1, 2], [2, 1]])('keeps both scores when completion order is %j then %j', (first, second) => {
    let current = run();
    for (const id of [first, second]) current = applyEvaluationScore(current, 'run-A', id, id + 2)!;
    expect(current.results).toEqual([{ id: 1, quality_score: 3 }, { id: 2, quality_score: 4 }]);
  });
  it('ignores an older run finishing after a new result is displayed', () => {
    const current = { ...run(), eval_run_id: 'run-B' };
    expect(applyEvaluationScore(current, 'run-A', 1, 5)).toBe(current);
    expect(applyEvaluationScore(null, 'run-A', 1, 5)).toBeNull();
  });
});
