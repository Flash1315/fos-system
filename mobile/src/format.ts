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

function asUtcDate(iso: string): Date {
  const s = iso.trim();
  if (
    /Z$/i.test(s) ||
    /[+-]\d{2}:\d{2}$/.test(s) ||
    /[+-]\d{4}$/.test(s)
  ) {
    return new Date(s);
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(s);
  return new Date(`${s}Z`);
}

export function formatWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = asUtcDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Client-side password rule aligned with API (min 8, letter + digit). */
export function passwordStrengthError(password: string): string | null {
  if (password.length < 8) return "Password must be at least 8 characters";
  if (password.length > 128) return "Password is too long (max 128 characters)";
  if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
    return "Password must include a letter and a digit";
  }
  return null;
}

/** Simple email shape check (API still validates EmailStr). */
export function emailFormatError(email: string): string | null {
  const v = email.trim();
  if (!v) return "Email is required";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return "Enter a valid email address";
  if (v.length > 254) return "Email is too long";
  return null;
}

/** ISO-ish 3-letter currency code. */
export function currencyCodeError(code: string): string | null {
  const v = code.trim().toUpperCase();
  if (!v) return "Currency is required";
  if (!/^[A-Z]{3}$/.test(v)) return "Currency must be a 3-letter code (e.g. IDR)";
  return null;
}

export function statusColor(status: string, isVoided = false) {
  if (isVoided) return "#6B7280";
  if (status === "approved") return "#1DB954";
  if (status === "rejected") return "#B33A3A";
  return "#C9A227";
}
