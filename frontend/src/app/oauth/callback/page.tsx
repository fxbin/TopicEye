'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Radar } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { authApi, setAuthToken } from '@/lib/api';
import { Button, Panel } from '@/components/ui';

type Status = 'loading' | 'error' | 'success';

/**
 * OAuth 回调消费页。
 *
 * 后端在 OAuth 成功后 302 到 /oauth/callback#provider=xx&expires_at=xx，
 * 失败则 302 到 /oauth/callback?error=xxx。
 *
 * 会话凭证只通过 HttpOnly cookie 下发（浏览器自动携带），本页不读取
 * 任何凭证类 fragment 参数（#63）；旧版 #token=... 链接仍能落地，
 * 但 token 一律不消费。流程：设置 presence 标记 → 拉 me() → 写入
 * Context → 跳首页，并用 history.replaceState 清理 URL。
 */
export default function OauthCallbackPage() {
  const router = useRouter();
  const { applyAuthSession } = useAppContext();
  const [status, setStatus] = useState<Status>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');

  useEffect(() => {
    let cancelled = false;

    async function run() {
      const { location } = window;

      // 1. 优先检查错误（query param）
      const errorParam = new URLSearchParams(location.search).get('error');
      if (errorParam) {
        if (!cancelled) {
          setErrorMsg(decodeURIComponent(errorParam));
          setStatus('error');
        }
        return;
      }

      // 2. 解析 fragment 中的非敏感状态（#63：不读取/消费任何凭证参数）
      const params = new URLSearchParams(location.hash.startsWith('#') ? location.hash.slice(1) : location.hash);
      const expiresAt = params.get('expires_at') ?? '';

      try {
        // 会话凭证已在 HttpOnly cookie 中（后端 302 响应设置）。
        // 设置 presence 标记让前端判断登录状态，然后以 cookie 拉 me()。
        setAuthToken('1');
        const user = await authApi.me();
        if (cancelled) return;

        applyAuthSession({
          access_token: 'http-only-cookie', // 占位：applyAuthSession 仅作 presence 用
          token_type: 'bearer',
          expires_at: expiresAt,
          user,
        });

        // 清理 URL，防止残留状态参数
        history.replaceState(null, '', '/oauth/callback');
        router.replace('/');
      } catch (err) {
        // cookie 缺失/无效或 me() 失败 → 清理并报错
        setAuthToken(null);
        if (!cancelled) {
          setErrorMsg(err instanceof Error ? err.message : '登录信息拉取失败，请重新登录');
          setStatus('error');
        }
      }
    }

    run();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-full min-h-0 items-center justify-center bg-page px-6 py-8">
      <Panel className="w-full max-w-md p-8 shadow-sm">
        {status === 'loading' && (
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-sm bg-primary text-white shadow-sm">
              <Radar size={22} strokeWidth={2.4} className="animate-pulse" />
            </div>
            <p className="text-sm font-black text-gray-700">正在完成登录...</p>
            <p className="mt-1 text-xs text-gray-400">请稍候</p>
          </div>
        )}

        {status === 'error' && (
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-sm bg-red-light text-red">
              <Radar size={22} strokeWidth={2.4} />
            </div>
            <p className="mb-1 text-sm font-black text-gray-800">登录失败</p>
            <p className="mb-5 max-w-xs text-xs leading-6 text-gray-500">{errorMsg}</p>
            <Button
              variant="primary"
              onClick={() => router.replace('/login')}
            >
              返回登录
              <ArrowRight size={14} />
            </Button>
          </div>
        )}
      </Panel>
    </div>
  );
}
