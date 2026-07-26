'use client';

import React, { useEffect, useState } from 'react';
import { CheckCircle2, ExternalLink, KeyRound, Loader2, Mail, Plus, Server, Settings, Trash2, Webhook } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { settingsApi } from '@/lib/api';
import type { EmailProviderConfig, NotificationWebhookConfig, WebhookItem, WebhookItemUpdate } from '@/lib/api/_analytics';
import { NOTIFICATION_EVENT_TYPES } from '@/lib/api/_analytics';
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

  // 通知推送 webhook 状态（多 webhook 列表）
  const [webhookConfig, setWebhookConfig] = useState<NotificationWebhookConfig | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookItemUpdate[]>([]);
  const [webhookSaving, setWebhookSaving] = useState(false);
  const [webhookTesting, setWebhookTesting] = useState(false);
  const [webhookTestResult, setWebhookTestResult] = useState<string | null>(null);
  const [webhookNotice, setWebhookNotice] = useState<string | null>(null);
  const [webhookError, setWebhookError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      settingsApi.getEmailProvider(),
      settingsApi.getNotificationWebhook(),
    ])
      .then(([emailData, webhookData]) => {
        setConfig(emailData);
        setProvider(emailData.provider);
        setFromEmail(emailData.from_email);
        setFromName(emailData.from_name);
        setSmtpHost(emailData.smtp_host);
        setSmtpPort(emailData.smtp_port || 587);
        setSmtpUsername(emailData.smtp_username);
        setSmtpUseSsl(emailData.smtp_use_ssl);

        setWebhookConfig(webhookData);
        setWebhooks(
          webhookData.webhooks.map((wh) => ({
            name: wh.name,
            enabled: wh.enabled,
            webhook_url: '', // 空表示保留原值
            event_types: wh.event_types?.length ? wh.event_types : ['source_failure'],
            note: wh.note,
          })),
        );
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

  const handleSaveWebhook = async () => {
    setWebhookSaving(true);
    setWebhookError(null);
    setWebhookNotice(null);
    try {
      await settingsApi.updateNotificationWebhook({ webhooks });
      setWebhookNotice('保存成功');
      const fresh = await settingsApi.getNotificationWebhook();
      setWebhookConfig(fresh);
      setWebhooks(
        fresh.webhooks.map((wh: WebhookItem) => ({
          name: wh.name,
          enabled: wh.enabled,
          webhook_url: '',
          event_types: wh.event_types?.length ? wh.event_types : ['source_failure'],
          note: wh.note,
        })),
      );
    } catch (err) {
      setWebhookError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setWebhookSaving(false);
    }
  };

  const handleAddWebhook = () => {
    setWebhooks([...webhooks, {
      name: '',
      enabled: true,
      webhook_url: '',
      event_types: ['source_failure'],
      note: '',
    }]);
  };

  const handleRemoveWebhook = (index: number) => {
    setWebhooks(webhooks.filter((_, i) => i !== index));
  };

  const handleUpdateWebhook = (index: number, updates: Partial<WebhookItemUpdate>) => {
    setWebhooks(webhooks.map((wh, i) => (i === index ? { ...wh, ...updates } : wh)));
  };

  const handleToggleEventType = (index: number, eventType: string, checked: boolean) => {
    const wh = webhooks[index];
    if (!wh) return;
    const newTypes = checked
      ? [...wh.event_types, eventType]
      : wh.event_types.filter((v) => v !== eventType);
    handleUpdateWebhook(index, { event_types: newTypes });
  };

  const handleTestWebhook = async () => {
    setWebhookTesting(true);
    setWebhookError(null);
    setWebhookTestResult(null);
    try {
      const result = await settingsApi.testNotificationWebhook();
      if (result.error) {
        setWebhookTestResult(`❌ ${result.error}`);
      } else if (result.sent > 0) {
        const detailLines = result.details.map((d) => `  • ${d.url_preview}: ${d.ok ? '✅' : '❌'} ${d.status}`).join('\n');
        setWebhookTestResult(`✅ 发送成功 ${result.sent} 条${result.failed > 0 ? `，失败 ${result.failed} 条` : ''}\n${detailLines}`);
      } else {
        const detailLines = result.details.map((d) => `  • ${d.url_preview}: ❌ ${d.status}`).join('\n');
        setWebhookTestResult(`❌ 全部失败（${result.failed} 条）\n${detailLines}`);
      }
    } catch (err) {
      setWebhookError(err instanceof Error ? err.message : '测试发送失败');
    } finally {
      setWebhookTesting(false);
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

        {/* ── 通知推送 webhook（多 webhook 列表） ── */}
        <Panel className="p-6">
          <div className="mb-5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Webhook size={16} className="text-gray-500" />
              <h2 className="text-base font-black text-gray-900">通知推送</h2>
            </div>
            <div className="flex items-center gap-2">
              {webhookConfig?.webhooks.some((w) => w.enabled && w.webhook_url_configured) ? (
                <Badge tone="teal">
                  <CheckCircle2 size={12} className="mr-1" />
                  {webhookConfig.webhooks.filter((w) => w.enabled && w.webhook_url_configured).length} 个已启用
                </Badge>
              ) : (
                <Badge tone="amber">未配置</Badge>
              )}
              <Button variant="ghost" onClick={handleAddWebhook} className="!px-2 !py-1 text-xs">
                <Plus size={12} className="mr-1" />
                添加
              </Button>
            </div>
          </div>

          <p className="mb-4 text-xs text-gray-500">
            将运营通知推送到飞书 / 钉钉 / Slack 群机器人。每个 webhook 可独立配置推送事件类型。webhook URL 加密存储。
          </p>

          {/* webhook 列表 */}
          {webhooks.length === 0 ? (
            <div className="rounded-sm border border-dashed border-gray-200 py-8 text-center text-xs text-gray-400">
              暂无 webhook 配置，点击右上角「添加」按钮新增
            </div>
          ) : (
            <div className="space-y-4">
              {webhooks.map((wh, index) => {
                const original = webhookConfig?.webhooks[index];
                const urlConfigured = original?.webhook_url_configured;
                const urlPreview = original?.webhook_url_preview || '';
                return (
                  <div key={index} className="rounded-sm border border-gray-200 p-4">
                    {/* 行 1：名称 + 启用 + 删除 */}
                    <div className="mb-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={wh.enabled}
                          onChange={(e) => handleUpdateWebhook(index, { enabled: e.target.checked })}
                          className="h-4 w-4 rounded border-gray-300"
                        />
                        <input
                          value={wh.name}
                          onChange={(e) => handleUpdateWebhook(index, { name: e.target.value })}
                          placeholder={`Webhook ${index + 1}（如：运营群）`}
                          className="h-8 w-48 rounded-sm border border-gray-200 px-2 text-sm font-black outline-none focus:border-primary-border"
                        />
                        {urlConfigured ? (
                          <Badge tone={wh.enabled ? 'teal' : 'neutral'}>
                            {wh.enabled ? '已启用' : '未启用'}
                          </Badge>
                        ) : null}
                      </div>
                      <button
                        onClick={() => handleRemoveWebhook(index)}
                        className="text-gray-400 hover:text-red-500"
                        title="删除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    {/* Webhook URL */}
                    <label className="block">
                      <span className="mb-1 block text-xs font-black text-gray-500">Webhook URL</span>
                      <div className="flex items-center rounded-sm border border-gray-200 bg-white px-3 focus-within:border-primary-border focus-within:ring-2 focus-within:ring-primary-light">
                        <Webhook size={14} className="shrink-0 text-gray-400" />
                        <input
                          value={wh.webhook_url}
                          onChange={(e) => handleUpdateWebhook(index, { webhook_url: e.target.value })}
                          type="password"
                          placeholder={
                            urlConfigured
                              ? `已配置（${urlPreview}****）留空不修改`
                              : 'https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx'
                          }
                          className="h-9 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
                        />
                      </div>
                    </label>

                    {/* 推送事件类型 */}
                    <div className="mt-3">
                      <span className="mb-1.5 block text-xs font-black text-gray-500">推送事件类型</span>
                      <div className="flex flex-wrap gap-1.5">
                        {NOTIFICATION_EVENT_TYPES.map((et) => {
                          const checked = wh.event_types.includes(et.value);
                          return (
                            <label
                              key={et.value}
                              className={`flex cursor-pointer items-center gap-1 rounded-sm border px-2 py-1 text-xs ${checked ? 'border-primary-border bg-primary-light/20 text-gray-700' : 'border-gray-200 text-gray-500'}`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(e) => handleToggleEventType(index, et.value, e.target.checked)}
                                className="h-3 w-3 rounded border-gray-300"
                              />
                              {et.label}
                            </label>
                          );
                        })}
                      </div>
                    </div>

                    {/* 备注 */}
                    <label className="mt-3 block">
                      <span className="mb-1 block text-xs font-black text-gray-500">备注（可选）</span>
                      <input
                        value={wh.note}
                        onChange={(e) => handleUpdateWebhook(index, { note: e.target.value })}
                        placeholder="如：飞书运营群"
                        className="h-9 w-full rounded-sm border border-gray-200 px-3 text-sm outline-none focus:border-primary-border"
                      />
                    </label>
                  </div>
                );
              })}
            </div>
          )}

          {webhookError && (
            <AdminNoticeBanner tone="red" onClose={() => setWebhookError(null)}>{webhookError}</AdminNoticeBanner>
          )}
          {webhookNotice && (
            <AdminNoticeBanner tone="teal" onClose={() => setWebhookNotice(null)}>{webhookNotice}</AdminNoticeBanner>
          )}
          {webhookTestResult && (
            <AdminNoticeBanner tone="teal" onClose={() => setWebhookTestResult(null)}>
              <pre className="whitespace-pre-wrap font-sans text-xs">{webhookTestResult}</pre>
            </AdminNoticeBanner>
          )}

          <div className="mt-5 flex items-center justify-between gap-3">
            <Button
              variant="ghost"
              onClick={handleTestWebhook}
              disabled={webhookTesting || !webhookConfig?.webhooks.some((w) => w.webhook_url_configured)}
            >
              {webhookTesting ? <Loader2 size={14} className="animate-spin" /> : null}
              {webhookTesting ? '发送中...' : '发送测试（全部）'}
            </Button>
            <Button variant="primary" onClick={handleSaveWebhook} disabled={webhookSaving}>
              {webhookSaving ? <Loader2 size={14} className="animate-spin" /> : null}
              {webhookSaving ? '保存中...' : '保存配置'}
            </Button>
          </div>
        </Panel>

        <Panel className="p-5">
          <h3 className="mb-2 text-sm font-black text-gray-700">通知推送说明</h3>
          <ul className="space-y-1.5 text-xs text-gray-500">
            <li>支持配置多个 webhook，每个独立配置推送事件类型</li>
            <li>支持飞书 / 钉钉 / Slack 群机器人 incoming webhook</li>
            <li>webhook URL 含 token，以加密方式存储，不会明文保存</li>
            <li>推送场景：信源失败告警 / 日报生成完成 / 周报生成完成 / 今日精选推送 / 测试发送</li>
            <li>环境变量 <code className="rounded bg-gray-100 px-1">ALERT_WEBHOOK_URL</code> 仍生效（运维通道，不参与事件过滤）</li>
          </ul>
        </Panel>
    </AdminPageShell>
  );
}
