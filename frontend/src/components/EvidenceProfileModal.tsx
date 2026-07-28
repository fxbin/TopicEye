'use client';

/**
 * 来源证据画像编辑模态框。
 *
 * 管理员通过此面板为信源配置可信线索画像：
 * - publisher_identity: 跨平台统一身份（如 "openai"）
 * - publisher_family:   发布者族群（如 "openai" / "the_verge"）
 * - platform:           平台标识（x / weibo / github / youtube / website / rss）
 * - publisher_kind:     发布者类型（unknown / primary / official / publisher / aggregator / social）
 * - official_domains:   官方一手链接域名白名单
 * - verification_proof_url: 管理员确认归属的依据 URL
 *
 * 后端 API:
 *   GET  /sources/{id}/evidence-profile
 *   PUT  /sources/{id}/evidence-profile
 */

import React, { useState, useEffect, useCallback } from 'react';
import { ShieldCheck } from 'lucide-react';
import { Badge, Button, Panel } from '@/components/ui';
import { sourcesApi } from '@/lib/api';
import type { BackendSource } from '@/components/SourceRow';
import { useDialogFocus } from '@/components/useDialogFocus';

const PUBLISHER_KINDS = [
  { value: 'unknown', label: '未知', desc: '默认值，不参与可信线索标注' },
  { value: 'primary', label: '原始发布', desc: '该信源是事件的原始发布者' },
  { value: 'official', label: '官方渠道', desc: '该信源是主体的官方渠道之一' },
  { value: 'publisher', label: '媒体发布者', desc: '独立媒体或出版方' },
  { value: 'aggregator', label: '聚合器', desc: '内容聚合平台，非独立报道' },
  { value: 'social', label: '社交账号', desc: '社交媒体账号，需配合身份确认' },
];

const PLATFORM_OPTIONS = [
  'website', 'rss', 'x', 'weibo', 'github', 'youtube', 'podcast', 'newsletter', 'other',
];

interface ProfileFormState {
  publisher_identity: string;
  publisher_family: string;
  platform: string;
  publisher_kind: string;
  official_domains: string;
  verification_proof_url: string;
}

const emptyForm: ProfileFormState = {
  publisher_identity: '',
  publisher_family: '',
  platform: 'website',
  publisher_kind: 'unknown',
  official_domains: '',
  verification_proof_url: '',
};

