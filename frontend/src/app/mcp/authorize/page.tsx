'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Radar, ShieldCheck, XCircle } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { mcpOAuthApi } from '@/lib/api';
import type { McpAuthorizeInfo } from '@/lib/api';
import { Badge, Button, Panel } from '@/components/ui';

type Status = 'loading' | 'ready' | 'error' | 'acting';

/**
 * MCP OAuth 同意页。
 *
 * MCP 客户端（Claude Code / ZCode 等）发起 /authorize 后，后端 302 到
 * 本页 ?request_id=xxx。页面按登录态分流：未登录跳 /login?returnTo=...
 * （登录后回来继续），已登录展示待授权应用与数据范围，用户「授权 /
 * 拒绝」后整页跳转回客户端回调地址（带一次性 code 或 access_denied）。
 *
 * 授权请求本身 10 分钟过期、一次性消费；重复进入/过期请求直接报错。
 */
export default function McpAuthorizePage() {
  const router = useRouter();
  const { currentUser } = useAppContext();
  const [status, setStatus] = useState<Status>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [info, setInfo] = useState<McpAuthorizeInfo | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      const requestId = new URLSearchParams(window.location.search).get('request_id');
      if (!requestId) {
        if (!cancelled) {
          setErrorMsg('缺少授权请求参数，请从 AI 客户端重新发起连接');
          setStatus('error');
        }
        return;
      }

      try {
        const result = await mcpOAuthApi.authorizeInfo(requestId);
        if (!cancelled) {
          setInfo(result);
          setStatus('ready');
        }
      } catch (err) {
        if (cancelled) return;
        const apiErr = err as Error & { status?: number; isAuthError?: boolean };
        if (apiErr.isAuthError || apiErr.status === 401) {
          // 未登录：带上完整当前地址作为 returnTo，登录后回来继续授权
          const here = encodeURIComponent(window.location.pathname + window.location.search);
          router.replace(`/login?returnTo=${here}`);
          return;
        }
        setErrorMsg(apiErr.status === 404 ? '授权请求不存在、已过期或已被处理，请从 AI 客户端重新发起' : apiErr.message);
        setStatus('error');
      }
    }

    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const decide = async (action: 'approve' | 'deny') => {
    if (!info || status === 'acting') return;
    setStatus('acting');
    try {
      const decision = action === 'approve'
        ? await mcpOAuthApi.approve(info.request_id)
        : await mcpOAuthApi.deny(info.request_id);
      // 整页跳转回 MCP 客户端回调地址（带 code / error 参数）
      window.location.href = decision.redirect_to;
    } catch (err) {
      const apiErr = err as Error & { status?: number };
      setErrorMsg(apiErr.status === 404 ? '授权请求已过期或已被处理，请从 AI 客户端重新发起' : apiErr.message);
      setStatus('error');
    }
  };

  return (
    <div className="flex h-full min-h-0 items-center justify-center bg-page px-6 py-8">
      <Panel className="w-full max-w-md p-8 shadow-sm">
        {status === 'loading' && (
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-sm bg-primary text-white shadow-sm">
              <Radar size={22} strokeWidth={2.4} className="animate-pulse" />
            </div>
            <p className="text-sm font-black text-gray-700">正在加载授权请求...</p>
            <p className="mt-1 text-xs text-gray-400">请稍候</p>
          </div>
        )}

        {(status === 'ready' || status === 'acting') && info && (
          <div className="flex flex-col">
            <div className="mb-4 flex items-center gap-3">
              <div className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-sm bg-primary text-white shadow-sm">
                <ShieldCheck size={22} strokeWidth={2.4} />
              </div>
              <div className="min-w-0">
                <h1 className="text-lg font-black leading-tight text-gray-900">连接 AI 客户端</h1>
                <p className="text-xs text-gray-400">TopicEye 选题雷达 · MCP 授权</p>
              </div>
            </div>

            <div className="mb-4 rounded-sm border border-gray-200 bg-gray-50 px-4 py-3">
              <p className="text-xs font-black text-gray-500">授权对象</p>
              <p className="mt-1 truncate text-[15px] font-black text-gray-900" title={info.client_name}>
                {info.client_name}
              </p>
              {info.redirect_host && (
                <p className="mt-1 text-xs text-gray-400">回调地址：{info.redirect_host}</p>
              )}
              {/* DCR 开放注册，客户端名可任意取（含仿冒官方）——知情权必须显式给出 */}
              <p className="mt-2 text-xs font-bold text-amber-600">
                该应用为未经 TopicEye 审核的第三方客户端，请确认你信任它再授权。
              </p>
            </div>

            <div className="mb-5 space-y-2 text-[13px] leading-6 text-gray-600">
              <p>授权后，该客户端可以代表你：</p>
              <ul className="space-y-1.5">
                <li className="flex items-start gap-2">
                  <Badge tone="teal">读</Badge>
                  <span>读取今日精选选题、选题日报（缺失时会自动生成当日快照）、话题趋势与关键词</span>
                </li>
                <li className="flex items-start gap-2">
                  <Badge tone="primary">算</Badge>
                  <span>对你提交的候选选题跑六维打分并返回评分明细</span>
                </li>
              </ul>
              <p className="text-xs text-gray-400">
                授权可随时在 AI 客户端断开（token 撤销即失效）；不会暴露你的登录密码。
                {currentUser ? ` 当前账号：${currentUser.display_name || currentUser.email}。` : ''}
              </p>
            </div>

            <div className="flex gap-2.5">
              <Button
                variant="primary"
                onClick={() => decide('approve')}
                disabled={status === 'acting'}
                className="flex-1"
              >
                {status === 'acting' ? '处理中...' : '授权'}
                <ArrowRight size={14} />
              </Button>
              <Button
                variant="secondary"
                onClick={() => decide('deny')}
                disabled={status === 'acting'}
                className="flex-1"
              >
                拒绝
              </Button>
            </div>
          </div>
        )}

        {status === 'error' && (
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-sm bg-red-light text-red">
              <XCircle size={22} strokeWidth={2.4} />
            </div>
            <p className="mb-1 text-sm font-black text-gray-800">无法完成授权</p>
            <p className="mb-5 max-w-xs text-xs leading-6 text-gray-500">{errorMsg}</p>
            <Button variant="secondary" onClick={() => router.replace('/')}>
              返回首页
              <ArrowRight size={14} />
            </Button>
          </div>
        )}
      </Panel>
    </div>
  );
}
