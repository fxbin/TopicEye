import { redirect } from 'next/navigation';

/**
 * 旧路径跳转桩（2026-10-19，owner 验收反馈）：
 * 任务统计本是流水线健康信息，归属管理后台。页面已迁至 /admin/jobs
 * （后台「系统」组「任务监控」），此处保留 301 语义的服务端跳转，
 * 让历史收藏/文档链接不失效。
 */
export default function LegacyJobsStatsPage() {
  redirect('/admin/jobs');
}
