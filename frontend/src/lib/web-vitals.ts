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
 * 上报端点。`next.config.js` 有 `/api/:path*` → 后端的同源 rewrite，
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

/** 浏览器侧 metric 的最小形状（next/web-vitals 的 Metric 类型没有 .d.ts）。 */
export interface WebVitalMetricLike {
  name: string;
  value: number;
  navigationType?: string;
}

export interface WebVitalReporterOptions {
  /** 取当前路径。必须是**惰性**读取：上报时刻的路径才是这次观测对应的页面。 */
  getPath: () => string;
  /** 取设备类型。惰性读取。 */
  getDeviceClass: () => DeviceClass;
  /** 发送通道，默认走 navigator.sendBeacon。 */
  send?: (samples: WebVitalSamplePayload[]) => boolean;
}

/**
 * 造一个上报回调。
 *
 * 抽出来有两个理由：
 *
 * 1. **可单测**：payload 整形与失败静默都是纯逻辑，不该只能靠渲染组件来验。
 * 2. **稳定引用**：web-vitals 的观察器按回调引用注册，回调一变就重挂观察器、
 *    可能重复上报。所以组件要**长期持有同一个回调实例**（用 ref 拿），
 *    而不是靠 `useCallback` 的依赖数组写对——后者是约定，前者是结构保证。
 */
export function createWebVitalReporter(options: WebVitalReporterOptions) {
  return (metric: WebVitalMetricLike): boolean => {
    const payload = buildSamplePayload({
      name: metric.name,
      value: metric.value,
      pathname: options.getPath(),
      navigationType: metric.navigationType,
      deviceClass: options.getDeviceClass(),
    });
    if (!payload) return false;
    const send =
      options.send ??
      ((samples: WebVitalSamplePayload[]) =>
        sendSamples(samples, (url, body) => navigator.sendBeacon(url, body)));
    try {
      return send([payload]);
    } catch {
      // 上报永远不能影响页面：发送通道抛错就当没发出去
      return false;
    }
  };
}
