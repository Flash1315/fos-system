import { storageDelete, storageGet, storageSet } from "./storage";

function resolveApiUrl(): string {
  const raw = (process.env.EXPO_PUBLIC_API_URL || "").trim().replace(/\/+$/, "");
  const appEnv = (process.env.EXPO_PUBLIC_APP_ENV || "").trim().toLowerCase();
  const allowLocalFallback = typeof __DEV__ !== "undefined" && __DEV__;
  const gatedRelease = appEnv === "production" || appEnv === "preview";
  if (!raw) {
    if (gatedRelease) {
      throw new Error("EXPO_PUBLIC_API_URL is required for preview/production builds");
    }
    if (allowLocalFallback) return "http://127.0.0.1:8000";
    throw new Error("EXPO_PUBLIC_API_URL is required outside development builds");
  }
  if (!allowLocalFallback || gatedRelease) {
    const isLoopbackHttp = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(raw);
    if (gatedRelease && isLoopbackHttp) {
      throw new Error("EXPO_PUBLIC_API_URL must not use loopback for preview/production builds");
    }
    if (!/^https:\/\//i.test(raw) && !isLoopbackHttp) {
      throw new Error("EXPO_PUBLIC_API_URL must use https:// outside development builds");
    }
  }
  return raw;
}

/** Change to your machine LAN IP when testing on a phone. */
export const API_URL = resolveApiUrl();

/** Shared offline copy (boot / resume / fetch failures). */
export const OFFLINE_MSG =
  "Could not reach the server. Check your connection and try again.";

function networkErrorFrom(e: unknown): Error {
  if (e instanceof Error && e.name === "AbortError") {
    return new Error("Request timed out — check connection and try again");
  }
  return new Error(OFFLINE_MSG);
}

const TOKEN_KEY = "fos_token";
const TOKEN_EXP_KEY = "fos_token_exp";
let cachedToken: string | null = null;
let cachedTokenExpMs = 0;
let cachedMediaToken: string | null = null;
let cachedMediaTokenExpMs = 0;
const REQUEST_TIMEOUT_MS = 30000;
const UPLOAD_TIMEOUT_MS = 120000;
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
let lastAuthClearedMs = 0;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

/** True for a short window after JWT clear — avoid Offline + Session expired dual Alerts. */
export function wasAuthRecentlyCleared(withinMs = 2500): boolean {
  return lastAuthClearedMs > 0 && Date.now() - lastAuthClearedMs < withinMs;
}

function markAuthCleared() {
  lastAuthClearedMs = Date.now();
}

/** Thrown after local session clear so screens can skip a second Alert. */
export class SessionExpiredError extends Error {
  constructor(message = "Session expired") {
    super(message);
    this.name = "SessionExpiredError";
  }
}

/** Suppress screen Alerts when App already showed the session-expired dialog. */
export function shouldSkipErrorAlert(err: unknown): boolean {
  return err instanceof SessionExpiredError || wasAuthRecentlyCleared();
}

export type User = {
  id: number;
  email: string;
  full_name: string;
  role: "owner" | "manager" | "employee";
  organization_id: number;
  is_active?: boolean;
  must_set_password?: boolean;
};

function isFormDataBody(body: BodyInit | null | undefined): boolean {
  if (!body || typeof body !== "object") return false;
  if (typeof FormData !== "undefined" && body instanceof FormData) return true;
  return typeof (body as { append?: unknown }).append === "function";
}

async function notifyUnauthorized(requestToken: string | null) {
  // Only clear session if the failing request still matches the active token
  // (a delayed 401 — including one started with no token — must not wipe a
  // freshly logged-in session).
  const active = await getToken();
  if (requestToken !== active) {
    return;
  }
  try {
    await clearToken();
  } catch {
    /* ignore */
  }
  markAuthCleared();
  try {
    unauthorizedHandler?.();
  } catch {
    /* ignore */
  }
}

