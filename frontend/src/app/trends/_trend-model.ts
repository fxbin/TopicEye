import type { TrendPoint } from '@/types/trends';

export interface TopicSeries {
  topicId: number;
  name: string;
  pts: TrendPoint[];
  total: number;
  picks: number;
  latestCount: number;
  latestDate: string;
  previousDate: string | null;
  delta: number | null;
  momentum: number;
  maxScore: number;
  topItem: { title: string; url: string; score: number } | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function dateTime(date: string): number {
  return Date.parse(`${date}T00:00:00Z`);
}

/** Missing snapshots stay missing; only the shared calendar axis fills gaps. */
export function buildTrendModel(trends: TrendPoint[]) {
  const byTopic = new Map<number, TrendPoint[]>();
  const recordedDates = new Set<string>();
  let totalContent = 0;
  let totalPicks = 0;

  for (const point of trends) {
    const pts = byTopic.get(point.topic_id) ?? [];
    pts.push(point);
    byTopic.set(point.topic_id, pts);
    recordedDates.add(point.date);
    totalContent += point.content_count;
    totalPicks += point.pick_count;
  }

  const topics: TopicSeries[] = Array.from(byTopic, ([topicId, points]) => {
    const pts = [...points].sort((a, b) => a.date.localeCompare(b.date));
    const latest = pts[pts.length - 1];
    const previous = pts[pts.length - 2];
    const comparable = previous !== undefined
      && dateTime(latest.date) - dateTime(previous.date) === DAY_MS
      && !!latest.calculation_version?.trim()
      && latest.calculation_version === previous.calculation_version;
    const delta = comparable ? latest.content_count - previous.content_count : null;
    const picks = pts.reduce((sum, point) => sum + point.pick_count, 0);
    let topItem: TopicSeries['topItem'] = null;
    for (const point of pts) {
      for (const item of point.top_items ?? []) {
        if (topItem === null || item.score > topItem.score) topItem = item;
      }
    }
    return {
      topicId,
      name: latest.topic_name,
      pts,
      total: pts.reduce((sum, point) => sum + point.content_count, 0),
      picks,
      latestCount: latest.content_count,
      latestDate: latest.date,
      previousDate: previous?.date ?? null,
      delta,
      momentum: latest.content_count + Math.max(0, delta ?? 0) * 2 + picks,
      maxScore: Math.max(0, ...pts.map((point) => point.max_score)),
      topItem,
    };
  }).sort((a, b) => b.momentum - a.momentum || a.topicId - b.topicId);

  const recorded = Array.from(recordedDates).sort();
  const latestDate = recorded[recorded.length - 1] ?? null;
  const dates: string[] = [];
  if (recorded.length > 0) {
    // The topics API bounds its snapshot window to 31 calendar days.
    const end = dateTime(latestDate!);
    for (let day = dateTime(recorded[0]); day <= end && dates.length < 31; day += DAY_MS) {
      dates.push(new Date(day).toISOString().slice(0, 10));
    }
  }

  return { topics, dates, totalContent, totalPicks, latestDate, recordedDays: recorded.length };
}
