'use client';

import React, { useEffect, useState } from 'react';
import { CheckCircle2, ExternalLink, KeyRound, Loader2, Mail, Server, Settings } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { settingsApi } from '@/lib/api';
import type { EmailProviderConfig } from '@/lib/api/_analytics';
import { Badge, Button, Panel } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner } from '@/components/admin-ui';
import { LoadingState } from '@/components/StateView';

const DEFAULT_FROM_NAME = 'TopicEye';

/** Brevo 官方资源链接 */
const BREVO_LINKS = {
  /** 注册账号 */
  signup: 'https://www.brevo.com/',
  /** 获取 API Key */
  apiKey: 'https://app.brevo.com/settings/keys/api',
  /** 域名认证（SPF/DKIM） */
  domains: 'https://app.brevo.com/senders/domains',
};

/** 配置说明项 */
const CONFIG_NOTES: Record<string, string[]> = {
  brevo: [
    'Brevo 免费额度：300 封/天（约 9000 封/月），无需信用卡',
    '发件人邮箱需在 Brevo 后台完成域名认证（SPF/DKIM）',
    'API Key 以加密方式存储，不会明文保存',
    '配置完成后，用户注册时需先获取邮箱验证码',
  ],
  smtp: [
    '支持任意标准 SMTP 服务器（腾讯企业邮、Gmail、自建 Postfix 等）',
    '端口 465 使用 SSL 直连；端口 587 使用 STARTTLS',
    'SMTP 密码以加密方式存储，不会明文保存',
    '部分邮箱（如 QQ、163）需使用授权码而非登录密码',
  ],
};

