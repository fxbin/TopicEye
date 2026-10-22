/** Each navigation/query owns its responses, including failures and cleanup. */
export function createRequestGuard() {
  let generation = 0;
  const capture = () => {
    const current = generation;
    return () => current === generation;
  };
  return {
    begin() {
      generation += 1;
      return capture();
    },
    capture,
    invalidate() {
      generation += 1;
    },
  };
}
