/** A reset must cancel the search draft, even when the committed value is unchanged. */
export function createDebouncedSearch(commit: (value: string) => void, delayMs: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cancel = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };
  return {
    cancel,
    schedule(value: string) {
      cancel();
      timer = setTimeout(() => { timer = undefined; commit(value); }, delayMs);
    },
  };
}
