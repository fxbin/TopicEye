/**
 * TopicEye Shared Utilities
 * Pure functions used across multiple pages
 */

import type { ContentItem, ContentAnalysis } from '@/types';
import { explainRecommendation } from '@/lib/recommendation';

// ─── timeAgo ───
// timeAgo / parseUTC / formatDateTime 等时间工具已统一迁移到 @/lib/datetime。
// 这里 re-export timeAgo 以保持既有 `import { timeAgo } from '@/lib/utils'` 不变。
export { timeAgo } from '@/lib/datetime';

// ─── weightStars ───

export const weightStars = (w: number) =>
  '●'.repeat(Math.min(w, 5)) + '○'.repeat(Math.max(5 - w, 0));

// ─── Analysis extract helpers (topics/[id] page) ───

export function extractRiskNotes(analysis: ContentAnalysis | null): string[] {
  if (!analysis?.risk_notes) return [];
  if (typeof analysis.risk_notes === 'string') {
    return analysis.risk_notes ? [analysis.risk_notes] : [];
  }
  if (Array.isArray(analysis.risk_notes)) {
    return analysis.risk_notes.filter((n: unknown) => typeof n === 'string' && n.length > 0);
  }
  if (typeof analysis.risk_notes === 'object') {
    const obj = analysis.risk_notes as Record<string, unknown>;
    const notes: string[] = [];
    for (const v of Object.values(obj)) {
      if (typeof v === 'string' && v.length > 0) notes.push(v);
      if (Array.isArray(v)) {
        for (const item of v) {
          if (typeof item === 'string' && item.length > 0) notes.push(item);
        }
      }
    }
    return notes;
  }
  return [];
}

export function extractCreatorAngles(analysis: ContentAnalysis | null): string[] {
  if (!analysis?.creator_angles) return [];
  if (Array.isArray(analysis.creator_angles)) {
    return analysis.creator_angles.filter((a: unknown) => typeof a === 'string');
  }
  return [];
}

export function extractTags(item: ContentItem, analysis: ContentAnalysis | null): string[] {
  const tags: string[] = [];
  if (item.tags && Array.isArray(item.tags)) {
    tags.push(...item.tags);
  }
  if (analysis?.tags && Array.isArray(analysis.tags)) {
    for (const t of analysis.tags) {
      if (!tags.includes(t)) tags.push(t);
    }
  }
  return tags;
}

export function extractTitleSuggestions(analysis: ContentAnalysis | null): string[] {
  if (!analysis?.title_suggestions) return [];
  if (Array.isArray(analysis.title_suggestions)) {
    return analysis.title_suggestions.filter((t: unknown) => typeof t === 'string');
  }
  return [];
}

export function extractKeyPoints(analysis: ContentAnalysis | null): string[] {
  if (!analysis?.key_points) return [];
  if (Array.isArray(analysis.key_points)) {
    return analysis.key_points.filter((p: unknown) => typeof p === 'string');
  }
  return [];
}

// ─── Tag color helper (today-picks) ───

import { T } from '@/lib/design-tokens';

const TAG_COLORS: Record<string, string> = {
  '模型': '#8B5CF6', '产品': '#3B82F6', '行业': '#10B981',
  '论文': '#6366F1', '技巧': '#F59E0B', '开源': '#EF4444',
  '工具': '#EC4899', '趋势': '#14B8A6', '大佬': '#F97316',
  '智能体': '#06B6D4', '具身智能': '#84CC16', '编码': '#A855F7',
};

export function getTagColor(tag: string): string {
  return TAG_COLORS[tag] || T.gray400;
}

// ─── Recommend level label (today-picks) ───

export function getRecommendLevelLabel(analysis: ContentAnalysis): string {
  return explainRecommendation(analysis).level;
}

// ─── Creation plan formatter ───

