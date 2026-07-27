export function formatMoney(amount: number, currency: string) {
  try {
    return `${amount.toLocaleString()} ${currency}`;
  } catch {
    return `${amount} ${currency}`;
  }
}

export function formatWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function statusColor(status: string) {
  if (status === "approved") return "#1DB954";
  if (status === "rejected") return "#B33A3A";
  return "#C9A227";
}
