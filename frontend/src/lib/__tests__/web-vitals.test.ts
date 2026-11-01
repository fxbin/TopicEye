import { describe, expect, it, vi } from 'vitest';
import {
  REPORTABLE_METRICS,
  WEB_VITALS_ENDPOINT,
  buildSamplePayload,
  createWebVitalReporter,
  isReportableMetric,
  sendSamples,
  toDeviceClass,
  type WebVitalSamplePayload,
} from '@/lib/web-vitals';

describe('isReportableMetric', () => {
  it('接受 web-vitals 的五个核心指标', () => {
    expect([...REPORTABLE_METRICS]).toEqual(['LCP', 'INP', 'CLS', 'FCP', 'TTFB']);
    REPORTABLE_METRICS.forEach((name) => {
      expect(isReportableMetric(name)).toBe(true);
    });
  });

  it('拒绝未知指标', () => {
    expect(isReportableMetric('FID')).toBe(false);
    expect(isReportableMetric('lcp')).toBe(false);
    expect(isReportableMetric('')).toBe(false);
  });
});

describe('toDeviceClass', () => {
  it('识别手机', () => {
    expect(toDeviceClass('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')).toBe('mobile');
    expect(toDeviceClass('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile')).toBe('mobile');
  });

  it('识别平板（不能被 Android 手机规则吃掉）', () => {
    expect(toDeviceClass('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)')).toBe('tablet');
    expect(toDeviceClass('Mozilla/5.0 (Linux; Android 14; SM-X200)')).toBe('tablet');
  });

  it('识别桌面', () => {
    expect(toDeviceClass('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe('desktop');
    expect(toDeviceClass('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('desktop');
    expect(toDeviceClass('Mozilla/5.0 (X11; Linux x86_64)')).toBe('desktop');
  });

  it('未知 UA 归 unknown，不猜', () => {
    expect(toDeviceClass('')).toBe('unknown');
    expect(toDeviceClass('SomeBot/1.0')).toBe('unknown');
  });
});

describe('buildSamplePayload', () => {
  const base = {
    name: 'LCP',
    value: 1200,
    pathname: '/trending',
    deviceClass: 'desktop' as const,
  };

  it('整形成上报体', () => {
    expect(buildSamplePayload(base)).toEqual({
      metric: 'LCP',
      value: 1200,
      path: '/trending',
      navigation_type: 'navigate',
      device_class: 'desktop',
    });
  });

  it('透传导航类型，缺省为 navigate', () => {
    expect(buildSamplePayload({ ...base, navigationType: 'soft-navigation' })?.navigation_type).toBe(
      'soft-navigation',
    );
    expect(buildSamplePayload(base)?.navigation_type).toBe('navigate');
  });

  it('路径缺省为根路径', () => {
    expect(buildSamplePayload({ ...base, pathname: '' })?.path).toBe('/');
  });

  it('不认识的指标不上报', () => {
    expect(buildSamplePayload({ ...base, name: 'FID' })).toBeNull();
  });

  it('非法数值不上报', () => {
    expect(buildSamplePayload({ ...base, value: Number.NaN })).toBeNull();
    expect(buildSamplePayload({ ...base, value: Number.POSITIVE_INFINITY })).toBeNull();
    expect(buildSamplePayload({ ...base, value: -1 })).toBeNull();
  });
});

describe('sendSamples', () => {
  it('把样本发到同源上报端点', async () => {
    const sender = vi.fn().mockReturnValue(true);
    const payload = buildSamplePayload({
      name: 'LCP',
      value: 1200,
      pathname: '/trending',
      deviceClass: 'desktop',
    })!;

    expect(sendSamples([payload], sender)).toBe(true);
    expect(sender).toHaveBeenCalledTimes(1);
    const [url, body] = sender.mock.calls[0];
    expect(url).toBe(WEB_VITALS_ENDPOINT);
    expect(url.startsWith('/')).toBe(true);
    expect(body).toBeInstanceOf(Blob);
    const parsed = JSON.parse(await body.text());
    expect(parsed.samples).toHaveLength(1);
    expect(parsed.samples[0].metric).toBe('LCP');
  });

  it('空批次不发', () => {
    const sender = vi.fn().mockReturnValue(true);
    expect(sendSamples([], sender)).toBe(false);
    expect(sender).not.toHaveBeenCalled();
  });

  it('发送失败静默返回 false', () => {
    const failing = vi.fn().mockReturnValue(false);
    expect(sendSamples([{} as never], failing)).toBe(false);

    const throwing = vi.fn().mockImplementation(() => {
      throw new Error('beacon unavailable');
    });
    expect(sendSamples([{} as never], throwing)).toBe(false);
  });
});

describe('createWebVitalReporter', () => {
  it('整形并发送样本', () => {
    const sent: WebVitalSamplePayload[][] = [];
    const report = createWebVitalReporter({
      getPath: () => '/trending',
      getDeviceClass: () => 'desktop',
      send: (samples) => {
        sent.push(samples);
        return true;
      },
    });

    expect(report({ name: 'LCP', value: 1200, navigationType: 'navigate' })).toBe(true);
    expect(sent).toHaveLength(1);
    expect(sent[0][0]).toEqual({
      metric: 'LCP',
      value: 1200,
      path: '/trending',
      navigation_type: 'navigate',
      device_class: 'desktop',
    });
  });

  it('路径与设备类型都是上报时刻才取', () => {
    // 软导航：metric 触发时页面已经切走，取到的应是当前路径
    let currentPath = '/';
    const sent: WebVitalSamplePayload[][] = [];
    const report = createWebVitalReporter({
      getPath: () => currentPath,
      getDeviceClass: () => 'mobile',
      send: (samples) => {
        sent.push(samples);
        return true;
      },
    });

    currentPath = '/topics/42';
    report({ name: 'LCP', value: 900 });
    expect(sent[0][0].path).toBe('/topics/42');
  });

  it('不认识的指标不发', () => {
    const send = vi.fn().mockReturnValue(true);
    const report = createWebVitalReporter({
      getPath: () => '/',
      getDeviceClass: () => 'desktop',
      send,
    });
    expect(report({ name: 'FID', value: 100 })).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('发送失败静默返回 false，不抛', () => {
    const report = createWebVitalReporter({
      getPath: () => '/',
      getDeviceClass: () => 'desktop',
      send: () => {
        throw new Error('beacon unavailable');
      },
    });
    expect(report({ name: 'LCP', value: 100 })).toBe(false);
  });
});

describe('createWebVitalReporter 默认发送通道', () => {
  it('走 navigator.sendBeacon，投递到上报端点', () => {
    const original = globalThis.navigator;
    const sendBeacon = vi.fn().mockReturnValue(true);
    Object.defineProperty(globalThis, 'navigator', {
      value: { ...original, sendBeacon },
      configurable: true,
      writable: true,
    });
    try {
      const report = createWebVitalReporter({
        getPath: () => '/trending',
        getDeviceClass: () => 'desktop',
      });
      expect(report({ name: 'LCP', value: 1200 })).toBe(true);
      expect(sendBeacon).toHaveBeenCalledTimes(1);
      expect(sendBeacon.mock.calls[0][0]).toBe(WEB_VITALS_ENDPOINT);
    } finally {
      Object.defineProperty(globalThis, 'navigator', {
        value: original,
        configurable: true,
        writable: true,
      });
    }
  });

  it('beacon 不可用时静默返回 false', () => {
    const original = globalThis.navigator;
    Object.defineProperty(globalThis, 'navigator', {
      value: { ...original, sendBeacon: () => false },
      configurable: true,
      writable: true,
    });
    try {
      const report = createWebVitalReporter({
        getPath: () => '/trending',
        getDeviceClass: () => 'desktop',
      });
      expect(report({ name: 'LCP', value: 1200 })).toBe(false);
    } finally {
      Object.defineProperty(globalThis, 'navigator', {
        value: original,
        configurable: true,
        writable: true,
      });
    }
  });
});
