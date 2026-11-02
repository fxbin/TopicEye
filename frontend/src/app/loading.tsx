export default function PageLoading() {
  return (
    <div className="workspace-scroll" role="status" aria-live="polite" aria-busy="true">
      <p className="mb-5 text-sm text-ink-500">正在打开页面…</p>
      <div aria-hidden="true" className="space-y-4">
        <div className="admin-shimmer h-6 w-48 rounded-sm" />
        <div className="admin-shimmer h-10 w-full rounded-sm" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div className="admin-shimmer h-80 rounded-lg" />
          <div className="admin-shimmer h-48 rounded-lg" />
        </div>
      </div>
    </div>
  );
}