export default function AdminSettingsPage() {
  const { currentUser } = useAppContext();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<EmailProviderConfig | null>(null);
  const [provider, setProvider] = useState('brevo');
  const [fromEmail, setFromEmail] = useState('');
  const [fromName, setFromName] = useState(DEFAULT_FROM_NAME);
  const [apiKey, setApiKey] = useState('');
  // SMTP 专属字段
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpUseSsl, setSmtpUseSsl] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .getEmailProvider()
      .then((data) => {
        setConfig(data);
        setProvider(data.provider);
        setFromEmail(data.from_email);
        setFromName(data.from_name);
        setSmtpHost(data.smtp_host);
        setSmtpPort(data.smtp_port || 587);
        setSmtpUsername(data.smtp_username);
        setSmtpUseSsl(data.smtp_use_ssl);
      })
      .catch(() => setError('加载配置失败'))
      .finally(() => setLoading(false));
  }, []);

  // 切换 provider 时联动 SSL 默认端口
  const handleProviderChange = (value: string) => {
    setProvider(value);
    if (value === 'smtp') {
      // 切到 SMTP 时，若端口为默认 587 保持不变；用户可自行改 465
      if (smtpPort === 587 && !smtpUseSsl) setSmtpUseSsl(false);
    }
  };

  // 切换 SSL 时联动常用端口
  const handleSslToggle = (checked: boolean) => {
    setSmtpUseSsl(checked);
    if (checked && smtpPort === 587) setSmtpPort(465);
    if (!checked && smtpPort === 465) setSmtpPort(587);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await settingsApi.updateEmailProvider({
        provider,
        from_email: fromEmail,
        from_name: fromName,
        api_key: apiKey,
        smtp_host: smtpHost,
        smtp_port: smtpPort,
        smtp_username: smtpUsername,
        smtp_password: smtpPassword,
        smtp_use_ssl: smtpUseSsl,
      });
      setApiKey('');
      setSmtpPassword('');
      setNotice('保存成功');
      const fresh = await settingsApi.getEmailProvider();
      setConfig(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  // admin 守卫已收敛到 app/admin/layout.tsx

  if (loading) {
    return (
      <AdminPageShell maxWidth={860}>
        <LoadingState label="加载中…" minHeight="200px" panel />
      </AdminPageShell>
    );
  }

  const isBrevo = provider === 'brevo';
  const isSmtp = provider === 'smtp';
  const notes = CONFIG_NOTES[provider] || [];

  return (
    <AdminPageShell maxWidth={860}>
      <AdminPageHeader
        title="系统设置"
        icon={Settings}
        description="配置系统级邮件服务，用于注册验证码等事务邮件发送"
      />

        <Panel className="p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-base font-black text-gray-900">邮件服务</h2>
            {config?.api_key_configured || config?.smtp_password_configured ? (
              <Badge tone="teal">
                <CheckCircle2 size={12} className="mr-1" />
                已配置
              </Badge>
            ) : (
              <Badge tone="amber">未配置</Badge>
            )}
          </div>

          {/* Provider 选择 */}
          <label className="block">
            <span className="mb-1.5 block text-xs font-black text-gray-500">邮件服务商</span>
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none focus:border-primary-border focus:ring-2 focus:ring-primary-light"
            >
              {(config?.supported_providers || ['brevo', 'smtp']).map((p) => (
                <option key={p} value={p}>
                  {p === 'brevo' ? 'Brevo（免费 300 封/天，API 模式）' : '自定义 SMTP（企业邮箱/自建服务器）'}
                </option>
              ))}
            </select>
          </label>

          {/* Brevo 官方指引 */}
          {isBrevo && (
            <div className="mt-3 rounded-sm border border-blue-100 bg-blue-50 px-3 py-2.5">
              <p className="mb-1.5 text-xs font-black text-blue-700">Brevo 配置指引</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <a href={BREVO_LINKS.signup} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 hover:underline">
                  <ExternalLink size={11} /> 注册 Brevo 账号
                </a>
                <a href={BREVO_LINKS.apiKey} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 hover:underline">
                  <ExternalLink size={11} /> 获取 API Key
                </a>
                <a href={BREVO_LINKS.domains} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 hover:underline">
                  <ExternalLink size={11} /> 域名认证（SPF/DKIM）
                </a>
              </div>
            </div>
          )}

          {/* 通用字段：发件人 */}
          <label className="mt-4 block">
            <span className="mb-1.5 block text-xs font-black text-gray-500">发件人邮箱</span>
            <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
              <Mail size={15} className="shrink-0 text-gray-400" />
              <input
                value={fromEmail}
                onChange={(e) => setFromEmail(e.target.value)}
                type="email"
                placeholder="noreply@yourdomain.com"
                className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
              />
            </div>
          </label>

          <label className="mt-4 block">
            <span className="mb-1.5 block text-xs font-black text-gray-500">发件人名称</span>
            <input
              value={fromName}
              onChange={(e) => setFromName(e.target.value)}
              className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none focus:border-primary-border focus:ring-2 focus:ring-primary-light"
            />
          </label>

          {/* Brevo 专属：API Key */}
          {isBrevo && (
            <label className="mt-4 block">
              <span className="mb-1.5 block text-xs font-black text-gray-500">API Key</span>
              <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                <KeyRound size={15} className="shrink-0 text-gray-400" />
                <input
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  type="password"
                  placeholder={
                    config?.api_key_configured
                      ? `已配置（${config.api_key_preview}****）留空不修改`
                      : '输入 API Key'
                  }
                  className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                />
              </div>
            </label>
          )}

          {/* SMTP 专属字段 */}
          {isSmtp && (
            <>
              <label className="mt-4 block">
                <span className="mb-1.5 block text-xs font-black text-gray-500">SMTP 服务器</span>
                <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                  <Server size={15} className="shrink-0 text-gray-400" />
                  <input
                    value={smtpHost}
                    onChange={(e) => setSmtpHost(e.target.value)}
                    placeholder="smtp.qq.com"
                    className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                  />
                </div>
              </label>

              <div className="mt-4 flex gap-3">
                <label className="block flex-1">
                  <span className="mb-1.5 block text-xs font-black text-gray-500">端口</span>
                  <input
                    value={smtpPort}
                    onChange={(e) => setSmtpPort(Number(e.target.value) || 587)}
                    type="number"
                    className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                  />
                </label>
                <div className="flex w-32 items-end pb-2.5">
                  <label className="flex cursor-pointer items-center gap-2 text-xs font-black text-gray-600">
                    <input
                      type="checkbox"
                      checked={smtpUseSsl}
                      onChange={(e) => handleSslToggle(e.target.checked)}
                      className="h-4 w-4 rounded border-gray-300"
                    />
                    SSL 直连
                  </label>
                </div>
              </div>
              <p className="mt-1 text-[11px] text-gray-400">
                勾选 SSL 通常用 465；不勾选则用 STARTTLS（587）。会自动联动端口。
              </p>

              <label className="mt-4 block">
                <span className="mb-1.5 block text-xs font-black text-gray-500">SMTP 用户名</span>
                <input
                  value={smtpUsername}
                  onChange={(e) => setSmtpUsername(e.target.value)}
                  placeholder="通常为发件人邮箱"
                  className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                />
              </label>

              <label className="mt-4 block">
                <span className="mb-1.5 block text-xs font-black text-gray-500">SMTP 密码 / 授权码</span>
                <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                  <KeyRound size={15} className="shrink-0 text-gray-400" />
                  <input
                    value={smtpPassword}
                    onChange={(e) => setSmtpPassword(e.target.value)}
                    type="password"
                    placeholder={
                      config?.smtp_password_configured
                        ? `已配置（${config.smtp_password_preview}****）留空不修改`
                        : '输入密码或授权码'
                    }
                    className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                  />
                </div>
              </label>
            </>
          )}

          {error && (
            <AdminNoticeBanner tone="red" onClose={() => setError(null)}>{error}</AdminNoticeBanner>
          )}
          {notice && (
            <AdminNoticeBanner tone="teal" onClose={() => setNotice(null)}>{notice}</AdminNoticeBanner>
          )}

          <div className="mt-5 flex justify-end">
            <Button variant="primary" onClick={handleSave} disabled={saving || !fromEmail.trim()}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              {saving ? '保存中...' : '保存配置'}
            </Button>
          </div>
        </Panel>

        <Panel className="p-5">
          <h3 className="mb-2 text-sm font-black text-gray-700">配置说明</h3>
          <ul className="space-y-1.5 text-xs text-gray-500">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Panel>
    </AdminPageShell>
  );
}
