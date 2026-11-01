/**
 * 分类选项的合并口径（客户端与服务端共用）。
 *
 * 为什么单独抽出来：首页的分类 chips 行如果客户端与服务端各算一遍，
 * 两边的结果可能不同（分类接口与列表接口的返回顺序、到达顺序都不一样），
 * 于是首屏 HTML 与 hydration 后的状态不一致——要么报 hydration 警告，
 * 要么 chips 行在内容画出后悄悄变一次（CLS）。
 *
 * 口径：'全部' 永远在第一个，其余是「已知分类 ∪ 列表条目里的分类」，
 * 按中文 locale 排序。
 */

export interface CategoryLike {
  category?: string | null;
}

export function mergeCategoryOptions(
  existing: string[],
  names: string[],
  items: CategoryLike[],
): string[] {
  const merged = new Set(existing);
  merged.add('全部');
  names.forEach((name) => {
    if (name) merged.add(name);
  });
  items.forEach((item) => {
    if (item.category) merged.add(item.category);
  });
  return [
    '全部',
    ...Array.from(merged)
      .filter((name) => name !== '全部')
      .sort((a, b) => a.localeCompare(b, 'zh-CN')),
  ];
}
