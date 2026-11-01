'use client';

/**
 * 前端体验指标采集器（#179）。
 *
 * 用 Next 内置的 `useReportWebVitals` 订阅 LCP / INP / CLS / FCP / TTFB，
 * 每次拿到最终值就经 `navigator.sendBeacon` 发到后端。
 *
 * 三条纪律：
 *
 * 1. **不拖累被观测的指标**：sendBeacon 不阻塞渲染，失败静默。
 * 2. **回调要稳定**：web-vitals 的观察器按回调引用注册，回回调换会把
 *    观察器重挂一遍、可能重复上报。所以回调用 `useCallback([])` 固定，
 *    当前路径走 ref 读，不把 pathname 放进依赖。
 * 3. **路径按上报时刻取**：软导航时 metric 触发时页面已经切走，
 *    ref 里是当前路径，正是这次观测对应的页面。
 */

import { useCallback, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { useReportWebVitals } from 'next/web-vitals';
import { buildSamplePayload, sendSamples, toDeviceClass } from '@/lib/web-vitals';

/** next/web-vitals 的 Metric 类型在编译产物里没有 .d.ts，这里用最小形状自描述。 */
type WebVitalMetricLike = {
  name: string;
  value: number;
  navigationType?: string;
};

export default function WebVitalsReporter() {
  const pathname = usePathname();
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;

  const report = useCallback((metric: WebVitalMetricLike) => {
    const payload = buildSamplePayload({
      name: metric.name,
      value: metric.value,
      pathname: pathnameRef.current,
      navigationType: metric.navigationType,
      deviceClass: toDeviceClass(navigator.userAgent),
    });
    if (!payload) return;
    sendSamples([payload], (url, body) => navigator.sendBeacon(url, body));
  }, []);

  useReportWebVitals(report);

  return null;
}
