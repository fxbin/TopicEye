/**
 * 前端体验指标上报的纯逻辑（#179）。
 *
 * 口径真源在服务端（阈值判定、路径归一、值域校验，见
 * `backend/app/services/web_vitals_service.py`），这里只做三件事：
 *
 * - 把浏览器侧的 metric 对象整形成上报体；
 * - 派生设备类型（**不传原始 User-Agent**，服务端也不存原始 UA）；
 * - 用 `navigator.sendBeacon` 发出去（sender 以参数注入，便于单测）。
 *
 * 本模块不碰 DOM 之外的浏览器状态，可在 node 环境直接测。
 */

/** 服务端接受的指标名，与 web-vitals 的 name 对齐。 */
export const REPORTABLE_METRICS = ['LCP', 'INP', 'CLS', 'FCP', 'TTFB'] as const;

export type ReportableMetric = (typeof REPORTABLE_METRICS)[number];

export type DeviceClass = 'mobile' | 'desktop' | 'tablet' | 'unknown';

export interface WebVitalSamplePayload {
  metric: string;
  value: number;
  path: string;
  navigation_type: string;
  device_class: DeviceClass;
}

/**
 * 上报端点。`next.config.ts` 有 `/api/:path*` → 后端的同源 rewrite，
 * 所以这里是**同源**请求：HttpOnly auth cookie 随行，能关联到用户；
 * 且不需要 CORS 预检。
 */
export const WEB_VITALS_ENDPOINT = '/api/v1/metrics/web-vitals';

export function isReportableMetric(name: string): name is ReportableMetric {
  return (REPORTABLE_METRICS as readonly string[]).includes(name);
}

/**
 * 从 User-Agent 派生设备类型。原始 UA 不上报、不落库。
 *
 * 判定顺序有讲究：iPad 与「无 mobile 的 Android」都算平板，
 * 必须排在 mobile 规则前面，否则会被 Android 规则先吃掉。
 */
export function toDeviceClass(userAgent: string): DeviceClass {
  if (!userAgent) return 'unknown';
  const ua = userAgent.toLowerCase();
  if (/ipad|tablet|playbook|silk/.test(ua)) return 'tablet';
  if (/android/.test(ua) && !/mobile/.test(ua)) return 'tablet';
  if (/mobi|iphone|ipod|android/.test(ua)) return 'mobile';
  if (/windows|macintosh|linux|cros/.test(ua)) return 'desktop';
  return 'unknown';
}

/** 把浏览器侧的 metric 整形成上报体；不认识的指标或非法值返回 null（不上报）。 */
export function buildSamplePayload(input: {
  name: string;
  value: number;
  pathname: string;
  navigationType?: string;
  deviceClass: DeviceClass;
}): WebVitalSamplePayload | null {
  if (!isReportableMetric(input.name)) return null;
  if (typeof input.value !== 'number' || !Number.isFinite(input.value)) return null;
  if (input.value < 0) return null;
  return {
    metric: input.name,
    value: input.value,
    path: input.pathname || '/',
    navigation_type: input.navigationType || 'navigate',
    device_class: input.deviceClass,
  };
}

/** beacon 发送器签名，便于注入替身做单测。 */
export type BeaconSender = (url: string, body: Blob) => boolean;

/**
 * 发出一批样本。返回是否投递成功。
 *
 * 失败一律静默返回 false：这是遥测通道，不能因为上报失败影响页面。
 */
export function sendSamples(samples: WebVitalSamplePayload[], sender: BeaconSender): boolean {
  if (!samples.length) return false;
  try {
    const body = new Blob([JSON.stringify({ samples })], { type: 'application/json' });
    return sender(WEB_VITALS_ENDPOINT, body);
  } catch {
    return false;
  }
}
