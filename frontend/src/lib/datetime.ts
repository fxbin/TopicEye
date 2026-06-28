/**
 * 日期/时间格式化工具（项目内统一来源）。
 *
 * 后端存储的 UTC datetime 默认不带 'Z' 后缀，必须通过 parseUTC 规整后
 * 才能被 JS 当作 UTC 解析。所有相对/绝对时间格式化都基于 parseUTC。
 */

/**
 * 把后端返回的 datetime 字符串规整为合法的 UTC 时间字符串并解析成 Date。
 *
 * 后端 datetime 形如 "2026-06-28T10:00:00"（无时区后缀），直接 new Date()
 * 会被当作本地时间，导致时区错乱。这里补 'Z' 让其按 UTC 解析。
 */
export function parseUTC(s: string): Date {
  const normalized = s.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(s) ? s : s + 'Z';
  return new Date(normalized);
}

/**
 * 相对时间，如「刚刚 / 3 分钟前 / 2 小时前 / 5 天前 / 3 个月前」。
 * 30 天为界，超过 30 天显示「X 个月前」。
 */
export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '从未同步';
  try {
    const date = parseUTC(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const seconds = Math.floor(diffMs / 1000);
    if (seconds < 60) return '刚刚';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} 分钟前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} 小时前`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days} 天前`;
    const months = Math.floor(days / 30);
    return `${months} 个月前`;
  } catch {
    return '';
  }
}

/**
 * 紧凑相对时间（中文无空格），如「3分钟前 / 2小时前 / 5天前」。
 * 用于表格、徽章等空间受限场景。与 timeAgo 语义一致，仅排版不同。
 */
export function timeAgoShort(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  try {
    const diff = Date.now() - parseUTC(dateStr).getTime();
    if (diff < 0) return '-';
    if (diff < 60_000) return '刚刚';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`;
    return `${Math.floor(diff / 86_400_000)}天前`;
  } catch {
    return '-';
  }
}

/**
 * 时:分（HH:MM），如「14:30」。用于时间轴、列表项的时间戳。
 */
export function formatClock(dateStr: string): string {
  try {
    const d = parseUTC(dateStr);
    if (Number.isNaN(d.getTime())) return '--:--';
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  } catch {
    return '--:--';
  }
}

/**
 * 完整日期时间（MM-DD HH:MM 或 YYYY-MM-DD HH:MM），用于详情、个人资料。
 * includeYear=true 时带上年份（默认 false）。
 */
export function formatDateTime(value?: string | null, includeYear = false): string {
  if (!value) return '-';
  const date = parseUTC(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    hour12: false,
    ...(includeYear ? { year: 'numeric' } : {}),
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * 仅日期（YYYY-MM-DD），用于版本计划、变更日志等。
 */
export function formatDate(value?: string | null): string {
  if (!value) return '-';
  const date = parseUTC(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

/**
 * 时间轴日期标签：今天显示「今天」，否则显示「MM-DD」。
 */
export function formatTimelineDate(dateStr: string): string {
  try {
    const d = parseUTC(dateStr);
    if (Number.isNaN(d.getTime())) return '未知时间';
    const today = new Date();
    const isSameDay =
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate();
    if (isSameDay) return '今天';
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  } catch {
    return '未知时间';
  }
}

/**
 * 判断给定时间是否是今天（按本地时区）。
 */
export function isToday(dateStr: string): boolean {
  try {
    const d = parseUTC(dateStr);
    if (Number.isNaN(d.getTime())) return false;
    const now = new Date();
    return (
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    );
  } catch {
    return false;
  }
}
