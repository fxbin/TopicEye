'use client';
import { EDITION_LABELS } from '@/lib/edition-naming';

import React, { useState, useCallback } from 'react';
import { ClipboardList } from 'lucide-react';
import DigestReportPage from '@/components/DigestReportPage';
import WeeklyPickTracking from '@/components/WeeklyPickTracking';
import { weeklyDigestApi } from '@/lib/api';
import { useReadTracking } from '@/hooks/useReadTracking';
import type { WeeklyDigest, WeeklyDigestWeekSummary } from '@/types';

export default function WeeklyDigestPage() {
  const [currentWeekKey, setCurrentWeekKey] = useState<string | undefined>();
  const handleDigestChange = useCallback((digest: WeeklyDigest | null) => {
    setCurrentWeekKey(digest?.week_key);
  }, []);

  // 阅读时长追踪：切换周刊/离开页面时上报累计停留时长（行为偏好数据）
  useReadTracking('weekly_digest', currentWeekKey);

  return (
      <DigestReportPage<WeeklyDigest, WeeklyDigestWeekSummary>
        title={EDITION_LABELS.weekly}
        badge="WEEKLY INTELLIGENCE"
        heroLabel="TOPIC RADAR WEEKLY"
        heroTitle={<>选题雷达<br />{EDITION_LABELS.weekly}</>}
        sidebarTitle={`历史${EDITION_LABELS.weekly}`}
        emptyHistoryText={`暂无历史${EDITION_LABELS.weekly}`}
        emptyText={`暂无${EDITION_LABELS.weekly}数据`}
        loadingText={`正在加载${EDITION_LABELS.weekly}...`}
        generatingText={`${EDITION_LABELS.weekly}生成中，请稍候...`}
        latestButtonLabel={`最新${EDITION_LABELS.weekly}`}
        periodName={EDITION_LABELS.weekly}
        periodCodeLabel="WEEK"
        topPicksTitle="精选选题 TOP 5"
        actionTitle="下周创作行动清单"
        overviewTitle="本周概述"
        keywordTitle="本周关键词"
        clusterTitle="本周脉络"
        clusterFirst
        historyIcon={ClipboardList}
        api={{
          getCurrent: weeklyDigestApi.getCurrent,
          getByPeriod: weeklyDigestApi.getByWeek,
          listPeriods: async () => (await weeklyDigestApi.listWeeks()).weeks || [],
          generate: weeklyDigestApi.generate,
        }}
        getDigestKey={(digest) => digest.week_key}
        getDigestLabel={(digest) => digest.week_label}
        getDigestStart={(digest) => digest.week_start}
        getDigestEnd={(digest) => digest.week_end}
        getSummaryKey={(summary) => summary.week_key}
        getSummaryLabel={(summary) => summary.week_label}
        onDigestChange={handleDigestChange}
      >
        <WeeklyPickTracking weekKey={currentWeekKey} />
      </DigestReportPage>
  );
}
