export function mergeById<T extends { id: number }>(prev: T[], more: T[]): T[] {
  if (!more.length) return prev;
  const byId = new Map<number, T>();
  const order: number[] = [];
  for (const row of prev) {
    byId.set(row.id, row);
    order.push(row.id);
  }
  for (const row of more) {
    if (!byId.has(row.id)) order.push(row.id);
    byId.set(row.id, row);
  }
  return order.map((id) => byId.get(id)!);
}

/**
 * The list APIs cap results at the requested page size, so a full final page
 * remains indistinguishable from a page with more results until the next load.
 */
export function hasMorePage(pageLen: number, pageSize: number): boolean {
  return pageLen >= pageSize;
}
