/**
 * MCP OAuth 同意页 API（后端 app/api/v1/mcp_oauth.py）。
 *
 * 浏览器弹窗登录流程中 /mcp/authorize 同意页的交互面：
 * - authorizeInfo  展示待授权客户端（client_name / 回调主机 / scope）
 * - approve/deny   用户决定，返回带 code 或 error=access_denied 的回调地址
 *
 * 会话通过 HttpOnly cookie（request() credentials: 'include'）认证，
 * 401 由 _core 的 refresh 机制兜底，仍 401 时页面跳登录。
 */

import { request } from './_core';

export interface McpAuthorizeInfo {
  request_id: string;
  client_name: string;
  client_uri: string | null;
  scopes: string[];
  redirect_host: string;
}

export interface McpAuthorizeDecision {
  redirect_to: string;
}

export const mcpOAuthApi = {
  authorizeInfo: (requestId: string) =>
    request<McpAuthorizeInfo>(`/mcp-oauth/authorize-info?request_id=${encodeURIComponent(requestId)}`),

  approve: (requestId: string) =>
    request<McpAuthorizeDecision>('/mcp-oauth/approve', {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),

  deny: (requestId: string) =>
    request<McpAuthorizeDecision>('/mcp-oauth/deny', {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),
};