function newIdemKey(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Generate a stable Idempotency-Key for a confirmed mutation attempt. */
export function makeIdempotencyKey(prefix = "idem"): string {
  return newIdemKey(prefix);
}

/** Keep the same key for identical retries; rotate when the payload slot changes. */
export function idemKeyFor(
  keyRef: { current: string | null },
  slotRef: { current: string | number | null },
  prefix: string,
  slot: string | number,
): string {
  if (slotRef.current !== slot) {
    slotRef.current = slot;
    keyRef.current = null;
  }
  if (!keyRef.current) keyRef.current = makeIdempotencyKey(prefix);
  return keyRef.current;
}

export type MoneyRecord = {
  id: number;
  kind: "expense" | "fuel" | "income";
  status: "pending" | "approved" | "rejected";
  amount: number;
  currency: string;
  category: string;
  purpose?: string;
  place?: string;
  bike?: string;
  comment: string;
  photo_url?: string;
  liters?: number | null;
  odometer?: number | null;
  client_name?: string;
  payment_method?: string;
  payment_source?: string;
  created_by?: number;
  created_by_name?: string;
  created_by_active?: boolean;
  created_at: string;
  occurred_at?: string | null;
  decided_at?: string | null;
  decided_by?: number | null;
  decided_by_name?: string;
  is_voided?: boolean;
  voided_at?: string | null;
  transfer_group_id?: string | null;
  can_void?: boolean;
  void_blocked_reason?: string | null;
  is_in_closed_cycle?: boolean;
  settlement_cutoff_at?: string | null;
};

export type OrgReport = {
  currency: string;
  approved_expense_total: number;
  approved_fuel_total: number;
  approved_income_cash: number;
  approved_income_transfer: number;
  pending_count: number;
  team_count: number;
  net_result?: number;
  cash_position: number;
  spend_from_cash?: number;
  spend_from_pocket?: number;
  internal_transfer_total?: number;
  total_spendings?: number;
  total_cash_held?: number;
  by_category: { kind: string; category: string; total: number }[];
  by_purpose?: { purpose: string; total: number }[];
};

export type MyReport = {
  currency: string;
  cash_on_hand: number;
  spendings: number;
  approved_expense_total: number;
  approved_fuel_total: number;
  approved_income_cash: number;
  pending_count: number;
  by_purpose?: { purpose: string; total: number }[];
  by_category?: { kind: string; category: string; total: number }[];
};

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function saveToken(token: string, expiresInSec?: number) {
  // Persist expiry metadata before the JWT so a crash cannot leave a fresh
  // token without fos_token_exp (client preflight would skip forever).
  if (expiresInSec != null && Number.isFinite(expiresInSec) && expiresInSec > 0) {
    const expMs = Date.now() + Math.floor(expiresInSec) * 1000;
    await storageSet(TOKEN_EXP_KEY, String(expMs));
    await storageSet(TOKEN_KEY, token);
    cachedTokenExpMs = expMs;
    cachedToken = token;
  } else {
    try {
      await storageDelete(TOKEN_EXP_KEY);
    } catch {
      /* best-effort */
    }
    await storageSet(TOKEN_KEY, token);
    cachedTokenExpMs = 0;
    cachedToken = token;
  }
}

export async function clearToken() {
  cachedToken = null;
  cachedTokenExpMs = 0;
  cachedMediaToken = null;
  cachedMediaTokenExpMs = 0;
  // Best-effort: clear both keys even if one SecureStore delete fails.
  await Promise.allSettled([storageDelete(TOKEN_KEY), storageDelete(TOKEN_EXP_KEY)]);
}

/** Revoke server-side tokens then clear local session. */
export async function logout() {
  try {
    await request<{ ok: boolean }>("/auth/logout", { method: "POST" });
  } catch {
    /* still clear local token */
  }
  await clearToken();
}

export async function getToken() {
  if (cachedToken) return cachedToken;
  cachedToken = await storageGet(TOKEN_KEY);
  return cachedToken;
}

async function loadTokenExpMs(): Promise<number> {
  if (cachedTokenExpMs > 0) return cachedTokenExpMs;
  const raw = await storageGet(TOKEN_EXP_KEY);
  const n = raw ? Number(raw) : 0;
  cachedTokenExpMs = Number.isFinite(n) && n > 0 ? n : 0;
  return cachedTokenExpMs;
}

/** Clear local session when persisted access-token expiry has passed.
 * Legacy sessions without fos_token_exp skip client preflight (server 401 still clears).
 */
async function ensureAccessTokenNotExpired(): Promise<void> {
  const token = await getToken();
  if (!token) return;
  const expMs = await loadTokenExpMs();
  if (expMs <= 0) return; // pre-0.7.81 tokens: no client expiry
  // Small skew so we don't race the server clock.
  if (Date.now() + 5_000 < expMs) return;
  await notifyUnauthorized(token);
  throw new SessionExpiredError();
}

function newClientRequestId(): string {
  return `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}


function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function parseRetryAfterSec(raw: string | null): number | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.min(30, n);
}

/** Soft-retry is only safe for GET or Idempotency-Key mutations. */
export function isSafeSoftRetry(method: string, hasIdempotencyKey: boolean): boolean {
  return method.toUpperCase() === "GET" || hasIdempotencyKey;
}

function shouldSoftRetry(status: number | null, err: unknown): boolean {
  if (status === 429 || status === 502 || status === 503) return true;
  if (err instanceof Error) {
    const msg = err.message || "";
    if (err.name === "AbortError") return true;
    if (/timed out|network request failed|failed to fetch|network error/i.test(msg)) {
      return true;
    }
  }
  return false;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  opts?: { timeoutMs?: number; retries?: number },
): Promise<T> {
  await ensureAccessTokenNotExpired();
  const auth = await authHeaders();
  const requestToken = auth.Authorization?.startsWith("Bearer ")
    ? auth.Authorization.slice(7)
    : null;
  const headers: Record<string, string> = {
    ...(isFormDataBody(init.body) ? {} : { "Content-Type": "application/json" }),
    ...auth,
    ...((init.headers as Record<string, string>) || {}),
  };
  // Keep the same client request id + Idempotency-Key across soft retries.
  if (!headers["X-Request-Id"]) headers["X-Request-Id"] = newClientRequestId();
  const method = (init.method || "GET").toUpperCase();
  const hasIdem = !!(headers["Idempotency-Key"] || headers["idempotency-key"]);
  const safeRetry = isSafeSoftRetry(method, hasIdem);
  const maxAttempts = Math.max(1, (opts?.retries ?? (safeRetry ? 2 : 0)) + 1);
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const controller = new AbortController();
    const timeoutMs = opts?.timeoutMs ?? REQUEST_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res: Response | null = null;
    try {
      res = await fetch(`${API_URL}${path}`, {
        ...init,
        headers,
        signal: init.signal || controller.signal,
      });
    } catch (e) {
      lastError = networkErrorFrom(e);
      if (attempt < maxAttempts && shouldSoftRetry(null, e)) {
        await sleep(Math.min(1500, 250 * attempt));
        continue;
      }
      throw lastError;
    } finally {
      clearTimeout(timer);
    }
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      if (res.status === 401) {
        await notifyUnauthorized(requestToken);
        throw new SessionExpiredError();
      }
      if (
        attempt < maxAttempts &&
        shouldSoftRetry(res.status, null) &&
        res.status !== 401
      ) {
        const retryAfter = parseRetryAfterSec(res.headers.get("Retry-After"));
        const waitMs =
          retryAfter != null ? retryAfter * 1000 : Math.min(1500, 300 * attempt);
        await sleep(waitMs);
        continue;
      }
      throw new Error(
        formatApiError(
          data,
          res.statusText || `HTTP ${res.status}`,
          res.status,
          res.headers.get("Retry-After"),
          res.headers.get("X-Request-Id") || headers["X-Request-Id"],
        ),
      );
    }
    return data as T;
  }
  throw lastError instanceof Error ? lastError : new Error("Request failed");
}

async function requestText(path: string, init: RequestInit = {}): Promise<string> {
  await ensureAccessTokenNotExpired();
  const auth = await authHeaders();
  const requestToken = auth.Authorization?.startsWith("Bearer ")
    ? auth.Authorization.slice(7)
    : null;
  const headers: Record<string, string> = {
    ...auth,
    ...((init.headers as Record<string, string>) || {}),
  };
  if (!headers["X-Request-Id"]) headers["X-Request-Id"] = newClientRequestId();
  const method = (init.method || "GET").toUpperCase();
  const hasIdem = !!(headers["Idempotency-Key"] || headers["idempotency-key"]);
  const safeRetry = isSafeSoftRetry(method, hasIdem);
  const maxAttempts = Math.max(1, (safeRetry ? 2 : 0) + 1);
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let res: Response | null = null;
    try {
      res = await fetch(`${API_URL}${path}`, {
        ...init,
        headers,
        signal: init.signal || controller.signal,
      });
    } catch (e) {
      lastError = networkErrorFrom(e);
      if (attempt < maxAttempts && shouldSoftRetry(null, e)) {
        await sleep(Math.min(1500, 250 * attempt));
        continue;
      }
      throw lastError;
    } finally {
      clearTimeout(timer);
    }
    const text = await res.text();
    if (!res.ok) {
      if (res.status === 401) {
        await notifyUnauthorized(requestToken);
        throw new SessionExpiredError();
      }
      if (attempt < maxAttempts && shouldSoftRetry(res.status, null) && res.status !== 401) {
        const retryAfter = parseRetryAfterSec(res.headers.get("Retry-After"));
        const waitMs =
          retryAfter != null ? retryAfter * 1000 : Math.min(1500, 300 * attempt);
        await sleep(waitMs);
        continue;
      }
      let detail = text;
      try {
        const data = JSON.parse(text);
        detail = formatApiError(
          data,
          res.statusText || `HTTP ${res.status}`,
          res.status,
          res.headers.get("Retry-After"),
          res.headers.get("X-Request-Id"),
        );
      } catch {
        detail = formatApiError(
          null,
          text || res.statusText || `HTTP ${res.status}`,
          res.status,
          res.headers.get("Retry-After"),
          res.headers.get("X-Request-Id") || headers["X-Request-Id"],
        );
      }
      throw new Error(detail);
    }
    return text;
  }
  throw lastError instanceof Error ? lastError : new Error("Request failed");
}

/** True when org billing freezes money mutations (canceled / past_due). */
export function isBillingReadOnly(status: string | null | undefined): boolean {
  const s = (status || "").toLowerCase();
  return s === "canceled" || s === "past_due";
}

export const BILLING_READONLY_MSG =
  "Billing restricted — org is read-only (canceled or past due). You can still view data and cancel pending items; creates, approvals, invites, org/team edits, payouts, and receipt uploads are blocked until billing is restored.";

function formatApiError(
  data: unknown,
  fallback: string,
  status?: number,
  retryAfter?: string | null,
  requestId?: string | null,
): string {
  const reqId = (requestId || "").trim();
  if (status === 429) {
    let base = "Too many requests — wait a moment and try again";
    if (typeof data === "object" && data && "detail" in data) {
      const d = (data as { detail: unknown }).detail;
      if (typeof d === "string" && d.trim()) base = d;
    }
    const sec =
      retryAfter && /^\d+$/.test(retryAfter.trim()) ? Number(retryAfter.trim()) : null;
    if (sec != null && sec > 0) base = `${base} (retry in ~${sec}s)`;
    return reqId ? `${base} (ref ${reqId})` : base;
  }
  if (status === 413) {
    let base = "Request too large — try a smaller photo or fewer fields";
    if (typeof data === "object" && data && "detail" in data) {
      const d = (data as { detail: unknown }).detail;
      if (typeof d === "string" && d.trim()) base = d;
    }
    return reqId ? `${base} (ref ${reqId})` : base;
  }
  if (status != null && status >= 500) {
    let msg = fallback || "Server error — try again";
    if (typeof data === "object" && data && "detail" in data) {
      const d = (data as { detail: unknown }).detail;
      if (typeof d === "string" && d.trim()) msg = d;
    }
    return reqId ? `${msg} (ref ${reqId})` : msg;
  }
  if (typeof data !== "object" || !data || !("detail" in data)) {
    return reqId && status != null && status >= 400 ? `${fallback} (ref ${reqId})` : fallback;
  }
  const detail = (data as { detail: unknown }).detail;
  if (typeof detail === "string") {
    // Keep JWT on billing 403 — only soften the copy for freeze responses.
    if (
      status === 403 &&
      /organization billing is (canceled|past due)/i.test(detail)
    ) {
      return BILLING_READONLY_MSG;
    }
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "object" && item && "msg" in item) {
          const loc =
            "loc" in item && Array.isArray((item as { loc: unknown }).loc)
              ? (item as { loc: unknown[] }).loc.slice(1).join(".")
              : "";
          const msg = String((item as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(item);
      })
      .join("; ");
  }
  return fallback;
}

export type AuthToken = {
  access_token: string;
  token_type?: string;
  expires_in?: number;
  user: User;
  organization_slug: string;
};

export function registerOrg(body: {
  name: string;
  slug: string;
  currency?: string;
  owner_email: string;
  owner_name: string;
  owner_password: string;
  owner_password_confirm: string;
}) {
  return request<AuthToken>("/orgs/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function login(body: {
  email: string;
  password: string;
  organization_slug: string;
}) {
  return request<AuthToken>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function me() {
  return request<User>("/auth/me");
}

type ResumeListener = () => void;
const resumeListeners = new Set<ResumeListener>();

/** Screens subscribe to refresh after AppState reconnect. */
export function onResumeRefresh(listener: ResumeListener): () => void {
  resumeListeners.add(listener);
  return () => {
    resumeListeners.delete(listener);
  };
}

export function notifyResumeRefresh() {
  for (const listener of [...resumeListeners]) {
    try {
      listener();
    } catch {
      /* ignore */
    }
  }
}

/** Cheap liveness probe (no auth) for reconnect UX. */
export async function probeApiLive(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch(`${API_URL}/health/live`, { signal: controller.signal });
      return res.ok;
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return false;
  }
}


export function changePassword(
  current_password: string,
  new_password: string,
  password_confirm: string,
) {
  return request<AuthToken>("/auth/password", {
    method: "POST",
    body: JSON.stringify({
      current_password,
      new_password,
      password_confirm,
    }),
  });
}

export function acceptInvite(
  token: string,
  password: string,
  password_confirm: string,
  opts?: { idempotencyKey?: string },
) {
  return request<AuthToken>("/auth/accept-invite", {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify({
      token,
      password,
      password_confirm,
    }),
  });
}

export function myOrg() {
  return request<{
    id: number;
    name: string;
    slug: string;
    currency: string;
    currency_locked?: boolean;
  }>("/orgs/me");
}

export function updateOrg(
  body: { name?: string; currency?: string },
  opts?: { idempotencyKey?: string },
) {
  return request<{
    id: number;
    name: string;
    slug: string;
    currency: string;
    currency_locked?: boolean;
  }>("/orgs/me", {
    method: "PATCH",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify(body),
  });
}

export type InviteResult = User & {
  organization_slug?: string;
  must_set_password?: boolean;
  invite_token?: string | null;
  email_sent?: boolean;
};

export function inviteUser(
  body: {
    email: string;
    full_name: string;
    role: "owner" | "manager" | "employee";
    password?: string;
    password_confirm?: string;
  },
  opts?: { idempotencyKey?: string },
) {
  return request<InviteResult>("/orgs/invite", {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify(body),
  });
}

export async function listMembers() {
  return fetchAllMemberPages("/orgs/members");
}

export async function orgDirectory() {
  return fetchAllMemberPages("/orgs/directory");
}

async function fetchAllMemberPages(path: string): Promise<User[]> {
  const pageSize = 200;
  const out: User[] = [];
  let offset = 0;
  for (;;) {
    const q = new URLSearchParams({
      limit: String(pageSize),
      offset: String(offset),
    });
    const page = await request<User[]>(`${path}?${q.toString()}`);
    out.push(...page);
    if (page.length < pageSize) break;
    offset += pageSize;
    if (offset > 10_000) break;
  }
  return out;
}

export function setMemberActive(
  id: number,
  is_active: boolean,
  opts?: { idempotencyKey?: string },
) {
  return request<User>(`/orgs/members/${id}/active`, {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify({ is_active }),
  });
}

export function setMemberRole(
  id: number,
  role: "owner" | "manager" | "employee",
  opts?: { idempotencyKey?: string },
) {
  return request<User>(`/orgs/members/${id}/role`, {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify({ role }),
  });
}

export function resetMemberPassword(
  id: number,
  new_password: string,
  password_confirm: string,
  opts?: { idempotencyKey?: string },
) {
  return request<User>(`/orgs/members/${id}/password`, {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify({ new_password, password_confirm }),
  });
}

export function issueMemberResetToken(
  id: number,
  opts?: { force?: boolean; idempotencyKey?: string },
) {
  const q = opts?.force ? "?force=true" : "";
  return request<{
    id: number;
    email: string;
    full_name: string;
    organization_slug: string;
    invite_token: string;
    must_set_password: boolean;
    email_sent?: boolean;
  }>(`/orgs/members/${id}/reset-token${q}`, {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
  });
}

export type BillingInfo = {
  plan: string;
  billing_status: string;
  currency: string;
  organization_slug: string;
  telegram_configured: boolean;
  telegram_chat_id: string;
  email_configured: boolean;
  media_backend: string;
};

export function billingMe() {
  return request<BillingInfo>("/billing/me");
}

/** Stub only — paid plans are refused server-side until billing ships. Prefer free/trial. */
export function setBillingPlan(
  plan: "free" | "trial",
  opts?: { idempotencyKey?: string },
) {
  return request<BillingInfo>("/billing/plan", {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify({ plan }),
  });
}

export function setTelegramChat(
  telegram_chat_id: string,
  opts?: { idempotencyKey?: string },
) {
  return request<BillingInfo>("/integrations/telegram/chat", {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
    body: JSON.stringify({ telegram_chat_id }),
  });
}

export function testTelegram(opts?: { idempotencyKey?: string }) {
  return request<{ ok: boolean }>("/integrations/telegram/test", {
    method: "POST",
    headers: opts?.idempotencyKey
      ? { "Idempotency-Key": opts.idempotencyKey }
      : undefined,
  });
}

export type BalanceInfo = {
  cash_on_hand: number;
  spendings: number;
  currency: string;
  pending_count: number;
  last_expense_payout_at?: string | null;
  last_income_handover_at?: string | null;
  reserved_spendings?: number;
  reserved_cash?: number;
  available_spendings?: number;
  available_cash?: number;
};

export function myBalance() {
  return request<BalanceInfo>("/records/balance/me");
}

export type TeamBalance = {
  user_id: number;
  full_name: string;
  role: string;
  cash_on_hand: number;
  spendings: number;
  owed_to_employee: number;
  currency?: string;
  pending_count: number;
  last_expense_payout_at?: string | null;
  last_income_handover_at?: string | null;
  reserved_spendings?: number;
  reserved_cash?: number;
  available_spendings?: number;
  available_cash?: number;
};

export function teamBalances() {
  return request<TeamBalance[]>("/records/balance/team");
}

export function myRecords(params?: {
  kind?: string;
  status?: string;
  purpose?: string;
  q?: string;
  voided?: boolean;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.purpose) q.set("purpose", params.purpose);
  if (params?.q) q.set("q", params.q);
  if (params?.voided != null) q.set("voided", String(params.voided));
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q}` : "";
  return request<MoneyRecord[]>(`/records/mine${suffix}`);
}

export function orgRecords(params?: {
  kind?: string;
  status?: string;
  purpose?: string;
  created_by?: number;
  q?: string;
  voided?: boolean;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.purpose) q.set("purpose", params.purpose);
  if (params?.created_by != null) q.set("created_by", String(params.created_by));
  if (params?.q) q.set("q", params.q);
  if (params?.voided != null) q.set("voided", String(params.voided));
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q}` : "";
  return request<MoneyRecord[]>(`/records/org${suffix}`);
}

export function getRecord(id: number) {
  return request<MoneyRecord>(`/records/${id}`);
}

export function getCategories(kind?: string) {
  const suffix = kind ? `?kind=${kind}` : "";
  return request<{
    categories: Record<string, string[]>;
    purposes: string[];
    payment_sources: string[];
  }>(`/records/categories${suffix}`);
}

export function createRecord(
  body: {
    kind: "expense" | "fuel" | "income";
    amount: number;
    category?: string;
    purpose?: string;
    place?: string;
    bike?: string;
    comment?: string;
    photo_url?: string;
    payment_method?: string;
    payment_source?: string;
    client_name?: string;
    liters?: number;
    odometer?: number;
    created_for_user_id?: number;
    occurred_at?: string;
    approve_now?: boolean;
    allow_closed_cycle?: boolean;
  },
  opts?: { idempotencyKey?: string },
) {
  const idem = opts?.idempotencyKey || newIdemKey("rec");
  return request<MoneyRecord>("/records", {
    method: "POST",
    headers: { "Idempotency-Key": idem },
    body: JSON.stringify(body),
  });
}

export function updateRecord(
  id: number,
  body: {
    amount?: number;
    category?: string;
    purpose?: string;
    place?: string;
    bike?: string;
    comment?: string;
    photo_url?: string;
    payment_method?: string;
    payment_source?: string;
    client_name?: string;
    liters?: number;
    odometer?: number;
    occurred_at?: string | null;
  },
  opts?: { idempotencyKey?: string },
) {
  const idem = opts?.idempotencyKey || newIdemKey("rupd");
  return request<MoneyRecord>(`/records/${id}`, {
    method: "PATCH",
    headers: { "Idempotency-Key": idem },
    body: JSON.stringify(body),
  });
}

export function lastFuelOdometer(params?: {
  bike?: string;
  user_id?: number;
  at?: string;
  exclude_id?: number;
}) {
  const q = new URLSearchParams();
  if (params?.bike) q.set("bike", params.bike);
  if (params?.user_id != null) q.set("user_id", String(params.user_id));
  if (params?.at) q.set("at", params.at);
  if (params?.exclude_id != null) q.set("exclude_id", String(params.exclude_id));
  const suffix = q.toString() ? `?${q}` : "";
  return request<{
    bike: string;
    user_id: number;
    odometer: number | null;
    min_odometer: number | null;
    max_odometer: number | null;
    record_id: number | null;
    occurred_at: string | null;
    has_history: boolean;
  }>(`/records/fuel/last-odometer${suffix}`);
}

export function pendingRecords(params?: {
  purpose?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.purpose) q.set("purpose", params.purpose);
  if (params?.kind) q.set("kind", params.kind);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q}` : "";
  return request<MoneyRecord[]>(`/records/pending${suffix}`);
}

