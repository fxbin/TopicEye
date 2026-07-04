'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, LockKeyhole, Mail, Radar, UserRound } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { authApi } from '@/lib/api';
import { Badge, Button, Panel, cx } from '@/components/ui';

type AuthMode = 'login' | 'register';

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  );
}

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56v-2c-3.2.7-3.88-1.54-3.88-1.54-.53-1.34-1.3-1.7-1.3-1.7-1.06-.72.08-.71.08-.71 1.17.08 1.79 1.2 1.79 1.2 1.04 1.79 2.73 1.27 3.4.97.11-.75.41-1.27.74-1.56-2.55-.29-5.23-1.28-5.23-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.1 11.1 0 0 1 2.9-.39c.98 0 1.97.13 2.9.39 2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.69 5.41-5.25 5.69.42.36.79 1.08.79 2.18v3.23c0 .31.21.68.8.56C20.21 21.38 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}

const OAUTH_META: Record<'google' | 'github', { label: string; Icon: (p: { className?: string }) => React.ReactElement }> = {
  google: { label: 'Google', Icon: GoogleIcon },
  github: { label: 'GitHub', Icon: GithubIcon },
};

export default function LoginPage() {
  const router = useRouter();
  const { applyAuthSession, currentUser } = useAppContext();
  const [mode, setMode] = useState<AuthMode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oauthProviders, setOauthProviders] = useState<string[]>([]);

  // 拉取后端已启用的 OAuth provider 列表，决定是否渲染对应按钮
  useEffect(() => {
    authApi.oauthProviders()
      .then((res) => setOauthProviders(res.providers || []))
      .catch(() => { /* 未配置或后端不可用，静默隐藏按钮 */ });
  }, []);

  const enabledOauth = (['google', 'github'] as const).filter((p) => oauthProviders.includes(p));

  const handleOauthLogin = (provider: 'google' | 'github') => {
    // 整页跳转到后端，后端 302 到 provider 授权页
    window.location.href = authApi.oauthLoginUrl(provider);
  };

  const canSubmit = useMemo(() => {
    if (!email.trim() || !password) return false;
    if (mode === 'register' && password.length < 8) return false;
    return true;
  }, [email, password, mode]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const session = mode === 'login'
        ? await authApi.login({ email: email.trim(), password })
        : await authApi.register({
            email: email.trim(),
            password,
            display_name: displayName.trim() || null,
          });
      applyAuthSession(session);
      router.push('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === 'login' ? '登录失败' : '注册失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 overflow-y-auto bg-page px-6 py-8 lg:px-10">
      <div className="mx-auto grid w-full max-w-[980px] items-center gap-6 lg:grid-cols-[1fr_420px]">
        <div className="min-w-0">
          <div className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-sm bg-primary text-white shadow-sm">
            <Radar size={22} strokeWidth={2.4} />
          </div>
          <h1 className="mb-3 max-w-[560px] text-[30px] font-black leading-tight text-gray-900">
            把选题、收藏和创作流绑定到你的账号
          </h1>
          <p className="max-w-[560px] text-[14px] leading-7 text-gray-500">
            登录后可以稳定保存收藏、信源偏好和后续付费区权限。复盘、创作和个人工作台需要登录，管理入口仅管理员可见。
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Badge tone="primary">邮箱登录</Badge>
            <Badge tone="teal">免费版默认开通</Badge>
            <Badge tone="neutral">付费区预留</Badge>
          </div>
        </div>

        <Panel className="p-6 shadow-sm">
          <div className="mb-5 flex rounded-sm border border-gray-200 bg-gray-100 p-0.5">
            {[
              { key: 'login' as const, label: '登录' },
              { key: 'register' as const, label: '注册' },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  setMode(item.key);
                  setError(null);
                }}
                className={cx(
                  'flex-1 rounded-xs px-3 py-2 text-sm font-black transition',
                  mode === item.key ? 'bg-white text-primary shadow-sm' : 'text-gray-500 hover:text-gray-800',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {currentUser && (
            <div className="mb-4 rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal">
              当前已登录：{currentUser.display_name || currentUser.email}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3.5">
            {mode === 'register' && (
              <label className="block">
                <span className="mb-1.5 block text-xs font-black text-gray-500">昵称</span>
                <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                  <UserRound size={15} className="shrink-0 text-gray-400" />
                  <input
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                    placeholder="创作者昵称"
                    maxLength={100}
                  />
                </div>
              </label>
            )}

            <label className="block">
              <span className="mb-1.5 block text-xs font-black text-gray-500">邮箱</span>
              <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                <Mail size={15} className="shrink-0 text-gray-400" />
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                  placeholder="you@example.com"
                  type="email"
                  autoComplete="email"
                  required
                />
              </div>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-black text-gray-500">密码</span>
              <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                <LockKeyhole size={15} className="shrink-0 text-gray-400" />
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                  placeholder={mode === 'register' ? '至少 8 位' : '输入密码'}
                  type="password"
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                  required
                />
              </div>
            </label>

            {error && (
              <div className="rounded-sm border border-red-light bg-red-light px-3 py-2 text-xs font-bold text-red">
                {error}
              </div>
            )}

            <Button type="submit" variant="primary" disabled={!canSubmit || submitting} className="w-full">
              {submitting ? '处理中...' : mode === 'login' ? '登录' : '创建账号'}
              <ArrowRight size={14} />
            </Button>
          </form>

          {enabledOauth.length > 0 && (
            <>
              <div className="my-4 flex items-center gap-3 text-[11px] font-black text-gray-400">
                <span className="h-px flex-1 bg-gray-200" />
                <span>或</span>
                <span className="h-px flex-1 bg-gray-200" />
              </div>
              <div className="space-y-2">
                {enabledOauth.map((provider) => {
                  const meta = OAUTH_META[provider];
                  const { Icon } = meta;
                  return (
                    <button
                      key={provider}
                      type="button"
                      onClick={() => handleOauthLogin(provider)}
                      className="flex h-10 w-full items-center justify-center gap-2 rounded-sm border border-gray-200 bg-white text-sm font-bold text-gray-700 transition hover:border-gray-300 hover:bg-gray-50"
                    >
                      <Icon className="h-4 w-4" />
                      使用 {meta.label} 登录
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
