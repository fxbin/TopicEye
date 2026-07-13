'use client';

import React, { useState, useCallback } from 'react';
import { ClipboardList } from 'lucide-react';
import DigestReportPage from '@/components/DigestReportPage';
import DailyWeeklyMonthlyTabs from '@/components/DailyWeeklyMonthlyTabs';
import WeeklyPickTracking from '@/components/WeeklyPickTracking';
import { weeklyDigestApi } from '@/lib/api';
import type { WeeklyDigest, WeeklyDigestWeekSummary } from '@/types';

export default function WeeklyDigestPage() {
  const [currentWeekKey, setCurrentWeekKey] = useState<string | undefined>();
  const handleDigestChange = useCallback((digest: WeeklyDigest | null) => {
    setCurrentWeekKey(digest?.week_key);
  }, []);

  return (
    <>
      <DailyWeeklyMonthlyTabs current="weekly" />
      <div className="flex-1 overflow-hidden">
        <DigestReportPage<WeeklyDigest, WeeklyDigestWeekSummary>
          title="AI 周刊"
          badge="WEEKLY REVIEW"
          heroLabel="TOPIC RADAR WEEKLY"
          heroTitle={<>选题雷达<br />周刊</>}
          sidebarTitle="历史周刊"
          emptyHistoryText="暂无历史周刊"
          emptyText="暂无周刊数据"
          loadingText="正在加载周刊..."
          generatingText="周刊生成中，请稍候..."
          latestButtonLabel="最新周刊"
          periodName="周刊"
          periodCodeLabel="WEEK"
          topPicksTitle="精选选题 TOP 5"
          actionTitle="下周创作行动清单"
          overviewTitle="本周概述"
          keywordTitle="本周关键词"
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
        />
        <WeeklyPickTracking weekKey={currentWeekKey} />
      </div>
    </>
  );
}