export function pendingCount(params?: { purpose?: string; kind?: string }) {
  const q = new URLSearchParams();
  if (params?.purpose) q.set("purpose", params.purpose);
  if (params?.kind) q.set("kind", params.kind);
  const suffix = q.toString() ? `?${q}` : "";
  return request<{ count: number }>(`/records/pending/count${suffix}`);
}

export function pendingSettlementCount() {
  return request<{ count: number }>("/payouts/requests/pending/count");
}

export function myPendingSettlementCount() {
  return request<{ count: number }>("/payouts/requests/mine/pending/count");
}

export function decideRecord(
  id: number,
  approve: boolean,
  note = "",
  opts?: { idempotencyKey?: string; allowClosedCycle?: boolean },
) {
  return request<MoneyRecord>(`/records/${id}/decide`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("decide") },
    body: JSON.stringify({
      approve,
      note,
      allow_closed_cycle: !!opts?.allowClosedCycle,
    }),
  });
}

export function decideBatch(
  ids: number[],
  approve: boolean,
  note = "",
  opts?: { idempotencyKey?: string; allowClosedCycle?: boolean },
) {
  return request<{
    decided: MoneyRecord[];
    skipped: number;
    skipped_insufficient_cash?: number;
    skipped_inactive?: number;
    skipped_closed_cycle?: number;
  }>("/records/decide-batch", {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("dbatch") },
    body: JSON.stringify({
      ids,
      approve,
      note,
      allow_closed_cycle: !!opts?.allowClosedCycle,
    }),
  });
}