export function EvidenceProfileModal({
  source,
  onClose,
}: {
  source: BackendSource;
  onClose: () => void;
}) {
  const { dialogRef, onKeyDown } = useDialogFocus<HTMLDivElement>(true, onClose);
  const [form, setForm] = useState<ProfileFormState>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewedAt, setReviewedAt] = useState<string | null>(null);

  const fetchProfile = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await sourcesApi.getEvidenceProfile(source.id);
      if (res.profile) {
        const p = res.profile;
        setForm({
          publisher_identity: p.publisher_identity || '',
          publisher_family: p.publisher_family || '',
          platform: p.platform || 'website',
          publisher_kind: p.publisher_kind || 'unknown',
          official_domains: (p.official_domains || []).join('\n'),
          verification_proof_url: p.verification_proof_url || '',
        });
        setReviewedAt(p.reviewed_at);
      } else {
        setForm({
          ...emptyForm,
          platform: source.source_type?.toLowerCase() || 'website',
          publisher_family: source.name || '',
          publisher_identity: source.name?.toLowerCase().replace(/\s+/g, '_') || '',
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [source]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      const domains = form.official_domains
        .split('\n')
        .map((d) => d.trim())
        .filter(Boolean);
      await sourcesApi.upsertEvidenceProfile(source.id, {
        publisher_identity: form.publisher_identity.trim(),
        publisher_family: form.publisher_family.trim(),
        platform: form.platform,
        publisher_kind: form.publisher_kind,
        official_domains: domains.length > 0 ? domains : undefined,
        verification_proof_url: form.verification_proof_url.trim() || undefined,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const kindMeta = PUBLISHER_KINDS.find((k) => k.value === form.publisher_kind);

  return (
    <>
      <div aria-hidden="true" className="fixed inset-0 z-[1000] bg-black/30" onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-profile-modal-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="pointer-events-none fixed inset-0 z-[1001] flex items-center justify-center px-4"
      >
        <Panel className="pointer-events-auto flex max-h-[90vh] w-full max-w-[560px] flex-col overflow-hidden p-0 shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-gray-100 px-6 py-4">
          <ShieldCheck className="h-5 w-5 text-primary" />
          <div className="flex-1">
            <h2 id="evidence-profile-modal-title" className="text-base font-black text-gray-900">来源证据画像</h2>
            <p className="text-xs text-gray-400">
              {source.name} · 配置可信线索标注规则
            </p>
          </div>
          {reviewedAt && (
            <Badge tone="neutral" className="text-[11px]">
              审核于 {new Date(reviewedAt).toLocaleDateString('zh-CN')}
            </Badge>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="py-8 text-center text-sm text-gray-400">加载中…</div>
          ) : (
            <div className="flex flex-col gap-4">
              {error && (
                <div className="rounded-sm border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                  {error}
                </div>
              )}

              {/* 说明 */}
              <p className="text-xs leading-relaxed text-gray-400">
                来源画像用于「跨源证据」系统标注可信线索。同一 publisher_identity
                的多个官方账号只算一个发布主体，不伪装成多家独立报道。
                <span className="text-gray-500"> 画像仅系统信源可配置。</span>
              </p>

              {/* publisher_identity */}
              <Field label="发布者统一身份" hint="跨平台统一标识，如 openai / the_verge">
                <input
                  type="text"
                  value={form.publisher_identity}
                  onChange={(e) => setForm({ ...form, publisher_identity: e.target.value })}
                  placeholder="openai"
                  className="w-full rounded-sm border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </Field>

              {/* publisher_family */}
              <Field label="发布者族群" hint="用于独立性判定，同族群只计一次">
                <input
                  type="text"
                  value={form.publisher_family}
                  onChange={(e) => setForm({ ...form, publisher_family: e.target.value })}
                  placeholder="openai"
                  className="w-full rounded-sm border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </Field>

              {/* platform + publisher_kind */}
              <div className="grid grid-cols-2 gap-4">
                <Field label="平台">
                  <select
                    value={form.platform}
                    onChange={(e) => setForm({ ...form, platform: e.target.value })}
                    className="w-full rounded-sm border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary"
                  >
                    {PLATFORM_OPTIONS.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </Field>
                <Field label="发布者类型">
                  <select
                    value={form.publisher_kind}
                    onChange={(e) => setForm({ ...form, publisher_kind: e.target.value })}
                    className="w-full rounded-sm border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary"
                  >
                    {PUBLISHER_KINDS.map((k) => (
                      <option key={k.value} value={k.value}>{k.label}</option>
                    ))}
                  </select>
                </Field>
              </div>
              {kindMeta && (
                <p className="-mt-2 text-[11px] text-gray-400">{kindMeta.desc}</p>
              )}

              {/* official_domains */}
              <Field label="官方域名白名单" hint="每行一个域名，用于标注「官方一手链接」">
                <textarea
                  value={form.official_domains}
                  onChange={(e) => setForm({ ...form, official_domains: e.target.value })}
                  placeholder="openai.com&#10;openai.org"
                  rows={3}
                  className="w-full rounded-sm border border-gray-200 px-3 py-2 font-mono text-xs outline-none focus:border-primary"
                />
              </Field>

              {/* verification_proof_url */}
              <Field label="归属确认依据 URL" hint="管理员确认该账号/信源归属主体的参考链接">
                <input
                  type="url"
                  value={form.verification_proof_url}
                  onChange={(e) => setForm({ ...form, verification_proof_url: e.target.value })}
                  placeholder="https://openai.com/about"
                  className="w-full rounded-sm border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </Field>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-gray-100 px-6 py-3.5">
          <p className="text-[11px] text-gray-300">
            来源线索不代表事实核验
          </p>
          <div className="flex gap-3">
            <Button
              type="button"
              variant="secondary"
              onClick={onClose}
              disabled={saving}
              className="px-5"
            >
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={handleSave}
              disabled={loading || saving || !form.publisher_identity.trim()}
              className="px-5"
            >
              {saving ? '保存中…' : '保存'}
            </Button>
          </div>
        </div>
        </Panel>
      </div>
    </>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[13px] font-semibold text-gray-700">{label}</label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-gray-400">{hint}</p>}
    </div>
  );
}
