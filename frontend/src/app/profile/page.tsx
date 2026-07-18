'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  PlugZap,
  RefreshCw,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  UserRound,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { integrationsApi, apiTokensApi, authApi } from '@/lib/api';
import type { ApiTokenItem } from '@/lib/api';
import type { IntegrationStatus, WeReadSyncResult } from '@/types';
import { formatDateTime } from '@/lib/datetime';

const DEFAULT_API_URL_PLACEHOLDER = 'https://weread.example.com/api';

function formatTime(value?: string | null) {
  return value ? formatDateTime(value, true) : '尚未同步';
}

function CopyCommandButton({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border border-gray-200 bg-white text-gray-500 transition hover:border-primary-border hover:text-primary"
      title={copied ? '已复制' : '复制命令'}
    >
      {copied ? <CheckCircle2 size={15} /> : <Copy size={15} />}
    </button>
  );
}

function CommandRow({ label, command }: { label: string; command: string }) {
  return (
    <div className="grid gap-2 rounded-sm border border-gray-200 bg-gray-50 p-3 sm:grid-cols-[116px_1fr_auto] sm:items-center">
      <div className="text-xs font-black text-gray-500">{label}</div>
      <code className="min-w-0 overflow-x-auto whitespace-nowrap rounded-xs bg-white px-2.5 py-2 font-mono text-xs font-bold text-gray-800">
        {command}
      </code>
      <CopyCommandButton command={command} />
    </div>
  );
}

