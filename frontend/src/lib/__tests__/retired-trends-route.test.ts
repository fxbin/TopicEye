import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('退役的趋势追踪页面', () => {
  it('不再注册页面或路由处理器', () => {
    for (const name of ['page', 'route']) {
      for (const extension of ['ts', 'tsx', 'js', 'jsx', 'mdx']) {
        expect(existsSync(new URL(`../../app/trends/${name}.${extension}`, import.meta.url))).toBe(false);
      }
    }
  });
  it('不通过配置把旧地址重定向到其它页面', () => {
    const config = readFileSync(new URL('../../../next.config.js', import.meta.url), 'utf8');
    const retiredSource = /source\s*:\s*['"]\/trends(?:\/[^'"]*)?['"]/;
    expect("{ source: '/trends', destination: '/today-picks' }").toMatch(retiredSource);
    expect("{ source: '/trends/:path*', destination: '/today-picks' }").toMatch(retiredSource);
    expect(config).not.toMatch(retiredSource);
  });
});
