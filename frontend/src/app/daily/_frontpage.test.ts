import { describe, expect, it } from 'vitest';
import { computeChangeMarkers } from './_frontpage';

describe('daily change markers', () => {
  it('reports declining scores rather than labelling them stable', () => {
    expect(computeChangeMarkers([{ title: 'A', reason: '', score: 70 }], [{ source_title: 'A', old_score: 90 }])).toEqual({ A: 'down' });
  });
  it('does not mislabel a known topic with missing old score as new', () => {
    expect(computeChangeMarkers([{ title: 'A', reason: '', score: 70 }], [{ source_title: 'A', old_score: null }])).toEqual({});
  });
  it('matches a legacy report title when source_title is absent', () => {
    expect(computeChangeMarkers([{ title: 'A', reason: '', score: 80 }], [{ source_title: '', title: 'A', old_score: 80 }])).toEqual({ A: 'flat' });
  });
});