export default function ProfilePage() {
  const router = useRouter();
  const { currentUser, authLoading, refreshCounts } = useAppContext();
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<WeReadSyncResult | null>(null);
  const [apiTokens, setApiTokens] = useState<ApiTokenItem[]>([]);
  const [loadingTokens, setLoadingTokens] = useState(true);
  const [tokenName, setTokenName] = useState('');
  const [creatingToken, setCreatingToken] = useState(false);
  const [newTokenSecret, setNewTokenSecret] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const [tokenNotice, setTokenNotice] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  // 自助改密
  const [pwForm, setPwForm] = useState({ old: '', next: '', confirm: '' });
  const [savingPw, setSavingPw] = useState(false);
  const [pwNotice, setPwNotice] = useState<string | null>(null);
  const [pwError, setPwError] = useState<string | null>(null);

  const docsUrl = status?.docs_url || 'https://weread.qq.com/r/weread-skills';
  const canSave = apiKey.trim().length >= 8 && !saving;
  const canSync = Boolean(status?.configured) && !syncing;

  const readiness = useMemo(() => {
    if (!status?.configured) {
      return { label: '未配置', tone: 'amber' as const, text: '先保存微信读书 API Key。' };
    }
    if (!status.sync_endpoint_configured) {
      return { label: '待接入', tone: 'amber' as const, text: 'API Key 已保存，后端还未配置 WEREAD_SKILL_API_URL。' };
    }
    return { label: '可同步', tone: 'teal' as const, text: 'Key 与同步 endpoint 均已配置。' };
  }, [status]);

  const loadStatus = useCallback(async () => {
    if (!currentUser) {
      setLoadingStatus(false);
      return;
    }
    setLoadingStatus(true);
    setError(null);
    try {
      setStatus(await integrationsApi.getWeRead());
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取微信读书配置失败');
    } finally {
      setLoadingStatus(false);
    }
  }, [currentUser]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const loadTokens = useCallback(async () => {
    if (!currentUser) {
      setLoadingTokens(false);
      return;
    }
    setLoadingTokens(true);
    setTokenError(null);
    try {
      const result = await apiTokensApi.list();
      setApiTokens(result.tokens);
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : '读取 API Token 失败');
    } finally {
      setLoadingTokens(false);
    }
  }, [currentUser]);

  useEffect(() => {
    void loadTokens();
  }, [loadTokens]);

  const handleCreateToken = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = tokenName.trim();
    if (!name || creatingToken) return;
    setCreatingToken(true);
    setTokenError(null);
    setTokenNotice(null);
    setNewTokenSecret(null);
    try {
      const result = await apiTokensApi.create({ name });
      setNewTokenSecret(result.token);
      setTokenNotice(`Token「${name}」已创建，明文仅显示一次，请立即复制保存。`);
      setTokenName('');
      await loadTokens();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : '创建 API Token 失败');
    } finally {
      setCreatingToken(false);
    }
  };

  const handleRevokeToken = async (id: number, name: string) => {
    if (revokingId || !confirm(`确定撤销 Token「${name}」？撤销后该 Token 立即失效。`)) return;
    setRevokingId(id);
    setTokenError(null);
    try {
      await apiTokensApi.revoke(id);
      await loadTokens();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : '撤销 Token 失败');
    } finally {
      setRevokingId(null);
    }
  };

  const handleDeleteToken = async (id: number, name: string) => {
    if (revokingId || !confirm(`确定删除 Token「${name}」？`)) return;
    setRevokingId(id);
    setTokenError(null);
    try {
      await apiTokensApi.remove(id);
      await loadTokens();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : '删除 Token 失败');
    } finally {
      setRevokingId(null);
    }
  };

  const canSavePw =
    pwForm.old.length >= 1 &&
    pwForm.next.length >= 8 &&
    pwForm.next === pwForm.confirm &&
    !savingPw;

  const handleChangePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSavePw) return;
    setSavingPw(true);
    setPwNotice(null);
    setPwError(null);
    try {
      const res = await authApi.changePassword(pwForm.old, pwForm.next);
      setPwNotice(res.message || '密码修改成功');
      setPwForm({ old: '', next: '', confirm: '' });
    } catch (err) {
      setPwError(err instanceof Error ? err.message : '密码修改失败');
    } finally {
      setSavingPw(false);
    }
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    setSyncResult(null);
    try {
      const next = await integrationsApi.updateWeRead({ api_key: apiKey.trim() });
      setStatus(next);
      setApiKey('');
      setNotice('微信读书 API Key 已保存。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (clearing) return;
    setClearing(true);
    setError(null);
    setNotice(null);
    setSyncResult(null);
    try {
      setStatus(await integrationsApi.clearWeRead());
      setApiKey('');
      setNotice('微信读书 API Key 已清除。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '清除失败');
    } finally {
      setClearing(false);
    }
  };

  const handleSync = async () => {
    if (!canSync) return;
    setSyncing(true);
    setError(null);
    setNotice(null);
    setSyncResult(null);
    try {
      const result = await integrationsApi.syncWeRead(50);
      setSyncResult(result);
      setNotice(result.message);
      refreshCounts();
      await loadStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : '同步失败';
      setError(message);
      await loadStatus();
    } finally {
      setSyncing(false);
    }
  };

  if (authLoading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page">
        <div className="inline-flex items-center gap-2 text-sm font-bold text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          正在检查登录状态
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <div className="flex h-full min-h-0 overflow-y-auto bg-page px-6 py-8 lg:px-10">
        <Panel className="mx-auto flex w-full max-w-[620px] flex-col items-start justify-center p-7">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-sm bg-primary-light text-primary">
            <UserRound size={22} />
          </div>
          <h1 className="mb-2 text-2xl font-black text-gray-900">需要登录后配置个人集成</h1>
          <p className="mb-5 text-sm leading-7 text-gray-500">
            微信读书 API Key 属于个人凭据，只会绑定到你的账号，不会显示给其他用户。
          </p>
          <Button type="button" variant="primary" onClick={() => router.push('/login')}>
            去登录
            <ArrowRight size={14} />
          </Button>
        </Panel>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[1120px] space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Badge tone={currentUser.plan === 'free' ? 'neutral' : 'primary'}>
                {currentUser.plan === 'free' ? '免费版' : '付费版'}
              </Badge>
              <Badge tone={readiness.tone}>{readiness.label}</Badge>
            </div>
            <h1 className="text-[26px] font-black leading-tight text-gray-900">个人中心</h1>
            <p className="mt-2 max-w-[720px] text-sm leading-7 text-gray-500">
              管理账号、外部素材接入和同步状态。微信读书素材会进入内容流，后续可参与选题、收藏和创作方案生成。
            </p>
          </div>
          <Button type="button" onClick={loadStatus} disabled={loadingStatus} className="shrink-0">
            {loadingStatus ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            刷新状态
          </Button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
          <Panel className="p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-black text-gray-500">当前账号</div>
                <div className="mt-1 truncate text-base font-black text-gray-900">
                  {currentUser.display_name || currentUser.email}
                </div>
              </div>
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-teal-light text-teal">
                <ShieldCheck size={20} />
              </div>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-500">邮箱</span>
                <span className="min-w-0 truncate font-bold text-gray-800">{currentUser.email}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-500">套餐</span>
                <span className="font-bold text-gray-800">{currentUser.plan === 'free' ? '免费版' : currentUser.plan}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-500">创建时间</span>
                <span className="font-bold text-gray-800">{formatTime(currentUser.created_at)}</span>
              </div>
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <KeyRound size={18} className="text-primary" />
              <h2 className="text-lg font-black text-gray-900">账号安全</h2>
            </div>
            <p className="mb-4 max-w-[560px] text-sm leading-6 text-gray-500">
              修改密码需验证旧密码。修改成功后，其他设备的登录状态会立即失效，当前设备保持登录。
            </p>
            <form onSubmit={handleChangePassword} className="max-w-[420px] space-y-3">
              <div>
                <label className="mb-1 block text-[12px] font-bold text-gray-600">旧密码</label>
                <input
                  type="password"
                  value={pwForm.old}
                  onChange={(e) => setPwForm((prev) => ({ ...prev, old: e.target.value }))}
                  autoComplete="current-password"
                  className="h-9 w-full rounded-sm border border-gray-200 px-3 text-sm outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-bold text-gray-600">新密码（至少 8 位，含字母和数字）</label>
                <input
                  type="password"
                  value={pwForm.next}
                  onChange={(e) => setPwForm((prev) => ({ ...prev, next: e.target.value }))}
                  autoComplete="new-password"
                  className="h-9 w-full rounded-sm border border-gray-200 px-3 text-sm outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-bold text-gray-600">确认新密码</label>
                <input
                  type="password"
                  value={pwForm.confirm}
                  onChange={(e) => setPwForm((prev) => ({ ...prev, confirm: e.target.value }))}
                  autoComplete="new-password"
                  className="h-9 w-full rounded-sm border border-gray-200 px-3 text-sm outline-none focus:border-primary"
                />
                {pwForm.confirm && pwForm.next !== pwForm.confirm && (
                  <p className="mt-1 text-[11px] text-red-600">两次输入的新密码不一致</p>
                )}
              </div>
              {pwError && (
                <div className="rounded-sm border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{pwError}</div>
              )}
              {pwNotice && (
                <div className="rounded-sm border border-teal-200 bg-teal-50 px-3 py-2 text-[12px] text-teal-700">{pwNotice}</div>
              )}
              <Button type="submit" variant="primary" disabled={!canSavePw} className="h-9">
                {savingPw ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                修改密码
              </Button>
            </form>
          </Panel>

          <Panel className="p-5">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <BookOpen size={18} className="text-primary" />
                  <h2 className="text-lg font-black text-gray-900">微信读书素材</h2>
                </div>
                <p className="text-sm leading-6 text-gray-500">{readiness.text}</p>
              </div>
              <Badge tone={status?.configured ? 'teal' : 'neutral'}>
                {status?.api_key_hint ? `Key ${status.api_key_hint}` : '未保存 Key'}
              </Badge>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                  <KeyRound size={14} />
                  API Key
                </div>
                <div className={cx('text-sm font-black', status?.configured ? 'text-teal' : 'text-gray-700')}>
                  {status?.configured ? '已保存' : '未配置'}
                </div>
              </div>
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                  <PlugZap size={14} />
                  同步 Endpoint
                </div>
                <div className={cx('text-sm font-black', status?.sync_endpoint_configured ? 'text-teal' : 'text-amber')}>
                  {status?.sync_endpoint_configured ? '已配置' : '未配置'}
                </div>
              </div>
              <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                  <RefreshCw size={14} />
                  最近同步
                </div>
                <div className="truncate text-sm font-black text-gray-800">{formatTime(status?.last_sync_at)}</div>
              </div>
            </div>

            <form onSubmit={handleSave} className="mt-5 grid gap-3 md:grid-cols-[1fr_auto_auto]">
              <label className="block">
                <span className="mb-1.5 block text-xs font-black text-gray-500">微信读书 API Key</span>
                <input
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                  placeholder={status?.configured ? '输入新 Key 后可覆盖当前配置' : '粘贴微信读书 API Key'}
                  type="password"
                  autoComplete="off"
                />
              </label>
              <div className="flex items-end">
                <Button type="submit" variant="primary" disabled={!canSave} className="w-full md:w-auto">
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                  保存 Key
                </Button>
              </div>
              <div className="flex items-end">
                <Button
                  type="button"
                  variant="danger"
                  onClick={handleClear}
                  disabled={clearing || !status?.configured}
                  className="w-full md:w-auto"
                >
                  {clearing ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                  清除
                </Button>
              </div>
            </form>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button type="button" variant="success" onClick={handleSync} disabled={!canSync}>
                {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {status?.configured && !status.sync_endpoint_configured ? '检查同步服务' : '同步 50 条素材'}
              </Button>
              {docsUrl && (
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-700 transition hover:border-primary-border hover:text-primary"
                >
                  官方文档
                  <ExternalLink size={14} />
                </a>
              )}
            </div>

            {(notice || error || syncResult || status?.last_sync_error) && (
              <div className="mt-4 space-y-2">
                {notice && (
                  <div className="rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal">
                    {notice}
                  </div>
                )}
                {error && (
                  <div className="rounded-sm border border-amber-border bg-amber-light px-3 py-2 text-xs font-bold text-amber">
                    {error}
                  </div>
                )}
                {syncResult && (
                  <div className="grid gap-2 text-xs sm:grid-cols-3">
                    <div className="rounded-sm bg-gray-50 px-3 py-2 font-bold text-gray-600">拉取 {syncResult.fetched}</div>
                    <div className="rounded-sm bg-gray-50 px-3 py-2 font-bold text-gray-600">新增 {syncResult.new}</div>
                    <div className="rounded-sm bg-gray-50 px-3 py-2 font-bold text-gray-600">重复 {syncResult.duplicates}</div>
                  </div>
                )}
                {!error && status?.last_sync_error && (
                  <div className="rounded-sm border border-red-light bg-red-light px-3 py-2 text-xs font-bold text-red">
                    上次同步错误：{status.last_sync_error}
                  </div>
                )}
              </div>
            )}
          </Panel>
        </div>

        <Panel className="p-5">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <TerminalSquare size={18} className="text-primary" />
                <h2 className="text-lg font-black text-gray-900">Agent 接入</h2>
              </div>
              <p className="text-sm leading-6 text-gray-500">
                安装 TopicEye 的读取 skill，让外部 Agent（ZCode / Claude）在对话中自主查询今日精选、日报与趋势。
                先创建一个 API Token，再按下方命令安装 skill 并配置环境变量。
              </p>
            </div>
            <Badge tone={apiTokens.length > 0 ? 'teal' : 'neutral'}>
              {apiTokens.length > 0 ? `${apiTokens.length} 个 Token` : '未创建'}
            </Badge>
          </div>

          {tokenError && (
            <div className="mb-4 rounded-sm border border-red-light bg-red-light px-3 py-2 text-xs font-bold text-red">
              {tokenError}
            </div>
          )}
          {tokenNotice && (
            <div className="mb-4 rounded-sm border border-teal bg-teal/10 px-3 py-2 text-xs font-bold text-teal">
              {tokenNotice}
            </div>
          )}

          {newTokenSecret && (
            <div className="mb-4 rounded-sm border border-amber/40 bg-amber/10 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-black text-amber">
                <ShieldCheck size={14} />
                新 Token 明文（仅显示一次，请立即复制）
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded bg-white px-2 py-1.5 text-xs text-gray-800">{newTokenSecret}</code>
                <Button
                  type="button"
                  className="shrink-0 px-2 py-1"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(newTokenSecret);
                    } catch {
                      /* ignore */
                    }
                  }}
                >
                  <Copy size={14} /> 复制
                </Button>
              </div>
            </div>
          )}

          <form onSubmit={handleCreateToken} className="mb-5 grid gap-3 md:grid-cols-[1fr_auto]">
            <label className="block">
              <span className="mb-1.5 block text-xs font-black text-gray-500">Token 名称</span>
              <input
                value={tokenName}
                onChange={(event) => setTokenName(event.target.value)}
                className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                placeholder="如：我的 Agent / CI 脚本"
                maxLength={100}
              />
            </label>
            <div className="flex items-end">
              <Button type="submit" disabled={!tokenName.trim() || creatingToken}>
                {creatingToken ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                创建 Token
              </Button>
            </div>
          </form>

          <div className="mb-3 text-xs font-black text-gray-500">已创建的 Token</div>
          {loadingTokens ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={14} className="animate-spin" /> 加载中…
            </div>
          ) : apiTokens.length === 0 ? (
            <div className="rounded-sm border border-dashed border-gray-200 px-3 py-6 text-center text-sm text-gray-400">
              还没有 API Token，创建一个让 Agent 开始读取你的选题数据。
            </div>
          ) : (
            <div className="grid gap-2">
              {apiTokens.map((token) => (
                <div
                  key={token.id}
                  className="flex flex-wrap items-center gap-3 rounded-sm border border-gray-200 bg-gray-50 px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-bold text-gray-800">{token.name}</span>
                      {token.revoked_at && (
                        <Badge tone="red">已撤销</Badge>
                      )}
                      {!token.revoked_at && token.expires_at && new Date(token.expires_at) < new Date() && (
                        <Badge tone="neutral">已过期</Badge>
                      )}
                    </div>
                    <div className="mt-0.5 text-xs text-gray-500">
                      <code className="font-mono">{token.token_prefix}…</code>
                      {' · '}创建 {formatTime(token.created_at)}
                      {token.last_used_at ? ` · 最近使用 ${formatTime(token.last_used_at)}` : ' · 尚未使用'}
                      {token.expires_at ? ` · 过期 ${formatTime(token.expires_at)}` : ''}
                    </div>
                  </div>
                  {!token.revoked_at && (
                    <Button
                      type="button"
                      className="shrink-0 px-2 py-1"
                      variant="ghost"
                      disabled={revokingId === token.id}
                      onClick={() => handleRevokeToken(token.id, token.name)}
                    >
                      {revokingId === token.id ? <Loader2 size={14} className="animate-spin" /> : null}
                      撤销
                    </Button>
                  )}
                  <Button
                    type="button"
                    className="shrink-0 px-2 py-1"
                    variant="ghost"
                    disabled={revokingId === token.id}
                    onClick={() => handleDeleteToken(token.id, token.name)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                <TerminalSquare size={14} />
                1. 安装 skill
              </div>
              <code className="block overflow-x-auto whitespace-pre rounded bg-white px-3 py-2 text-xs leading-5 text-gray-700">
{`npx skills add ${typeof window !== 'undefined' ? window.location.origin : '$TOPICEYE_HOST'} -g`}
              </code>
              <div className="mt-2 text-xs text-gray-400">
                在你的 Agent 环境（ZCode / Claude 所在机器）执行一次即可。TopicEye 会通过标准协议自动暴露 skill。
              </div>
            </div>

            <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-black text-gray-500">
                <KeyRound size={14} />
                2. 配置环境变量
              </div>
              <code className="block overflow-x-auto whitespace-pre rounded bg-white px-3 py-2 text-xs leading-5 text-gray-700">
{`export TOPICEYE_API_URL="${typeof window !== 'undefined' ? window.location.origin : ''}"
export TOPICEYE_API_TOKEN="${newTokenSecret || '<上方创建的 Token>'}"`}
              </code>
              <div className="mt-2 text-xs text-gray-400">
                写入 shell 配置（<code className="font-mono">~/.zshrc</code> / <code className="font-mono">~/.bashrc</code>）后重启 Agent。Token 即上方创建的个人 API Token。
              </div>
            </div>
          </div>

          <div className="mt-3 rounded-sm border border-teal/30 bg-teal/5 px-3 py-2 text-xs leading-5 text-teal">
            <ShieldCheck size={13} className="mr-1 inline" />
            装好后，在 Agent 对话中直接问「今天有什么值得写的选题」「看看选题日报」即可，Agent 会自动调用 TopicEye 读取数据。
          </div>
        </Panel>
      </div>
    </div>
  );
}