export type ReportPeriod = {
  days?: number;
  date_from?: string;
  date_to?: string;
};

function reportQuery(period?: ReportPeriod | number) {
  const q = new URLSearchParams();
  if (typeof period === "number") {
    q.set("days", String(period));
  } else if (period) {
    if (period.days != null) q.set("days", String(period.days));
    if (period.date_from) q.set("date_from", period.date_from);
    if (period.date_to) q.set("date_to", period.date_to);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function orgReport(period?: ReportPeriod | number) {
  return request<OrgReport>(`/reports/org${reportQuery(period)}`);
}

export function myReport(period?: ReportPeriod | number) {
  return request<MyReport>(`/reports/me${reportQuery(period)}`);
}

export function downloadReportCsv(period?: ReportPeriod | number) {
  return requestText(`/reports/export.csv${reportQuery(period)}`);
}

export function commentRecord(id: number, note: string, opts?: { idempotencyKey?: string }) {
  return request<MoneyRecord>(`/records/${id}/comment`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("cmt") },
    body: JSON.stringify({ note }),
  });
}

export function cancelRecord(id: number, opts?: { idempotencyKey?: string }) {
  return request<MoneyRecord>(`/records/${id}`, {
    method: "DELETE",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("cancel") },
  });
}

export function voidRecord(id: number, note: string, opts?: { idempotencyKey?: string }) {
  return request<MoneyRecord>(`/records/${id}/void`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("void") },
    body: JSON.stringify({ note }),
  });
}

