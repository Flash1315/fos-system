/** Strict calendar date helpers (YYYY-MM-DD). */

export function isValidYmd(value: string): boolean {
  const s = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d
  );
}

export function ymdError(value: string, label = "Date"): string | null {
  const s = value.trim();
  if (!s) return null;
  if (!isValidYmd(s)) return `${label} must be a real calendar day (YYYY-MM-DD)`;
  return null;
}
