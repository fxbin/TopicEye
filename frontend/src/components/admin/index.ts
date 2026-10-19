/**
 * 管理后台数据密集页原语集（#121 圆桌定稿，S3 切片）。
 *
 * 三态契约：页面层禁止自造加载/空/错误态——
 * - loading → AdminTableSkeleton / AdminBlockSkeleton
 * - empty   → AdminEmptyState（为什么为空 + 主动作）
 * - error   → AdminTable 内联错误 + 重试（或页面级 AdminNoticeBanner 系统消息）
 *
 * 旧 admin-ui.tsx 四件套（Shell/Header/Banner/Modal）继续有效，
 * 本目录补齐表格/筛选/反馈层。
 */
export { AdminEmptyState } from './AdminEmptyState';
export { AdminTableSkeleton, AdminBlockSkeleton } from './AdminSkeleton';
export { AdminTable } from './AdminTable';
export type { AdminTableColumn } from './AdminTable';
export { AdminFilters, AdminFilterChips } from './AdminFilters';
export type { AdminFilterChip } from './AdminFilters';
export { AdminToaster, toast } from './admin-toast';
