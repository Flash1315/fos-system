export function mergeById<T extends { id: number }>(prev: T[], more: T[]): T[] {
  if (!more.length) return prev;
  const seen = new Set(prev.map((r) => r.id));
  const extra = more.filter((r) => !seen.has(r.id));
  return extra.length ? [...prev, ...extra] : prev;
}

/**
 * The list APIs cap results at the requested page size, so a full final page
 * remains indistinguishable from a page with more results until the next load.
 */
export function hasMorePage(pageLen: number, pageSize: number): boolean {
  return pageLen >= pageSize;
}
