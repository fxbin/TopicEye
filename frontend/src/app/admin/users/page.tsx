'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  KeyRound,
  Ban,
  CheckCircle2,
  X,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel } from '@/components/ui';
import { usersApi } from '@/lib/api';
import type { UserListItem } from '@/lib/api';
import { formatDateTime } from '@/lib/datetime';

const PAGE_SIZE = 20;

type FilterRole = '' | 'user' | 'admin';
type FilterStatus = '' | 'active' | 'banned';

export default function UsersAdminPage() {
  const { currentUser, authLoading } = useAppContext();
  const [items, setItems] = useState<UserListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [filterRole, setFilterRole] = useState<FilterRole>('');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actingId, setActingId] = useState<number | null>(null);

  // 重置密码 Modal
  const [resetTarget, setResetTarget] = useState<UserListItem | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [resetting, setResetting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await usersApi.list({
        page,
        page_size: PAGE_SIZE,
        keyword: keyword || undefined,
        role: filterRole || undefined,
        is_active: filterStatus === 'active' ? true : filterStatus === 'banned' ? false : undefined,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载用户列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, keyword, filterRole, filterStatus]);

  useEffect(() => {
    if (currentUser?.role === 'admin') void load();
  }, [load, currentUser]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setKeyword(searchInput.trim());
  };

  const clearFilters = () => {
    setSearchInput('');
    setKeyword('');
    setFilterRole('');
    setFilterStatus('');
    setPage(1);
  };

  const runAction = async (id: number, fn: () => Promise<unknown>, successMsg: string) => {
    setActingId(id);
    setNotice(null);
    setError(null);
    try {
      await fn();
      setNotice(successMsg);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setActingId(null);
    }
  };

  const handleToggleRole = (u: UserListItem) => {
    const next = u.role === 'admin' ? 'user' : 'admin';
    const verb = next === 'admin' ? '设为管理员' : '降为普通用户';
    if (!confirm(`确定将「${u.email}」${verb}？`)) return;
    void runAction(u.id, () => usersApi.update(u.id, { role: next }), `已${verb}`);
  };

  const handleToggleBan = (u: UserListItem) => {
    const next = !u.is_active;
    const verb = next ? '封禁' : '解封';
    if (!confirm(`确定${verb}用户「${u.email}」？${next ? '该用户将立即无法登录。' : ''}`)) return;
    void runAction(u.id, () => usersApi.update(u.id, { is_active: next }), `已${verb}`);
  };

  const handleTogglePlan = (u: UserListItem) => {
    const next = u.plan === 'pro' ? 'free' : 'pro';
    if (!confirm(`确定将「${u.email}」套餐改为 ${next}？`)) return;
    void runAction(u.id, () => usersApi.update(u.id, { plan: next }), `套餐已改为 ${next}`);
  };

  const submitReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetTarget) return;
    if (newPassword.length < 8) {
      setError('新密码至少 8 位');
      return;
    }
    setResetting(true);
    setNotice(null);
    setError(null);
    try {
      const res = await usersApi.resetPassword(resetTarget.id, newPassword);
      setNotice(`已重置「${resetTarget.email}」的密码，撤销了 ${res.revoked_sessions} 个会话`);
      setResetTarget(null);
      setNewPassword('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重置密码失败');
    } finally {
      setResetting(false);
    }
  };

  // ── 页面级 admin 守卫 ──────────────────────────────────────────────
  if (authLoading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page">
        <Loader2 size={20} className="animate-spin text-gray-400" />
      </div>
    );
  }
  if (!currentUser || currentUser.role !== 'admin') {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page p-6">
        <Panel className="max-w-md p-6 text-center">
          <h2 className="mb-2 text-base font-semibold text-gray-900">需要管理员权限</h2>
          <p className="text-[13px] text-gray-500">用户管理仅对管理员开放。</p>
        </Panel>
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[1100px] space-y-5 pb-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-[26px] font-black text-gray-900">
              <ShieldCheck size={22} className="text-primary" />
              用户管理
            </h1>
            <p className="mt-1 text-sm text-gray-500">管理账号角色、套餐、状态与密码</p>
          </div>
          <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading} className="shrink-0">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            刷新
          </Button>
        </div>

        {(notice || error) && (
          <div
            className={`rounded-sm border px-3 py-2 text-[13px] ${
              error
                ? 'border-red-200 bg-red-50 text-red-700'
                : 'border-teal-200 bg-teal-50 text-teal-700'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span>{error || notice}</span>
              <button
                type="button"
                onClick={() => {
                  setNotice(null);
                  setError(null);
                }}
                className="shrink-0 text-current/70 hover:text-current"
              >
                <X size={14} />
              </button>
            </div>
          </div>
        )}

        {/* 搜索 + 筛选 */}
        <Panel className="p-4">
          <form onSubmit={handleSearch} className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[240px] flex-1">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="按邮箱或昵称搜索"
                className="h-9 w-full rounded-sm border border-gray-200 pl-9 pr-3 text-sm text-gray-800 outline-none focus:border-primary"
              />
            </div>
            <select
              value={filterRole}
              onChange={(e) => {
                setFilterRole(e.target.value as FilterRole);
                setPage(1);
              }}
              className="h-9 rounded-sm border border-gray-200 px-2 text-sm text-gray-700 outline-none focus:border-primary"
            >
              <option value="">全部角色</option>
              <option value="admin">管理员</option>
              <option value="user">普通用户</option>
            </select>
            <select
              value={filterStatus}
              onChange={(e) => {
                setFilterStatus(e.target.value as FilterStatus);
                setPage(1);
              }}
              className="h-9 rounded-sm border border-gray-200 px-2 text-sm text-gray-700 outline-none focus:border-primary"
            >
              <option value="">全部状态</option>
              <option value="active">启用</option>
              <option value="banned">停用</option>
            </select>
            <Button type="submit" variant="primary" className="h-9">
              <Search size={14} />
              搜索
            </Button>
            {(keyword || filterRole || filterStatus) && (
              <Button type="button" variant="ghost" onClick={clearFilters} className="h-9">
                清除
              </Button>
            )}
          </form>
        </Panel>

        {/* 用户表格 */}
        <Panel className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 size={20} className="animate-spin text-gray-400" />
            </div>
          ) : items.length === 0 ? (
            <div className="py-16 text-center text-sm text-gray-400">没有匹配的用户</div>
          ) : (
            <div className="overflow-x-auto">
              {/* 表头 */}
              <div className="grid grid-cols-[1.6fr_88px_88px_88px_120px_150px] gap-2 border-b border-gray-100 bg-gray-50/60 px-4 py-2.5 text-[11px] font-black uppercase tracking-wide text-gray-500">
                <div>邮箱</div>
                <div>角色</div>
                <div>套餐</div>
                <div>状态</div>
                <div>登录方式</div>
                <div>注册时间</div>
              </div>
              {items.map((u) => {
                const isSelf = u.id === currentUser.id;
                return (
                  <div
                    key={u.id}
                    className="grid grid-cols-[1.6fr_88px_88px_88px_120px_150px] items-center gap-2 border-b border-gray-50 px-4 py-3 text-[13px] last:border-b-0 hover:bg-gray-50/40"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-bold text-gray-900">{u.email}{isSelf && <span className="ml-1 text-[11px] text-primary">（你）</span>}</div>
                      {u.display_name && <div className="truncate text-[11px] text-gray-400">{u.display_name}</div>}
                    </div>
                    <div>
                      <Badge tone={u.role === 'admin' ? 'primary' : 'neutral'}>
                        {u.role === 'admin' ? '管理员' : '用户'}
                      </Badge>
                    </div>
                    <div>
                      <Badge tone={u.plan === 'pro' ? 'teal' : 'neutral'}>{u.plan}</Badge>
                    </div>
                    <div>
                      <Badge tone={u.is_active ? 'teal' : 'red'}>
                        {u.is_active ? '启用' : '停用'}
                      </Badge>
                    </div>
                    <div className="text-[11px] text-gray-500">
                      {u.oauth_providers.length > 0 ? u.oauth_providers.join(' / ') : u.has_password ? '密码' : '—'}
                    </div>
                    <div className="text-[11px] text-gray-400">{u.created_at ? formatDateTime(u.created_at) : '—'}</div>

                    {/* 操作行（占整行，跨列） */}
                    <div className="col-span-6 -mt-1 flex flex-wrap gap-1.5 pb-1">
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={actingId === u.id || isSelf}
                        onClick={() => handleToggleRole(u)}
                        className="h-7 px-2.5 text-[12px]"
                        title={isSelf ? '不能修改自己的角色' : ''}
                      >
                        {u.role === 'admin' ? '降为用户' : '设为管理员'}
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={actingId === u.id}
                        onClick={() => handleTogglePlan(u)}
                        className="h-7 px-2.5 text-[12px]"
                      >
                        套餐改 {u.plan === 'pro' ? 'free' : 'pro'}
                      </Button>
                      <Button
                        type="button"
                        variant={u.is_active ? 'ghost' : 'secondary'}
                        disabled={actingId === u.id || isSelf}
                        onClick={() => handleToggleBan(u)}
                        className="h-7 px-2.5 text-[12px]"
                        title={isSelf ? '不能封禁自己' : ''}
                      >
                        {u.is_active ? (
                          <><Ban size={12} className="mr-1" />封禁</>
                        ) : (
                          <><CheckCircle2 size={12} className="mr-1" />解封</>
                        )}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={actingId === u.id || !u.is_active}
                        onClick={() => {
                          setResetTarget(u);
                          setNewPassword('');
                          setError(null);
                        }}
                        className="h-7 px-2.5 text-[12px]"
                      >
                        <KeyRound size={12} className="mr-1" />
                        重置密码
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 分页 */}
          {total > PAGE_SIZE && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 px-4 py-3 text-[13px] text-gray-500">
              <span>
                第 {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, total)} 条，共 {total} 条
              </span>
              <div className="flex flex-wrap gap-1.5">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                  className="min-h-8 px-3.5 py-1.5 text-[13px] disabled:cursor-not-allowed"
                >
                  上一页
                </Button>
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 2)
                  .map((p, idx, arr) => {
                    const showEllipsis = idx > 0 && p - arr[idx - 1] > 1;
                    return (
                      <React.Fragment key={p}>
                        {showEllipsis && <span className="px-1 py-1.5 text-gray-400">…</span>}
                        <Button
                          type="button"
                          variant={p === page ? 'primary' : 'secondary'}
                          onClick={() => setPage(p)}
                          disabled={p === page}
                          className="min-h-8 px-3 py-1.5 text-[13px]"
                        >
                          {p}
                        </Button>
                      </React.Fragment>
                    );
                  })}
                <Button
                  type="button"
                  variant="secondary"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                  className="min-h-8 px-3.5 py-1.5 text-[13px] disabled:cursor-not-allowed"
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </Panel>
      </div>

      {/* 重置密码 Modal */}
      {resetTarget && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 p-4">
          <Panel className="w-full max-w-md p-6">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-base font-black text-gray-900">
                <KeyRound size={16} className="text-primary" />
                重置密码
              </h3>
              <button
                type="button"
                onClick={() => setResetTarget(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={18} />
              </button>
            </div>
            <p className="mb-4 text-[13px] text-gray-500">
              为用户 <span className="font-bold text-gray-700">{resetTarget.email}</span> 设定新密码。
              重置后该用户的所有登录会话将立即失效，需用新密码重新登录。
            </p>
            <form onSubmit={submitReset} className="space-y-3">
              <div>
                <label className="mb-1 block text-[12px] font-bold text-gray-600">新密码（至少 8 位，含字母和数字）</label>
                <input
                  type="text"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoFocus
                  placeholder="如 Abc12345"
                  className="h-9 w-full rounded-sm border border-gray-200 px-3 text-sm outline-none focus:border-primary"
                />
              </div>
              {error && <div className="rounded-sm border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{error}</div>}
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="ghost" onClick={() => setResetTarget(null)} disabled={resetting}>
                  取消
                </Button>
                <Button type="submit" variant="primary" disabled={resetting || newPassword.length < 8}>
                  {resetting ? <Loader2 size={14} className="animate-spin" /> : null}
                  确认重置
                </Button>
              </div>
            </form>
          </Panel>
        </div>
      )}
    </div>
  );
}
