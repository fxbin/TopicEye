'use client';

import React, { useEffect, useState } from 'react';
import { CheckCircle2, KeyRound, Loader2, Mail, Settings } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { settingsApi } from '@/lib/api';
import type { EmailProviderConfig } from '@/lib/api/_analytics';
import { Badge, Button, Panel } from '@/components/ui';

const DEFAULT_FROM_NAME = 'TopicEye';

/** 验证码邮件配置说明项 */
const CONFIG_NOTES = [
  'Brevo 免费额度：300 封/天（约 9000 封/月），无需信用卡',
  '发件人邮箱需在 Brevo 后台完成域名认证（SPF/DKIM）',
  'API Key 以加密方式存储，不会明文保存',
  '配置完成后，用户注册时需先获取邮箱验证码',
];

export default function AdminSettingsPage() {
  const { currentUser } = useAppContext();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<EmailProviderConfig | null>(null);
  const [provider, setProvider] = useState('brevo');
  const [fromEmail, setFromEmail] = useState('');
  const [fromName, setFromName] = useState(DEFAULT_FROM_NAME);
  const [apiKey, setApiKey] = useState('');
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
      })
      .catch(() => setError('加载配置失败'))
      .finally(() => setLoading(false));
  }, []);

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
      });
      setApiKey('');
      setNotice('保存成功');
      const fresh = await settingsApi.getEmailProvider();
      setConfig(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (!currentUser || currentUser.role !== 'admin') {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page p-6">
        <Panel className="max-w-md p-6 text-center">
          <h2 className="mb-2 text-base font-semibold text-gray-900">需要管理员权限</h2>
          <p className="text-[13px] text-gray-500">系统设置仅对管理员开放。</p>
        </Panel>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page">
        <Loader2 size={24} className="animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[860px] space-y-5 pb-8">
        <div>
          <h1 className="flex items-center gap-2 text-[26px] font-black text-gray-900">
            <Settings size={22} className="text-primary" />
            系统设置
          </h1>
          <p className="mt-1 text-sm text-gray-500">配置系统级邮件服务，用于注册验证码等事务邮件发送</p>
        </div>

        <Panel className="p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-base font-black text-gray-900">邮件服务</h2>
            {config?.api_key_configured ? (
              <Badge tone="teal">
                <CheckCircle2 size={12} className="mr-1" />
                已配置
              </Badge>
            ) : (
              <Badge tone="amber">未配置</Badge>
            )}
          </div>

          <label className="block">
            <span className="mb-1.5 block text-xs font-black text-gray-500">邮件服务商</span>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="h-10 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm outline-none focus:border-primary-border focus:ring-2 focus:ring-primary-light"
            >
              {(config?.supported_providers || ['brevo']).map((p) => (
                <option key={p} value={p}>
                  {p === 'brevo' ? 'Brevo（免费 300 封/天）' : p}
                </option>
              ))}
            </select>
          </label>

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

          {error && (
            <div className="mt-4 rounded-sm border border-red-light bg-red-light px-3 py-2 text-xs font-bold text-red">
              {error}
            </div>
          )}
          {notice && (
            <div className="mt-4 rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal">
              {notice}
            </div>
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
            {CONFIG_NOTES.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
