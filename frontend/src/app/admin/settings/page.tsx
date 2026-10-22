'use client';

import React, { useEffect, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { CheckCircle2, KeyRound, Loader2, LogIn, Mail, Plus, Server, Settings, Trash2, Webhook } from 'lucide-react';
import { settingsApi } from '@/lib/api';
import type { EmailProviderConfig, NotificationWebhookConfig, OAuthProviderItem, WebhookItem, WebhookItemUpdate } from '@/lib/api/_analytics';
import { NOTIFICATION_EVENT_TYPES } from '@/lib/api/_analytics';
import { EDITION_LABELS } from '@/lib/edition-naming';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner } from '@/components/admin-ui';
import { AdminBlockSkeleton, AdminEmptyState, toast } from '@/components/admin';

const DEFAULT_FROM_NAME = 'TopicEye';

/** 第三方登录 provider 显示名 */
const OAUTH_PROVIDER_LABELS: Record<string, string> = {
  google: 'Google 登录',
  github: 'GitHub 登录',
};

/** 邮件配置说明项（#108 起仅剩自定义 SMTP） */
const SMTP_NOTES: string[] = [
  '支持任意标准 SMTP 服务器（腾讯企业邮、Gmail、自建 Postfix 等）',
  '端口 465 使用 SSL 直连；端口 587 使用 STARTTLS',
  'SMTP 密码以加密方式存储，不会明文保存',
  '部分邮箱（如 QQ、163）需使用授权码而非登录密码',
];

/** 通知推送说明项（原独立说明 Panel 合并进分组卡脚注） */
const WEBHOOK_NOTES: React.ReactNode[] = [
  '支持配置多个 webhook，每个独立配置推送事件类型',
  '支持飞书 / 钉钉 / Slack 群机器人 incoming webhook',
  'webhook URL 含 token，以加密方式存储，不会明文保存',
  `推送场景：信源失败告警 / ${EDITION_LABELS.daily}生成完成 / ${EDITION_LABELS.weekly}生成完成 / 今日精选推送 / 测试发送`,
  <>
    环境变量 <code className="rounded-xs bg-ink-100 px-1 py-0.5 font-mono text-[11px]">ALERT_WEBHOOK_URL</code> 仍生效（运维通道，不参与事件过滤）
  </>,
];

/** 分组锚点导航：id 与下方分组卡 Panel 的 id 一一对应 */
const SECTION_LINKS = [
  { id: 'settings-email', label: '邮件服务' },
  { id: 'settings-oauth', label: '第三方登录' },
  { id: 'settings-webhook', label: '通知推送' },
] as const;

// ── 表单基样式（#121 新原语：ink token + admin-accent 聚焦，替代散落的 gray/primary 旧写法） ──
const FIELD_LABEL_CLASS = 'mb-1.5 block text-xs font-medium text-ink-500';
const INPUT_CLASS =
  'h-9 w-full rounded-xs border border-ink-200 bg-white px-3 text-[13px] text-ink-900 placeholder:text-ink-500 focus:border-admin-accent focus:outline-none';
const INPUT_ICON_WRAPPER_CLASS =
  'flex items-center rounded-xs border border-ink-200 bg-white px-3 focus-within:border-admin-accent focus-within:outline-none';

/** 分组卡：带锚点 id 的 Panel，统一「图标 + 标题 + 右侧状态/操作」头部 */
function SettingsSection({
  id,
  icon: Icon,
  title,
  actions,
  description,
  children,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  actions?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Panel id={id} className="p-5 sm:p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={15} className="shrink-0 text-ink-500" strokeWidth={2.2} />
          <h2 className="text-sm font-black text-ink-900">{title}</h2>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {description && <p className="mb-4 text-xs leading-5 text-ink-500">{description}</p>}
      {children}
    </Panel>
  );
}

/** 表单字段：统一 label + 控件结构 */
function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cx('block', className)}>
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      {children}
    </label>
  );
}

