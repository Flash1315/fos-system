const MAX_MONEY = 9999999999999999.99;
const MAX_LITERS = 10000;
const MAX_ODOMETER = 9999999.99;

function normalizeMoney(value: number): number | null {
  if (!Number.isFinite(value)) return null;
  const rounded = Math.round((value + Number.EPSILON) * 100) / 100;
  if (!Number.isFinite(rounded) || Math.abs(rounded) > MAX_MONEY) return null;
  return rounded;
}

export function parseFiniteMoney(
  raw: string,
  opts?: { min?: number; allowZero?: boolean },
): number | null {
  const value = Number(String(raw ?? "").trim().replace(",", "."));
  if (!Number.isFinite(value)) return null;
  if (!opts?.allowZero && Math.abs(value) < 1e-9) return null;
  if (opts?.min != null && value < opts.min) return null;
  if (opts?.min == null && value < 0.01) return null;
  return normalizeMoney(value);
}

export function parseFiniteSignedMoney(raw: string): number | null {
  const value = Number(String(raw ?? "").trim().replace(",", "."));
  if (!Number.isFinite(value) || value === 0) return null;
  return normalizeMoney(value);
}

/** Liters for fuel forms — positive finite, max 10000. */
export function parseFiniteLiters(raw: string): number | null {
  const value = Number(String(raw ?? "").trim().replace(",", "."));
  if (!Number.isFinite(value) || value <= 0 || value > MAX_LITERS) return null;
  return value;
}

/** Odometer reading — non-negative finite, max 9999999.99. */
export function parseFiniteOdometer(raw: string): number | null {
  const value = Number(String(raw ?? "").trim().replace(",", "."));
  if (!Number.isFinite(value) || value < 0 || value > MAX_ODOMETER) return null;
  return value;
}

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

export function statusColor(status: string, isVoided = false) {
  if (isVoided) return "#6B7280";
  if (status === "approved") return "#1DB954";
  if (status === "rejected") return "#B33A3A";
  return "#C9A227";
}
