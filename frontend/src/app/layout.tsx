import type { Metadata } from 'next';
import { DM_Sans, DM_Mono, Noto_Serif_SC } from 'next/font/google';
import './globals.css';
import ClientLayout from '@/components/ClientLayout';
import SkipToContent from '@/components/SkipToContent';
import { prefetchInitialData } from '@/lib/server-prefetch';

const dmSans = DM_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-dm-sans',
});

const dmMono = DM_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  display: 'swap',
  variable: '--font-dm-mono',
});

// 衬线 display 字体：用于页面大标题，与 DM Sans body 形成对比，
// 强化「编辑 / 出版物」气质，跳出 sans 后台的售货员感。
const notoSerif = Noto_Serif_SC({
  subsets: ['latin'],
  weight: ['600', '700', '900'],
  display: 'swap',
  variable: '--font-display',
});

export const metadata: Metadata = {
  title: '选题雷达 · 创作者选题情报站',
  description: 'AI 驱动的创作者选题推荐平台，帮你发现下一个爆款选题',
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // SSR 预取首屏数据（auth/me + feature-flags + 侧边栏计数），
  // 消除客户端 useEffect 串行拉取导致的白屏。
  // 后端不可达时返回 null，客户端 Provider 会 fallback 到 useEffect。
  const initialData = await prefetchInitialData();

  return (
    <html lang="zh-CN" className={`${dmSans.variable} ${dmMono.variable} ${notoSerif.variable}`} suppressHydrationWarning>
      <body>
        <SkipToContent />
        <ClientLayout initialData={initialData}>{children}</ClientLayout>
      </body>
    </html>
  );
}