export function formatPlanText(plan: Record<string, unknown>): string {
  const lines: string[] = [];
  const p = plan as Record<string, unknown>;
  const titles = p.titles as string[] | undefined;
  if (titles) {
    lines.push('【备选标题】');
    titles.forEach((t: string, i: number) => lines.push(`${i + 1}. ${t}`));
    lines.push('');
  }
  const coverSlogan = p.cover_slogan as string | undefined;
  if (coverSlogan) lines.push(`封面文案：${coverSlogan}\n`);
  const structure = p.structure as Record<string, unknown> | undefined;
  if (structure) {
    lines.push('【正文结构】');
    const hook = structure.hook as string | undefined;
    if (hook) lines.push(`Hook: ${hook}`);
    const points = structure.points as string[] | undefined;
    points?.forEach((pt: string) => lines.push(`- ${pt}`));
    const cta = structure.cta as string | undefined;
    if (cta) lines.push(`互动引导: ${cta}`);
    lines.push('');
  }
  const scenes = p.scenes as Array<Record<string, unknown>> | undefined;
  if (scenes) {
    lines.push('【分镜头脚本】');
    scenes.forEach((s) => lines.push(`镜头${s.seq}(${s.seconds}s): ${s.visual}\n旁白: ${s.narration}`));
    lines.push('');
  }
  const outline = p.outline as Array<Record<string, unknown>> | undefined;
  if (outline) {
    lines.push('【文章大纲】');
    outline.forEach((s) => {
      lines.push(`${s.section}. ${s.heading}`);
      const sPoints = s.points as string[] | undefined;
      sPoints?.forEach((pt: string) => lines.push(`  • ${pt}`));
    });
    lines.push('');
  }
  const tags = p.tags as string[] | undefined;
  if (tags) lines.push(`标签：${tags.map((t: string) => `#${t}`).join(' ')}`);
  const tone = p.tone as string | undefined;
  if (tone) lines.push(`风格：${tone}`);
  return lines.join('\n');
}

/**
 * 分页追加时按 id 合并去重。
 *
 * 翻页窗口内可能有新内容入库导致 offset 位移，后一页会重复出现前一页
 * 已加载的条目；按 id 去重后再追加，保证列表不出现重复卡片。
 */
export function mergeItemsById<T extends { id: number }>(existing: T[], incoming: T[]): T[] {
  const seen = new Set(existing.map((item) => item.id));
  const merged = [...existing];
  for (const item of incoming) {
    if (!seen.has(item.id)) {
      merged.push(item);
      seen.add(item.id);
    }
  }
  return merged;
}

// ── 标签展示（规范化键 → 展示形态） ─────────────────────────────

/**
 * 标签存储的是规范化小写键（后端 tag_normalization），展示层统一经
 * prettyTag 还原观感：已知缩写全大写、已知品牌保留官方大小写，其余
 * 按词首字母大写；中文等无大小写文字原样返回。
 */
const TAG_ACRONYMS = new Set([
  'ai', 'llm', 'gpt', 'agi', 'gpu', 'ar', 'vr', 'mr', 'xr', 'api', 'sdk',
  'ios', 'mac', 'pc', 'saas', 'rag', 'mcp', 'nba', 'sql', 'cdn', 'cec',
]);

const TAG_BRANDS: Record<string, string> = {
  openai: 'OpenAI',
  chatgpt: 'ChatGPT',
  github: 'GitHub',
  gitlab: 'GitLab',
  youtube: 'YouTube',
  tiktok: 'TikTok',
  wechat: 'WeChat',
  whatsapp: 'WhatsApp',
  deepseek: 'DeepSeek',
  claude: 'Claude',
  gemini: 'Gemini',
  midjourney: 'Midjourney',
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  react: 'React',
  vue: 'Vue',
  nodejs: 'Node.js',
  mysql: 'MySQL',
  postgresql: 'PostgreSQL',
  sqlite: 'SQLite',
  macos: 'macOS',
  iphone: 'iPhone',
  ipad: 'iPad',
};

function capitalizeWord(word: string): string {
  if (TAG_ACRONYMS.has(word)) return word.toUpperCase();
  if (TAG_BRANDS[word]) return TAG_BRANDS[word];
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export function prettyTag(key: string): string {
  const trimmed = key.trim();
  if (!trimmed) return '';
  if (TAG_BRANDS[trimmed]) return TAG_BRANDS[trimmed];
  if (TAG_ACRONYMS.has(trimmed)) return trimmed.toUpperCase();
  // 含 CJK 的标签整体原样（避免按空格/连字符拆词破坏中文短语）
  if (/[\u4e00-\u9fff]/.test(trimmed)) return trimmed;
  return trimmed.split(/[\s-]+/).map(capitalizeWord).join(' ');
}
