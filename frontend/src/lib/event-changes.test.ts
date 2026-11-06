import { describe, expect, it, vi } from 'vitest';
import { createEventChangeController, relationFeedbackPayload } from './event-changes';
import type { EventChangeAnalysis, EventChangeRequest } from '@/types/event-changes';
const snapshot: EventChangeRequest = { expected_event_id: 11, expected_version: 3, member_ids: [2] };
const ref = (id: number) => ({ id, title: `报道${id}`, url: `https://example.test/${id}`, source_name: '资料站', published_at: null });
const answer: EventChangeAnalysis = { status: 'ok', event_id: 11, version: 3, anchor: ref(1), member_ids: [2], items: [{ ...ref(2), change_type: 'evidence', description: '增加了测试条件与记录', quotes: [{ ...ref(1), excerpt: '发布方尚未提供实测记录' }, { ...ref(2), excerpt: '实测四个固定任务并记录条件' }] }] };
function pending<T>() { let resolve!: (x: T) => void; let reject!: (x: unknown) => void; const promise = new Promise<T>((a,b) => { resolve=a; reject=b; }); return { promise,resolve,reject }; }
describe('事件变化对照身份与恢复', () => {
  it('冻结请求身份，原始参数随后变化不污染本次请求', async () => {
    const input = { ...snapshot, member_ids: [2] }; const fetcher = vi.fn().mockResolvedValue(answer); const publish = vi.fn();
    const c = createEventChangeController(1,input,fetcher,publish); input.member_ids.push(9);input.expected_version=99;
    await c.run(); expect(fetcher).toHaveBeenCalledWith(1,snapshot);expect(publish.mock.lastCall![0]).toMatchObject({ analysis: answer, loading:false });
  });
  it.each(['success','error'] as const)('组件切换后丢弃旧%s和finally', async outcome => {
    const p=pending<EventChangeAnalysis>();const publish=vi.fn();const c=createEventChangeController(1,snapshot,()=>p.promise,publish);const job=c.run();c.cancel();const count=publish.mock.calls.length;
    if(outcome==='success')p.resolve(answer);else p.reject(new Error('late'));await job;expect(publish).toHaveBeenCalledTimes(count);
  });
  it('连续点击只发一条请求，503后可重试', async()=>{
    const p=pending<EventChangeAnalysis>();const fetcher=vi.fn().mockReturnValueOnce(p.promise).mockResolvedValueOnce(answer);const publish=vi.fn();const c=createEventChangeController(1,snapshot,fetcher,publish);
    const first=c.run();await c.run();expect(fetcher).toHaveBeenCalledTimes(1);p.reject(new Error('暂不可用'));await first;expect(publish.mock.lastCall![0].error).toBe('暂不可用');await c.run();expect(publish.mock.lastCall![0].analysis).toEqual(answer);
  });
  it('409要求重新加载，不拿旧身份重复调用',async()=>{
    const fetcher=vi.fn().mockRejectedValue({status:409,message:'分组已变化'});const publish=vi.fn();const c=createEventChangeController(1,snapshot,fetcher,publish);await c.run();await c.run();expect(fetcher).toHaveBeenCalledTimes(1);expect(publish.mock.lastCall![0]).toMatchObject({conflict:true,loading:false,analysis:null});
  });
  it.each([{...answer,event_id:99},{...answer,version:99},{...answer,anchor:ref(9)},{...answer,member_ids:[9]},{...answer,items:[]},{...answer,items:[{...answer.items[0],quotes:[{...ref(9),excerpt:'别的文章'}]}]}])('拒绝事件、版本、锚点、成员或引文越界',async value=>{
    const publish=vi.fn();await createEventChangeController(1,snapshot,async()=>value,publish).run();expect(publish.mock.lastCall![0].analysis).toBeNull();expect(publish.mock.lastCall![0].error).toContain('不一致');
  });
  it('关联反馈只提交冻结的身份与用户理由，由认证端点生成定位',()=>{
    const value=relationFeedbackPayload(2,11,3,'  这是另一个版本的评测  ');
    expect(value).toEqual({expected_event_id:11,expected_version:3,member_id:2,reason:'这是另一个版本的评测'});
    expect(value).not.toHaveProperty('user_id');expect(value).not.toHaveProperty('decision');
    expect(()=>relationFeedbackPayload(2,11,3,' ')).toThrow();
  });
});
