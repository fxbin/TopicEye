/**
 * Admin 用户管理 API。
 * 与后端 backend/app/api/v1/users.py 对齐。
 */

import { request } from './_core';
import type { UserListResponse, UserUpdatePayload } from '@/types/users';

export interface ListUsersParams {
  page?: number;
  page_size?: number;
  keyword?: string;
  role?: string;
  plan?: string;
  is_active?: boolean;
}

export const usersApi = {
  list(params: ListUsersParams = {}): Promise<UserListResponse> {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.page_size) qs.set('page_size', String(params.page_size));
    if (params.keyword) qs.set('keyword', params.keyword);
    if (params.role) qs.set('role', params.role);
    if (params.plan) qs.set('plan', params.plan);
    if (typeof params.is_active === 'boolean') qs.set('is_active', String(params.is_active));
    const query = qs.toString();
    return request(query ? `/admin/users?${query}` : '/admin/users');
  },

  update(id: number, data: UserUpdatePayload): Promise<{ id: number; email: string; role: string; is_active: boolean; plan: string; message: string }> {
    return request(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  },

  resetPassword(id: number, newPassword: string): Promise<{ id: number; email: string; revoked_sessions: number; message: string }> {
    return request(`/admin/users/${id}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    });
  },
};
