import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="grid min-h-full place-items-center px-4 py-8">
      <div className="max-w-md">
        <p className="font-mono text-sm text-primary-text">404</p>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">找不到这个页面</h1>
        <p className="mt-3 text-sm leading-7 text-gray-600">地址可能已变更，请检查链接，或从导航中继续浏览。</p>
        <Link href="/" className="mt-5 inline-flex min-h-11 items-center rounded-sm bg-primary-solid px-4 text-sm font-bold text-white">返回首页</Link>
      </div>
    </div>
  );
}
