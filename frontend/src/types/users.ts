/**
 * 用户管理相关类型（admin 视角）。
 */

export interface UserListItem {
  id: number;
  email: string;
  display_name: string | null;
  plan: string;
  role: string;
  is_active: boolean;
  has_password: boolean;
  oauth_providers: string[];
  created_at: string | null;
}

export interface UserListResponse {
  items: UserListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserUpdatePayload {
  role?: 'user' | 'admin';
  is_active?: boolean;
  /** 仅允许 free / pro 互转 */
  plan?: 'free' | 'pro';
}

export interface UserCreatePayload {
  email: string;
  password: string;
  display_name?: string;
  role?: 'user' | 'admin';
  plan?: 'free' | 'pro';
  is_active?: boolean;
}

export interface UserCreateResponse {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
  plan: string;
  is_active: boolean;
  message: string;
}
