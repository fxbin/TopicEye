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
 * 后端在 OAuth 成功后 302 到 /oauth/callback#token=xxx&expires_at=xxx，
 * 失败则 302 到 /oauth/callback?error=xxx。
 *
 * 认证 token 通过 HttpOnly cookie 下发（浏览器自动携带），
 * fragment 中的 token 仅用于兼容与 presence 标记设置。
 * 本页读取 URL fragment → 设置 presence cookie → 拉 me() → 写入 Context → 跳首页，
 * 并用 history.replaceState 清理 URL 避免残留。
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

      // 2. 解析 fragment 拿 token
      const params = new URLSearchParams(location.hash.startsWith('#') ? location.hash.slice(1) : location.hash);
      const token = params.get('token');
      const expiresAt = params.get('expires_at');

      if (!token || !expiresAt) {
        if (!cancelled) {
          setErrorMsg('OAuth 回调缺少登录凭证，请重新登录');
          setStatus('error');
        }
        return;
      }

      try {
        // token 已在 HttpOnly cookie 中（后端 302 响应设置）。
        // 设置 presence cookie 让前端判断登录状态，然后拉 me()。
        setAuthToken('1');
        const user = await authApi.me();
        if (cancelled) return;

        applyAuthSession({
          access_token: token,
          token_type: 'bearer',
          expires_at: expiresAt,
          user,
        });

        // 抹掉 URL 里的 token，防止残留在浏览器历史
        history.replaceState(null, '', '/oauth/callback');
        router.replace('/');
      } catch (err) {
        // token 无效或 me() 失败 → 清理并报错
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