export function listMyPayouts(params?: {
  voided?: boolean;
  kind?: "expense_payout" | "income_handover";
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.voided != null) q.set("voided", String(params.voided));
  if (params?.kind) q.set("kind", params.kind);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q}` : "";
  return request<
    {
      id: number;
      user_id: number;
      user_name: string;
      kind: string;
      amount: number;
      currency: string;
      payment_method: string;
      note: string;
      overpayment?: number;
      balance_after?: number;
      is_voided?: boolean;
      void_note?: string;
      can_void?: boolean;
      void_blocked_reason?: string | null;
      created_at: string;
    }[]
  >(`/payouts/mine${suffix}`);
}

export function listOrgPayouts(params?: {
  voided?: boolean;
  user_id?: number;
  kind?: "expense_payout" | "income_handover";
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.voided != null) q.set("voided", String(params.voided));
  if (params?.user_id != null) q.set("user_id", String(params.user_id));
  if (params?.kind) q.set("kind", params.kind);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q}` : "";
  return request<
    {
      id: number;
      user_id: number;
      user_name: string;
      kind: string;
      amount: number;
      currency: string;
      payment_method: string;
      note: string;
      overpayment?: number;
      balance_after?: number;
      is_voided?: boolean;
      void_note?: string;
      can_void?: boolean;
      void_blocked_reason?: string | null;
      created_at: string;
    }[]
  >(`/payouts/org${suffix}`);
}

