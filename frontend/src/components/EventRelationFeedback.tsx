'use client';

import { useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthContext } from '@/providers/AppProvider';
import { contentsApi } from '@/lib/api';
import { relationFeedbackPayload } from '@/lib/event-changes';

interface Props { contentId: number; member: { id: number; title: string }; eventId: number; version: number }
export default function EventRelationFeedback(props: Props) {
  const { currentUser } = useAuthContext();
  return <FeedbackForm key={[currentUser?.id, props.contentId, props.member.id, props.eventId, props.version].join(':')} {...props} userId={currentUser?.id ?? null} />;
}
function FeedbackForm({ contentId, member, eventId, version, userId }: Props & { userId: number | null }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const labelId = useId();
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (inFlight.current || savedId) return;
    let payload;
    try { payload = relationFeedbackPayload(member.id, eventId, version, reason); }
    catch (error) { setError((error as Error).message); return; }
    inFlight.current = true; setSaving(true); setError(null);
    try {
      const saved = await contentsApi.reportEventRelation(contentId, payload);
      if (!Number.isInteger(saved.id) || saved.id <= 0 || saved.user_id !== userId) throw new Error('反馈结果未确认');
      if (active.current) { setSavedId(saved.id); setOpen(false); }
    } catch {
      if (active.current) setError('提交未确认，请先查看“我的反馈”；确认未保存后再重试，填写内容已保留。');
    } finally {
      inFlight.current = false;
      if (active.current) setSaving(false);
    }
  }
  return <div className="mt-2 text-xs leading-5 text-gray-500">
    {savedId ? <p role="status">关联问题已记录（反馈 #{savedId}），等待处理。<Link href="/feedback" className="ml-2 text-primary-text underline">我的反馈</Link></p>
      : <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="min-h-9 rounded-xs text-gray-500 hover:text-primary-text hover:underline focus-visible:outline-2 focus-visible:outline-primary">关联有误</button>}
    {open && (userId !== null ? <form onSubmit={event => void submit(event)} className="mt-1 space-y-2">
      <label htmlFor={labelId} className="block text-gray-600">这篇报道与当前事件的关联哪里有误？</label>
      <textarea id={labelId} value={reason} onChange={event => setReason(event.target.value)} minLength={5} maxLength={1500} required rows={3} disabled={saving} className="w-full resize-y rounded-sm border border-gray-200 bg-white px-3 py-2 text-sm leading-6 text-gray-700 focus:border-primary focus:outline-none" />
      <p>反馈将交由管理员处理，当前关联不会立即改变。</p>
      {error && <p role="alert" className="text-red">{error} <Link href="/feedback" className="underline">我的反馈</Link></p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={saving} className="min-h-9 rounded-xs bg-primary-light px-3 font-semibold text-primary-text disabled:opacity-50">{saving ? '正在提交…' : '提交反馈'}</button>
        <button type="button" disabled={saving} onClick={() => setOpen(false)} className="min-h-9 rounded-xs px-3 hover:bg-gray-100 disabled:opacity-50">取消</button>
      </div>
    </form> : <Link href={`/login?returnTo=${encodeURIComponent(pathname)}`} className="inline-flex min-h-9 text-primary-text underline">登录后反馈关联问题</Link>)}
  </div>;
}
