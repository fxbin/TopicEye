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
 * 2. **观察器只注册一次**：web-vitals 的观察器按回调引用注册，回调一变就重挂
 *    观察器、可能重复上报。所以回调实例用 ref 长期持有（结构保证），
 *    而不是靠 `useCallback` 的依赖数组写对（约定保证）。
 * 3. **路径按上报时刻取**：软导航时 metric 触发时页面已经切走，
 *    读的是 ref 里的当前路径，正是这次观测对应的页面。
 */

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { useReportWebVitals } from 'next/web-vitals';
import {
  createWebVitalReporter,
  toDeviceClass,
  type WebVitalMetricLike,
} from '@/lib/web-vitals';

export default function WebVitalsReporter() {
  const pathname = usePathname();
  const pathnameRef = useRef(pathname);
  useEffect(() => {
    pathnameRef.current = pathname;
  }, [pathname]);

  // 懒初始化一次，之后永远是同一个引用
  const reportRef = useRef<((metric: WebVitalMetricLike) => boolean) | null>(null);
  if (!reportRef.current) {
    reportRef.current = createWebVitalReporter({
      getPath: () => pathnameRef.current,
      getDeviceClass: () => toDeviceClass(navigator.userAgent),
    });
  }

  useReportWebVitals(reportRef.current);

  return null;
}