export function voidPayout(id: number, note: string, opts?: { idempotencyKey?: string }) {
  return request(`/payouts/${id}/void`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("pvoid") },
    body: JSON.stringify({ note }),
  });
}

export function transferCash(
  body: { to_email: string; amount: number; comment?: string },
  opts?: { idempotencyKey?: string },
) {
  const idem = opts?.idempotencyKey || newIdemKey("xfer");
  return request<{ sender_record: MoneyRecord; recipient_record: MoneyRecord }>("/transfers", {
    method: "POST",
    headers: { "Idempotency-Key": idem },
    body: JSON.stringify(body),
  });
}

export function createPayout(
  body: {
    user_id: number;
    kind: "expense_payout" | "income_handover";
    amount: number;
    payment_method?: string;
    note?: string;
  },
  opts?: { idempotencyKey?: string },
) {
  const idem = opts?.idempotencyKey || newIdemKey("pay");
  return request("/payouts", {
    method: "POST",
    headers: { "Idempotency-Key": idem },
    body: JSON.stringify(body),
  });
}

export function batchPaySpendings(payment_method = "cash", opts?: { idempotencyKey?: string }) {
  const idem = opts?.idempotencyKey || newIdemKey("bpay");
  return request(`/payouts/batch-spendings?payment_method=${encodeURIComponent(payment_method)}`, {
    method: "POST",
    headers: { "Idempotency-Key": idem },
  });
}

