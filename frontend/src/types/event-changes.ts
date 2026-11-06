export type EventChangeType = 'no_new_material' | 'fact' | 'evidence' | 'opinion' | 'uncertain';
export interface EventChangeRef {
  id: number;
  title: string;
  url: string;
  source_name: string | null;
  published_at: string | null;
}
export interface EventChangeQuote extends EventChangeRef { excerpt: string }
export interface EventChangeItem extends EventChangeRef {
  change_type: EventChangeType;
  description: string;
  quotes: EventChangeQuote[];
}
export interface EventChangeRequest {
  expected_event_id: number;
  expected_version: number;
  member_ids: number[];
}
export interface EventChangeAnalysis {
  status: 'ok' | 'partial' | 'insufficient_material';
  event_id: number;
  version: number;
  anchor: EventChangeRef;
  member_ids: number[];
  items: EventChangeItem[];
}

export interface EventRelationFeedbackRequest {
  expected_event_id: number;
  expected_version: number;
  member_id: number;
  reason: string;
}
