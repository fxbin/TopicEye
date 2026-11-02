import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import AdminTopBar from './AdminTopBar';

const status = vi.hoisted(() => ({ pending: false }));
vi.mock('next/navigation', () => ({ usePathname: () => '/admin/dashboard' }));
vi.mock('next/link', () => ({
  default: ({ children, prefetch, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { prefetch?: boolean }) => <a data-prefetch={String(prefetch)} {...props}>{children}</a>,
  useLinkStatus: () => status,
}));
vi.mock('@/components/ClientLayout', () => ({ useAppContext: () => ({ currentUser: null }) }));

describe('前后台导航', () => {
  it('返回前台使用可预取的真实链接', () => {
    status.pending = false;
    const html = renderToStaticMarkup(<AdminTopBar />);
    expect(html).toContain('href="/"');
    expect(html).toContain('data-prefetch="true"');
    expect(html).toContain('监控大盘');
  });
  it('等待首页响应时立即给出可访问的反馈', () => {
    status.pending = true;
    const html = renderToStaticMarkup(<AdminTopBar />);
    expect(html).toContain('正在返回');
    expect(html).toContain('正在打开前台页面');
    expect(html).toContain('role="status"');
  });
});
