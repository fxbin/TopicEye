import type { ContentItem } from '@/types';

export function PendingReview({ items, total, onRead }: {
  items: Pick<ContentItem, 'id' | 'title' | 'source_name'>[];
  total: number;
  onRead: (id: number) => void;
}) {
  if (!total) return null;
  return (
    <details className="mb-5 rounded-sm border border-gray-200 bg-white px-4 py-3">
      <summary className="cursor-pointer text-sm font-bold text-gray-700">待 AI 复核 · {total} 条</summary>
      <p className="mt-2 text-xs leading-6 text-gray-500">这些内容只有本地速览，尚未进入精选。AI 分析完成后会重新参与筛选。</p>
      <ul className="mt-2 divide-y divide-gray-100">
        {items.map(item => (
          <li key={item.id} className="py-3">
            <button type="button" onClick={() => onRead(item.id)} className="block w-full text-left text-sm font-medium leading-6 text-gray-800 hover:text-primary focus-visible:outline-2 focus-visible:outline-primary">{item.title}</button>
            {item.source_name && <span className="text-xs text-gray-500">{item.source_name}</span>}
          </li>
        ))}
      </ul>
      {items.length < total && <p className="text-xs leading-6 text-gray-500">先展示 {items.length} 条，更多内容可在首页查看。</p>}
    </details>
  );
}