/** 卡内说明脚注：合并原独立「配置说明」Panel */
function SectionNotes({ title, items }: { title: string; items: readonly React.ReactNode[] }) {
  return (
    <div className="mt-5 border-t border-ink-100 pt-4">
      <h3 className="mb-2 text-xs font-bold text-ink-700">{title}</h3>
      <ul className="list-disc space-y-1.5 pl-4 text-xs leading-5 text-ink-500">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export default function AdminSettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<EmailProviderConfig | null>(null);
  const [fromEmail, setFromEmail] = useState('');
  const [fromName, setFromName] = useState(DEFAULT_FROM_NAME);
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpUseSsl, setSmtpUseSsl] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 通知推送 webhook 状态（多 webhook 列表）
  const [webhookConfig, setWebhookConfig] = useState<NotificationWebhookConfig | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookItemUpdate[]>([]);
  const [webhookSaving, setWebhookSaving] = useState(false);
  const [webhookTesting, setWebhookTesting] = useState(false);
  const [webhookTestResult, setWebhookTestResult] = useState<string | null>(null);
  const [webhookError, setWebhookError] = useState<string | null>(null);

  // 第三方登录（OAuth）provider 配置状态
  const [oauthProviders, setOauthProviders] = useState<OAuthProviderItem[]>([]);
  const [oauthForms, setOauthForms] = useState<Record<string, { client_id: string; client_secret: string; enabled: boolean }>>({});
  const [oauthSaving, setOauthSaving] = useState<string | null>(null);
  const [oauthError, setOauthError] = useState<string | null>(null);

  // 锚点导航当前高亮分组
  const [activeSection, setActiveSection] = useState<string>(SECTION_LINKS[0].id);

  const syncOauthForms = (providers: OAuthProviderItem[]) => {
    setOauthProviders(providers);
    setOauthForms(
      Object.fromEntries(
        providers.map((p) => [p.provider, { client_id: p.client_id || '', client_secret: '', enabled: p.enabled }]),
      ),
    );
  };

  useEffect(() => {
    Promise.all([
      settingsApi.getEmailProvider(),
      settingsApi.getNotificationWebhook(),
      settingsApi.getOAuthProviders(),
    ])
      .then(([emailData, webhookData, oauthData]) => {
        setConfig(emailData);
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

        syncOauthForms(oauthData.providers);
      })
      .catch(() => setError('加载配置失败'))
      .finally(() => setLoading(false));
  }, []);

  // 锚点导航高亮：分组卡进入视口上部激活带即点亮。
  // 用 IntersectionObserver 而非 window scroll——本页滚动发生在 AdminPageShell
  // 内部滚动容器里，scroll 事件不会冒泡到 window。
  useEffect(() => {
    const sections = SECTION_LINKS
      .map(({ id }) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (sections.length === 0) return;

    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        // 激活带内可见的组取文档序最后一组：下滑时新组一进带即点亮
        const next = [...SECTION_LINKS].reverse().find(({ id }) => visible.has(id));
        if (next) setActiveSection(next.id);
      },
      // 激活带 = 视口上部约 1/3，其余留给阅读区
      { rootMargin: '0px 0px -66% 0px' },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  // 切换 SSL 时联动常用端口
  const handleSslToggle = (checked: boolean) => {
    setSmtpUseSsl(checked);
    if (checked && smtpPort === 587) setSmtpPort(465);
    if (!checked && smtpPort === 465) setSmtpPort(587);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await settingsApi.updateEmailProvider({
        provider: 'smtp',
        from_email: fromEmail,
        from_name: fromName,
        smtp_host: smtpHost,
        smtp_port: smtpPort,
        smtp_username: smtpUsername,
        smtp_password: smtpPassword,
        smtp_use_ssl: smtpUseSsl,
      });
      setSmtpPassword('');
      toast.success('已保存');
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
    try {
      await settingsApi.updateNotificationWebhook({ webhooks });
      toast.success('已保存');
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

  // ── 第三方登录 provider 保存（逐 provider） ──
  const handleUpdateOauthForm = (provider: string, updates: Partial<{ client_id: string; client_secret: string; enabled: boolean }>) => {
    setOauthForms((prev) => ({ ...prev, [provider]: { ...prev[provider], ...updates } }));
  };

  const handleSaveOauth = async (provider: string) => {
    const form = oauthForms[provider];
    if (!form) return;
    setOauthSaving(provider);
    setOauthError(null);
    try {
      await settingsApi.updateOAuthProvider(provider, {
        client_id: form.client_id,
        client_secret: form.client_secret,
        enabled: form.enabled,
      });
      toast.success('已保存');
      const fresh = await settingsApi.getOAuthProviders();
      syncOauthForms(fresh.providers);
    } catch (err) {
      setOauthError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setOauthSaving(null);
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

  // admin 守卫已收敛到 app/admin/layout.tsx；本页 loading 期间保持
  // 分组卡结构渲染骨架（布局稳定防跳变），不做全屏 spinner 早退。

  return (
    <AdminPageShell maxWidth={1280}>
      <AdminPageHeader
        title="系统设置"
        icon={Settings}
        description="邮件服务、第三方登录与通知推送的系统级配置，按分组独立保存"
      />

      <div className="flex items-start gap-6">
        {/* 分组卡主列 */}
        <div className="min-w-0 flex-1 space-y-5">
          {error && (
            <AdminNoticeBanner tone="red" onClose={() => setError(null)}>{error}</AdminNoticeBanner>
          )}

          {/* ── 邮件服务 ── */}
          <SettingsSection
            id="settings-email"
            icon={Mail}
            title="邮件服务"
            actions={!loading && (config?.smtp_password_configured ? (
              <Badge tone="teal">
                <CheckCircle2 size={12} className="mr-1" />
                已配置
              </Badge>
            ) : (
              <Badge tone="amber">未配置</Badge>
            ))}
          >
            {loading ? (
              <AdminBlockSkeleton lines={7} />
            ) : (
              <>
                <Field label="发件人邮箱" className="mt-1">
                  <div className={INPUT_ICON_WRAPPER_CLASS}>
                    <Mail size={14} className="shrink-0 text-ink-500" />
                    <input
                      value={fromEmail}
                      onChange={(e) => setFromEmail(e.target.value)}
                      type="email"
                      placeholder="noreply@yourdomain.com"
                      className="h-9 min-w-0 flex-1 bg-transparent px-2 text-[13px] text-ink-900 outline-none placeholder:text-ink-500"
                    />
                  </div>
                </Field>

                <Field label="发件人名称" className="mt-4">
                  <input
                    value={fromName}
                    onChange={(e) => setFromName(e.target.value)}
                    className={INPUT_CLASS}
                  />
                </Field>

                <Field label="SMTP 服务器" className="mt-4">
                  <div className={INPUT_ICON_WRAPPER_CLASS}>
                    <Server size={14} className="shrink-0 text-ink-500" />
                    <input
                      value={smtpHost}
                      onChange={(e) => setSmtpHost(e.target.value)}
                      placeholder="smtp.qq.com"
                      className="h-9 min-w-0 flex-1 bg-transparent px-2 text-[13px] text-ink-900 outline-none placeholder:text-ink-500"
                    />
                  </div>
                </Field>

                <div className="mt-4 flex gap-3">
                  <Field label="端口" className="min-w-0 flex-1">
                    <input
                      value={smtpPort}
                      onChange={(e) => setSmtpPort(Number(e.target.value) || 587)}
                      type="number"
                      className={INPUT_CLASS}
                    />
                  </Field>
                  <div className="flex w-32 items-end pb-2.5">
                    <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-ink-700">
                      <input
                        type="checkbox"
                        checked={smtpUseSsl}
                        onChange={(e) => handleSslToggle(e.target.checked)}
                        className="h-4 w-4 rounded border-ink-300 accent-ink-900"
                      />
                      SSL 直连
                    </label>
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-ink-500">
                  勾选 SSL 通常用 465；不勾选则用 STARTTLS（587）。会自动联动端口。
                </p>

                <Field label="SMTP 用户名" className="mt-4">
                  <input
                    value={smtpUsername}
                    onChange={(e) => setSmtpUsername(e.target.value)}
                    placeholder="通常为发件人邮箱"
                    className={INPUT_CLASS}
                  />
                </Field>

                <Field label="SMTP 密码 / 授权码" className="mt-4">
                  <div className={INPUT_ICON_WRAPPER_CLASS}>
                    <KeyRound size={14} className="shrink-0 text-ink-500" />
                    <input
                      value={smtpPassword}
                      onChange={(e) => setSmtpPassword(e.target.value)}
                      type="password"
                      placeholder={
                        config?.smtp_password_configured
                          ? `已配置（${config.smtp_password_preview}****）留空不修改`
                          : '输入密码或授权码'
                      }
                      className="h-9 min-w-0 flex-1 bg-transparent px-2 text-[13px] text-ink-900 outline-none placeholder:text-ink-500"
                    />
                  </div>
                </Field>

                <div className="mt-5 flex justify-end">
                  <Button type="button" variant="primary" onClick={handleSave} disabled={saving || !fromEmail.trim()}>
                    {saving ? <Loader2 size={14} className="animate-spin" /> : null}
                    {saving ? '保存中...' : '保存配置'}
                  </Button>
                </div>

                <SectionNotes title="配置说明" items={SMTP_NOTES} />
              </>
            )}
          </SettingsSection>

          {/* ── 第三方登录（OAuth provider 凭据，DB 单一事实源 #94） ── */}
          <SettingsSection
            id="settings-oauth"
            icon={LogIn}
            title="第三方登录"
            description="配置 Google / GitHub 登录凭据，保存后即时生效（无需重启）。client_secret 加密存储，永不回传。"
            actions={!loading && (oauthProviders.some((p) => p.enabled && p.client_secret_configured) ? (
              <Badge tone="teal">
                <CheckCircle2 size={12} className="mr-1" />
                {oauthProviders.filter((p) => p.enabled && p.client_secret_configured).length} 个已启用
              </Badge>
            ) : (
              <Badge tone="amber">未启用</Badge>
            ))}
          >
            {loading ? (
              <AdminBlockSkeleton lines={6} />
            ) : oauthProviders.length === 0 ? (
              <AdminEmptyState
                icon={LogIn}
                title="暂无可配置的登录方式"
                description="服务端未注册任何 OAuth provider"
                compact
              />
            ) : (
              <>
                <div className="space-y-4">
                  {oauthProviders.map((p) => {
                    const form = oauthForms[p.provider] || { client_id: '', client_secret: '', enabled: false };
                    const configured = p.client_secret_configured && !!p.client_id;
                    return (
                      <div key={p.provider} className="rounded-xs border border-ink-200 p-4">
                        <div className="mb-3 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={form.enabled}
                              onChange={(e) => handleUpdateOauthForm(p.provider, { enabled: e.target.checked })}
                              className="h-4 w-4 rounded border-ink-300 accent-ink-900"
                            />
                            <span className="text-sm font-bold text-ink-900">{OAUTH_PROVIDER_LABELS[p.provider] || p.provider}</span>
                            {configured ? (
                              <Badge tone={p.enabled ? 'teal' : 'neutral'}>{p.enabled ? '已启用' : '已配置未启用'}</Badge>
                            ) : (
                              <Badge tone="amber">未配置</Badge>
                            )}
                          </div>
                        </div>

                        <Field label="Client ID">
                          <input
                            value={form.client_id}
                            onChange={(e) => handleUpdateOauthForm(p.provider, { client_id: e.target.value })}
                            placeholder={p.provider === 'google' ? 'xxxx.apps.googleusercontent.com' : 'Ov23liXXXXXXXXXXXXXX'}
                            className={INPUT_CLASS}
                          />
                        </Field>

                        <Field label="Client Secret" className="mt-3">
                          <div className={INPUT_ICON_WRAPPER_CLASS}>
                            <KeyRound size={14} className="shrink-0 text-ink-500" />
                            <input
                              value={form.client_secret}
                              onChange={(e) => handleUpdateOauthForm(p.provider, { client_secret: e.target.value })}
                              type="password"
                              placeholder={p.client_secret_configured ? '已配置（加密存储）留空不修改' : '输入 Client Secret'}
                              className="h-9 min-w-0 flex-1 bg-transparent px-2 text-[13px] text-ink-900 outline-none placeholder:text-ink-500"
                            />
                          </div>
                        </Field>

                        <div className="mt-4 flex justify-end">
                          <Button
                            type="button"
                            variant="primary"
                            onClick={() => handleSaveOauth(p.provider)}
                            disabled={oauthSaving === p.provider || (form.enabled && (!form.client_id.trim() || (!form.client_secret.trim() && !p.client_secret_configured)))}
                          >
                            {oauthSaving === p.provider ? <Loader2 size={14} className="animate-spin" /> : null}
                            {oauthSaving === p.provider ? '保存中...' : '保存'}
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {oauthError && (
                  <AdminNoticeBanner tone="red" className="mt-4" onClose={() => setOauthError(null)}>{oauthError}</AdminNoticeBanner>
                )}
              </>
            )}
          </SettingsSection>

          {/* ── 通知推送 webhook（多 webhook 列表） ── */}
          <SettingsSection
            id="settings-webhook"
            icon={Webhook}
            title="通知推送"
            description="将运营通知推送到飞书 / 钉钉 / Slack 群机器人。每个 webhook 可独立配置推送事件类型。webhook URL 加密存储。"
            actions={
              <>
                {!loading && (webhookConfig?.webhooks.some((w) => w.enabled && w.webhook_url_configured) ? (
                  <Badge tone="teal">
                    <CheckCircle2 size={12} className="mr-1" />
                    {webhookConfig.webhooks.filter((w) => w.enabled && w.webhook_url_configured).length} 个已启用
                  </Badge>
                ) : (
                  <Badge tone="amber">未配置</Badge>
                ))}
                <Button type="button" variant="ghost" onClick={handleAddWebhook} disabled={loading} className="!px-2 !py-1 text-xs">
                  <Plus size={12} className="mr-1" />
                  添加
                </Button>
              </>
            }
          >
            {loading ? (
              <AdminBlockSkeleton lines={8} />
            ) : webhooks.length === 0 ? (
              <AdminEmptyState
                icon={Webhook}
                title="暂无 webhook 配置"
                description={`添加一个 webhook，把信源失败告警与${EDITION_LABELS.daily}推送到群里`}
                compact
                action={
                  <Button type="button" variant="secondary" onClick={handleAddWebhook}>
                    <Plus size={12} className="mr-1" />
                    添加 webhook
                  </Button>
                }
              />
            ) : (
              <>
                <div className="space-y-4">
                  {webhooks.map((wh, index) => {
                    const original = webhookConfig?.webhooks[index];
                    const urlConfigured = original?.webhook_url_configured;
                    const urlPreview = original?.webhook_url_preview || '';
                    return (
                      <div key={index} className="rounded-xs border border-ink-200 p-4">
                        {/* 行 1：名称 + 启用 + 删除 */}
                        <div className="mb-3 flex items-center justify-between">
                          <div className="flex min-w-0 items-center gap-2">
                            <input
                              type="checkbox"
                              checked={wh.enabled}
                              onChange={(e) => handleUpdateWebhook(index, { enabled: e.target.checked })}
                              className="h-4 w-4 rounded border-ink-300 accent-ink-900"
                            />
                            <input
                              value={wh.name}
                              onChange={(e) => handleUpdateWebhook(index, { name: e.target.value })}
                              placeholder={`Webhook ${index + 1}（如：运营群）`}
                              className="h-8 w-48 rounded-xs border border-ink-200 bg-white px-2 text-[13px] font-bold text-ink-900 outline-none placeholder:font-normal placeholder:text-ink-500 focus:border-admin-accent"
                            />
                            {urlConfigured ? (
                              <Badge tone={wh.enabled ? 'teal' : 'neutral'}>
                                {wh.enabled ? '已启用' : '未启用'}
                              </Badge>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            onClick={() => handleRemoveWebhook(index)}
                            className="shrink-0 text-ink-300 transition hover:text-red-500"
                            title="删除"
                            aria-label={`删除 Webhook ${index + 1}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>

                        {/* Webhook URL */}
                        <Field label="Webhook URL">
                          <div className={INPUT_ICON_WRAPPER_CLASS}>
                            <Webhook size={14} className="shrink-0 text-ink-500" />
                            <input
                              value={wh.webhook_url}
                              onChange={(e) => handleUpdateWebhook(index, { webhook_url: e.target.value })}
                              type="password"
                              placeholder={
                                urlConfigured
                                  ? `已配置（${urlPreview}****）留空不修改`
                                  : 'https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx'
                              }
                              className="h-9 min-w-0 flex-1 bg-transparent px-2 text-[13px] text-ink-900 outline-none placeholder:text-ink-500"
                            />
                          </div>
                        </Field>

                        {/* 推送事件类型 */}
                        <div className="mt-3">
                          <span className={FIELD_LABEL_CLASS}>推送事件类型</span>
                          <div className="flex flex-wrap gap-1.5">
                            {NOTIFICATION_EVENT_TYPES.map((et) => {
                              const checked = wh.event_types.includes(et.value);
                              return (
                                <label
                                  key={et.value}
                                  className={cx(
                                    'flex cursor-pointer items-center gap-1 rounded-xs border px-2 py-1 text-xs transition',
                                    checked
                                      ? 'border-admin-accent bg-admin-accent/10 text-ink-900'
                                      : 'border-ink-200 bg-white text-ink-500 hover:border-ink-300',
                                  )}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(e) => handleToggleEventType(index, et.value, e.target.checked)}
                                    className="h-3 w-3 rounded border-ink-300 accent-ink-900"
                                  />
                                  {et.label}
                                </label>
                              );
                            })}
                          </div>
                        </div>

                        {/* 备注 */}
                        <Field label="备注（可选）" className="mt-3">
                          <input
                            value={wh.note}
                            onChange={(e) => handleUpdateWebhook(index, { note: e.target.value })}
                            placeholder="如：飞书运营群"
                            className={INPUT_CLASS}
                          />
                        </Field>
                      </div>
                    );
                  })}
                </div>

                {webhookError && (
                  <AdminNoticeBanner tone="red" className="mt-4" onClose={() => setWebhookError(null)}>{webhookError}</AdminNoticeBanner>
                )}
                {webhookTestResult && (
                  <AdminNoticeBanner tone="teal" className="mt-4" onClose={() => setWebhookTestResult(null)}>
                    <pre className="whitespace-pre-wrap font-sans text-xs">{webhookTestResult}</pre>
                  </AdminNoticeBanner>
                )}

                <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={handleTestWebhook}
                    disabled={webhookTesting || !webhookConfig?.webhooks.some((w) => w.webhook_url_configured)}
                  >
                    {webhookTesting ? <Loader2 size={14} className="animate-spin" /> : null}
                    {webhookTesting ? '发送中...' : '发送测试（全部）'}
                  </Button>
                  <Button type="button" variant="primary" onClick={handleSaveWebhook} disabled={webhookSaving}>
                    {webhookSaving ? <Loader2 size={14} className="animate-spin" /> : null}
                    {webhookSaving ? '保存中...' : '保存配置'}
                  </Button>
                </div>

                <SectionNotes title="推送说明" items={WEBHOOK_NOTES} />
              </>
            )}
          </SettingsSection>
        </div>

        {/* 分组锚点导航：sticky 于滚动容器顶部，滚动/点击高亮当前组 */}
        <nav aria-label="设置分组导航" className="sticky top-5 hidden w-44 shrink-0 lg:block">
          <ul className="space-y-0.5 border-l border-ink-200">
            {SECTION_LINKS.map(({ id, label }) => {
              const active = activeSection === id;
              return (
                <li key={id}>
                  <a
                    href={`#${id}`}
                    aria-current={active ? 'true' : undefined}
                    onClick={() => setActiveSection(id)}
                    className={cx(
                      '-ml-px block border-l-2 py-1.5 pl-3 text-[13px] transition',
                      active
                        ? 'border-admin-accent font-medium text-ink-900'
                        : 'border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700',
                    )}
                  >
                    {label}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </AdminPageShell>
  );
}