export function batchTakeCash(payment_method = "cash", opts?: { idempotencyKey?: string }) {
  const idem = opts?.idempotencyKey || newIdemKey("bcash");
  return request(`/payouts/batch-cash?payment_method=${encodeURIComponent(payment_method)}`, {
    method: "POST",
    headers: { "Idempotency-Key": idem },
  });
}

export function listMySettlementRequests(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request<
    {
      id: number;
      user_id: number;
      user_name: string;
      kind: string;
      amount: number;
      note: string;
      status: string;
      settled_amount?: number | null;
      payout_id?: number | null;
      created_at: string;
    }[]
  >(`/payouts/requests/mine${qs ? `?${qs}` : ""}`);
}

export function requestSettlement(
  body: {
    kind: "expense_payout" | "income_handover";
    amount: number;
    note?: string;
  },
  opts?: { idempotencyKey?: string },
) {
  return request("/payouts/requests", {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("sreq") },
    body: JSON.stringify(body),
  });
}

export function listSettlementRequests(params?: {
  status?: "pending" | "approved" | "cancelled" | "all";
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request<
    {
      id: number;
      user_id: number;
      user_name: string;
      kind: string;
      amount: number;
      note: string;
      status: string;
      settled_amount?: number | null;
      payout_id?: number | null;
      created_at: string;
    }[]
  >(`/payouts/requests${qs ? `?${qs}` : ""}`);
}

export function approveSettlementRequest(
  id: number,
  paymentMethod: "cash" | "transfer" = "cash",
  opts?: { idempotencyKey?: string },
) {
  const idem = opts?.idempotencyKey || newIdemKey("appr");
  return request(`/payouts/requests/${id}/approve`, {
    method: "POST",
    headers: { "Idempotency-Key": idem },
    body: JSON.stringify({ payment_method: paymentMethod }),
  });
}

export function cancelSettlementRequest(
  id: number,
  note = "",
  opts?: { idempotencyKey?: string },
) {
  return request(`/payouts/requests/${id}/cancel`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("scancel") },
    body: JSON.stringify({ note }),
  });
}

