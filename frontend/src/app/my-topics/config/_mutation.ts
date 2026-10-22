/** Form drafts are reset only after the mutation succeeds; every exit settles pending. */
export async function runTopicMutation(
  mutate: () => Promise<void>,
  state: {
    pending(value: boolean): void;
    error(value: string | null): void;
    success(): void;
  },
) {
  state.pending(true);
  state.error(null);
  try {
    await mutate();
    state.success();
    return true;
  } catch (err) {
    state.error(err instanceof Error ? err.message : '操作失败，请重试');
    return false;
  } finally {
    state.pending(false);
  }
}
