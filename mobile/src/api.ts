import { storageDelete, storageGet, storageSet } from "./storage";

/** Change to your machine LAN IP when testing on a phone. */
export const API_URL = process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000";

const TOKEN_KEY = "fos_token";
let cachedToken: string | null = null;
const REQUEST_TIMEOUT_MS = 30000;
const UPLOAD_TIMEOUT_MS = 120000;
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
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
  // (a delayed 401 from an old JWT must not wipe a freshly logged-in session).
  const active = await getToken();
  if (requestToken && active && requestToken !== active) {
    return;
  }
  try {
    await clearToken();
  } catch {
    /* ignore */
  }
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

export async function saveToken(token: string) {
  cachedToken = token;
  await storageSet(TOKEN_KEY, token);
}

export async function clearToken() {
  cachedToken = null;
  await storageDelete(TOKEN_KEY);
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

function newClientRequestId(): string {
  return `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  opts?: { timeoutMs?: number },
): Promise<T> {
  const auth = await authHeaders();
  const requestToken = auth.Authorization?.startsWith("Bearer ")
    ? auth.Authorization.slice(7)
    : null;
  const headers: Record<string, string> = {
    ...(isFormDataBody(init.body) ? {} : { "Content-Type": "application/json" }),
    ...auth,
    ...((init.headers as Record<string, string>) || {}),
  };
  if (!headers["X-Request-Id"]) headers["X-Request-Id"] = newClientRequestId();
  const controller = new AbortController();
  const timeoutMs = opts?.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      signal: init.signal || controller.signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error("Request timed out — check connection and try again");
    }
    throw new Error(e instanceof Error ? e.message : "Network request failed");
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

async function requestText(path: string, init: RequestInit = {}): Promise<string> {
  const auth = await authHeaders();
  const requestToken = auth.Authorization?.startsWith("Bearer ")
    ? auth.Authorization.slice(7)
    : null;
  const headers: Record<string, string> = {
    ...auth,
    ...((init.headers as Record<string, string>) || {}),
  };
  if (!headers["X-Request-Id"]) headers["X-Request-Id"] = newClientRequestId();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      signal: init.signal || controller.signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error("Request timed out — check connection and try again");
    }
    throw new Error(e instanceof Error ? e.message : "Network request failed");
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  if (!res.ok) {
    if (res.status === 401) {
      await notifyUnauthorized(requestToken);
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
      detail =
        res.status === 429
          ? formatApiError(
              null,
              res.statusText || `HTTP ${res.status}`,
              429,
              res.headers.get("Retry-After"),
              res.headers.get("X-Request-Id"),
            )
          : res.status === 413
            ? formatApiError(
                null,
                res.statusText || `HTTP ${res.status}`,
                413,
                null,
                res.headers.get("X-Request-Id"),
              )
          : formatApiError(
              null,
              res.statusText || `HTTP ${res.status}`,
              res.status,
              null,
              res.headers.get("X-Request-Id"),
            );
    }
    throw new Error(detail);
  }
  return text;
}

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
    return base;
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
  if (typeof detail === "string") return detail;
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

export function acceptInvite(token: string, password: string, password_confirm: string) {
  return request<AuthToken>("/auth/accept-invite", {
    method: "POST",
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

export function updateOrg(body: { name?: string; currency?: string }) {
  return request<{
    id: number;
    name: string;
    slug: string;
    currency: string;
    currency_locked?: boolean;
  }>("/orgs/me", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export type InviteResult = User & {
  organization_slug?: string;
  must_set_password?: boolean;
  invite_token?: string | null;
  email_sent?: boolean;
};

export function inviteUser(body: {
  email: string;
  full_name: string;
  role: "owner" | "manager" | "employee";
  password?: string;
  password_confirm?: string;
}) {
  return request<InviteResult>("/orgs/invite", {
    method: "POST",
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

export function setMemberActive(id: number, is_active: boolean) {
  return request<User>(`/orgs/members/${id}/active`, {
    method: "POST",
    body: JSON.stringify({ is_active }),
  });
}

export function setMemberRole(id: number, role: "owner" | "manager" | "employee") {
  return request<User>(`/orgs/members/${id}/role`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}

export function resetMemberPassword(
  id: number,
  new_password: string,
  password_confirm: string,
) {
  return request<User>(`/orgs/members/${id}/password`, {
    method: "POST",
    body: JSON.stringify({ new_password, password_confirm }),
  });
}

export function issueMemberResetToken(id: number, opts?: { force?: boolean }) {
  const q = opts?.force ? "?force=true" : "";
  return request<{
    id: number;
    email: string;
    full_name: string;
    organization_slug: string;
    invite_token: string;
    must_set_password: boolean;
    email_sent?: boolean;
  }>(`/orgs/members/${id}/reset-token${q}`, { method: "POST" });
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
export function setBillingPlan(plan: "free" | "trial") {
  return request<BillingInfo>("/billing/plan", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
}

export function setTelegramChat(telegram_chat_id: string) {
  return request<BillingInfo>("/integrations/telegram/chat", {
    method: "POST",
    body: JSON.stringify({ telegram_chat_id }),
  });
}

export function testTelegram() {
  return request<{ ok: boolean }>("/integrations/telegram/test", { method: "POST" });
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
  opts?: { idempotencyKey?: string },
) {
  return request<MoneyRecord>(`/records/${id}/decide`, {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("decide") },
    body: JSON.stringify({ approve, note }),
  });
}

export function decideBatch(
  ids: number[],
  approve: boolean,
  note = "",
  opts?: { idempotencyKey?: string },
) {
  return request<{
    decided: MoneyRecord[];
    skipped: number;
    skipped_insufficient_cash?: number;
    skipped_inactive?: number;
  }>("/records/decide-batch", {
    method: "POST",
    headers: { "Idempotency-Key": opts?.idempotencyKey || newIdemKey("dbatch") },
    body: JSON.stringify({ ids, approve, note }),
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
    overpayment?: number;
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
  opts?: { name?: string; type?: string },
) {
  const form = new FormData();
  const name = opts?.name || "receipt.jpg";
  const type = opts?.type || "image/jpeg";
  form.append("file", {
    uri,
    name,
    type,
  } as unknown as Blob);
  return request<{ photo_url: string }>(
    "/media/photo",
    {
      method: "POST",
      body: form,
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

export async function mediaUrlWithMediaToken(path: string): Promise<string> {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/media/files/")) {
    return mediaUrl(path);
  }
  const res = await request<{ access_token: string }>("/records/media-token");
  return mediaUrl(path, res.access_token);
}
