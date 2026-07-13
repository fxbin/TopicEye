'use client';

import React from 'react';
import { CalendarDays } from 'lucide-react';
import DigestReportPage from '@/components/DigestReportPage';
import { monthlyDigestApi } from '@/lib/api';
import type { MonthlyDigest, MonthlyDigestMonthSummary } from '@/types';

export default function MonthlyDigestPage() {
  return (
    <DigestReportPage<MonthlyDigest, MonthlyDigestMonthSummary>
      title="AI 月刊"
      badge="MONTHLY REVIEW"
      heroLabel="TOPIC RADAR MONTHLY"
      heroTitle={<>选题雷达<br />月刊</>}
      sidebarTitle="历史月刊"
      emptyHistoryText="暂无历史月刊"
      emptyText="暂无月刊数据"
      loadingText="正在加载月刊..."
      generatingText="月刊生成中，请稍候..."
      latestButtonLabel="最新月刊"
      periodName="月刊"
      periodCodeLabel="MONTH"
      topPicksTitle="月度精选选题"
      actionTitle="下月创作行动清单"
      overviewTitle="本月概述"
      keywordTitle="本月关键词"
      historyIcon={CalendarDays}
      api={{
        getCurrent: monthlyDigestApi.getCurrent,
        getByPeriod: monthlyDigestApi.getByMonth,
        listPeriods: async () => (await monthlyDigestApi.listMonths()).months || [],
        generate: monthlyDigestApi.generate,
      }}
      getDigestKey={(digest) => digest.month_key}
      getDigestLabel={(digest) => digest.month_label}
      getDigestStart={(digest) => digest.month_start}
      getDigestEnd={(digest) => digest.month_end}
      getSummaryKey={(summary) => summary.month_key}
      getSummaryLabel={(summary) => summary.month_label}
    />
  );
}