export type BalanceAdjustment = {
  id: number;
  user_id: number;
  user_name: string;
  track: "cash_on_hand" | "spendings";
  amount: number;
  note: string;
  occurred_at: string;
  created_by: number;
  created_at: string;
  is_voided: boolean;
  can_void?: boolean;
  void_blocked_reason?: string | null;
};

export function listAdjustments(params?: {
  voided?: boolean;
  user_id?: number;
  track?: "cash_on_hand" | "spendings";
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.voided != null) q.set("voided", String(params.voided));
  if (params?.user_id != null) q.set("user_id", String(params.user_id));
  if (params?.track) q.set("track", params.track);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request<BalanceAdjustment[]>(`/adjustments${qs ? `?${qs}` : ""}`);
}

export function createAdjustment(
  body: {
    user_id: number;
    track: "cash_on_hand" | "spendings";
    amount: number;
    note: string;
    occurred_at?: string;
  },
  opts?: { idempotencyKey?: string },
) {
  return request<BalanceAdjustment>("/adjustments", {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("adj") },
    body: JSON.stringify(body),
  });
}

export function voidAdjustment(id: number, note: string, opts?: { idempotencyKey?: string }) {
  return request<BalanceAdjustment>(`/adjustments/${id}/void`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("avoid") },
    body: JSON.stringify({ note }),
  });
}

export async function uploadPhoto(
  uri: string,
  opts?: { name?: string; type?: string; idempotencyKey?: string },
) {
  const form = new FormData();
  const name = opts?.name || "receipt.jpg";
  const type = opts?.type || "image/jpeg";
  form.append("file", {
    uri,
    name,
    type,
  } as unknown as Blob);
  const idem = opts?.idempotencyKey || makeIdempotencyKey("photo");
  return request<{ photo_url: string }>(
    "/media/photo",
    {
      method: "POST",
      body: form,
      headers: { "Idempotency-Key": idem },
    },
    { timeoutMs: UPLOAD_TIMEOUT_MS },
  );
}

export function mediaUrl(path: string, token?: string | null): string {
  if (!path) return "";
  // Never attach credentials to absolute third-party URLs
  if (/^https?:\/\//i.test(path)) return path;
  const base = `${API_URL}${path.startsWith("/") ? path : `/${path}`}`;
  // Query auth must use a short-lived media JWT only (never the access token).
  if (!token || !path.startsWith("/media/files/")) return base;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}token=${encodeURIComponent(token)}`;
}

async function getMediaToken(): Promise<string> {
  const now = Date.now();
  if (cachedMediaToken && now < cachedMediaTokenExpMs - 30_000) {
    return cachedMediaToken;
  }
  const res = await request<{ access_token: string }>("/records/media-token", {
    method: "GET",
  });
  cachedMediaToken = res.access_token;
  // API media JWTs are ~15m — refresh a minute early.
  cachedMediaTokenExpMs = now + 14 * 60 * 1000;
  return cachedMediaToken;
}

export async function mediaUrlWithMediaToken(path: string): Promise<string> {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/media/files/")) {
    return mediaUrl(path);
  }
  const token = await getMediaToken();
  return mediaUrl(path, token);
}
