'use client';

/**
 * 阅读时长追踪 hook（行为偏好数据采集）。
 *
 * 设计：
 * - 纯前端用 setInterval 累计本地停留时长，不每次发请求（避免高频写库）。
 * - 仅在 targetKey 变化 / 页面隐藏 / 组件卸载时上报一次累计时长。
 * - 卸载上报用 navigator.sendBeacon（fetch 在 unload 时会被浏览器取消）；
 *   sendBeacon 同源时自动携带 cookie，跨域时不携带。
 * - 未登录（无 auth cookie）时静默跳过，不影响阅读体验。
 *
 * 用法：
 *   useReadTracking('daily_report', report?.report_date, report?.id);
 *   useReadTracking('weekly_digest', currentWeekKey);
 */

import { useEffect, useRef } from 'react';
import { BASE_URL, getAuthToken } from '@/lib/api/_core';
import { readRecordApi, type ReadTargetType } from '@/lib/api/_read-records';

const HEARTBEAT_INTERVAL_MS = 10_000; // 每 10s 累加一次本地时长

export function useReadTracking(
  targetType: ReadTargetType,
  targetKey: string | undefined,
  targetId?: number,
): void {
  // 当前会话的累计时长（ms），用 ref 避免 re-render
  const accumulatedMsRef = useRef(0);
  // 当前正在追踪的 target（用 ref 持有最新值，供 unload handler 读取）
  const sessionRef = useRef<{ type: ReadTargetType; key: string; id?: number } | null>(null);
  // 标记是否已上报过本次会话（避免卸载时重复发）
  const reportedRef = useRef(false);

  // 发送累计时长到后端（幂等 upsert）
  const flush = async (session: { type: ReadTargetType; key: string; id?: number } | null) => {
    if (!session) return;
    if (accumulatedMsRef.current <= 0) return;
    if (reportedRef.current) return;
    const duration_ms = accumulatedMsRef.current;
    // 标记已上报，清零本地累计
    reportedRef.current = true;
    accumulatedMsRef.current = 0;
    try {
      await readRecordApi.report({
        target_type: session.type,
        target_key: session.key,
        target_id: session.id,
        duration_ms,
      });
    } catch {
      // 上报失败静默处理，不阻塞用户阅读；时长丢失可接受（偏好数据容忍噪声）
    }
  };

  // 用 sendBeacon 发送（unload 场景，fetch 会被取消）
  const flushBeacon = (session: { type: ReadTargetType; key: string; id?: number } | null) => {
    if (!session) return;
    if (accumulatedMsRef.current <= 0) return;
    if (reportedRef.current) return;
    if (typeof navigator === 'undefined' || typeof navigator.sendBeacon !== 'function') return;
    if (!getAuthToken()) return; // 未登录不上报
    const duration_ms = accumulatedMsRef.current;
    reportedRef.current = true;
    accumulatedMsRef.current = 0;
    const payload = JSON.stringify({
      target_type: session.type,
      target_key: session.key,
      target_id: session.id,
      duration_ms,
    });
    // sendBeacon 只能发 Blob，需带 Content-Type 头让后端解析 JSON
    const blob = new Blob([payload], { type: 'application/json' });
    try {
      navigator.sendBeacon(`${BASE_URL}/read-records`, blob);
    } catch {
      // 静默
    }
  };

  useEffect(() => {
    // 无 targetKey（加载中/无报告）时，先 flush 旧会话再置空
    if (!targetKey) {
      flush(sessionRef.current);
      sessionRef.current = null;
      return;
    }
    if (!getAuthToken()) return; // 未登录不追踪

    // targetKey 变化：先 flush 旧会话，再开启新会话
    const prev = sessionRef.current;
    if (prev && prev.key !== targetKey) {
      flush(prev);
    }
    reportedRef.current = false;
    sessionRef.current = { type: targetType, key: targetKey, id: targetId };

    // 本地时长累加器
    const timer = setInterval(() => {
      accumulatedMsRef.current += HEARTBEAT_INTERVAL_MS;
      reportedRef.current = false; // 有新增时长，允许下次 flush
    }, HEARTBEAT_INTERVAL_MS);

    // 页面隐藏时立即上报（visibilitychange 比 unload 更可靠地触发）
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') {
        flushBeacon(sessionRef.current);
      }
    };
    const handlePageHide = () => {
      flushBeacon(sessionRef.current);
    };

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('pagehide', handlePageHide);

    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('pagehide', handlePageHide);
      // 组件卸载或 targetKey 切换：尝试正常 flush（异步），卸载时浏览器可能不等 await
      flush(sessionRef.current);
    };
    // targetKey / targetType / targetId 变化时重置会话
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType, targetKey, targetId]);
}
