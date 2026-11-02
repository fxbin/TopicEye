import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';
import { canAccessPath, requiredAccessForPath } from '@/lib/navigation';

const loadConfig = createRequire(import.meta.url);
const config = loadConfig('../../../next.config.js') as {
  redirects: () => Promise<Array<{ source: string; destination: string; permanent: boolean }>>;
  rewrites: () => Promise<Array<{ source: string; destination: string }>>;
};

describe('监控大盘路由归属', () => {
  it('只保留后台入口，不维护旧路径的重定向或转发', async () => {
    expect((await config.redirects()).some(r => r.source === '/dashboard')).toBe(false);
    expect((await config.rewrites()).some(r => r.source === '/dashboard')).toBe(false);
  });
  it('新入口仍要求管理员身份', () => {
    expect(requiredAccessForPath('/admin/dashboard')).toBe('admin');
    expect(canAccessPath('/admin/dashboard', null)).toBe(false);
  });
});
