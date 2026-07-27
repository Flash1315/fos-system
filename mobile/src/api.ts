import { storageDelete, storageGet, storageSet } from "./storage";

/** Change to your machine LAN IP when testing on a phone. */
export const API_URL = process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000";

const TOKEN_KEY = "fos_token";

export type User = {
  id: number;
  email: string;
  full_name: string;
  role: "owner" | "manager" | "employee";
  organization_id: number;
  is_active?: boolean;
};

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
  created_at: string;
  occurred_at?: string | null;
  decided_at?: string | null;
  decided_by?: number | null;
};

export type OrgReport = {
  currency: string;
  approved_expense_total: number;
  approved_fuel_total: number;
  approved_income_cash: number;
  approved_income_transfer: number;
  pending_count: number;
  team_count: number;
  cash_position: number;
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
  const token = await storageGet(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function saveToken(token: string) {
  await storageSet(TOKEN_KEY, token);
}

export async function clearToken() {
  await storageDelete(TOKEN_KEY);
}

export async function getToken() {
  return storageGet(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(await authHeaders()),
    ...((init.headers as Record<string, string>) || {}),
  };
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    throw new Error(formatApiError(data, res.statusText || `HTTP ${res.status}`));
  }
  return data as T;
}

function formatApiError(data: unknown, fallback: string): string {
  if (typeof data !== "object" || !data || !("detail" in data)) return fallback;
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

export function registerOrg(body: {
  name: string;
  slug: string;
  currency?: string;
  owner_email: string;
  owner_name: string;
  owner_password: string;
}) {
  return request<{ access_token: string; user: User }>("/orgs/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function login(body: {
  email: string;
  password: string;
  organization_slug: string;
}) {
  return request<{ access_token: string; user: User }>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function me() {
  return request<User>("/auth/me");
}

export function changePassword(current_password: string, new_password: string) {
  return request<{ ok: boolean }>("/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
}

export function myOrg() {
  return request<{ id: number; name: string; slug: string; currency: string }>("/orgs/me");
}

export function inviteUser(body: {
  email: string;
  full_name: string;
  role: "owner" | "manager" | "employee";
  password: string;
}) {
  return request<User>("/orgs/invite", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listMembers() {
  return request<User[]>("/orgs/members");
}

export function orgDirectory() {
  return request<User[]>("/orgs/directory");
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

export function myBalance() {
  return request<{
    cash_on_hand: number;
    spendings: number;
    currency: string;
    pending_count: number;
  }>("/records/balance/me");
}

export type TeamBalance = {
  user_id: number;
  full_name: string;
  role: string;
  cash_on_hand: number;
  spendings: number;
  owed_to_employee: number;
  pending_count: number;
};

export function teamBalances() {
  return request<TeamBalance[]>("/records/balance/team");
}

export function myRecords(params?: { kind?: string; status?: string; purpose?: string; q?: string }) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.purpose) q.set("purpose", params.purpose);
  if (params?.q) q.set("q", params.q);
  const suffix = q.toString() ? `?${q}` : "";
  return request<MoneyRecord[]>(`/records/mine${suffix}`);
}

export function orgRecords(params?: {
  kind?: string;
  status?: string;
  purpose?: string;
  created_by?: number;
  q?: string;
}) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.purpose) q.set("purpose", params.purpose);
  if (params?.created_by != null) q.set("created_by", String(params.created_by));
  if (params?.q) q.set("q", params.q);
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

export function createRecord(body: {
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
}) {
  return request<MoneyRecord>("/records", {
    method: "POST",
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
  },
) {
  return request<MoneyRecord>(`/records/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function pendingRecords() {
  return request<MoneyRecord[]>("/records/pending");
}

export function decideRecord(id: number, approve: boolean, note = "") {
  return request<MoneyRecord>(`/records/${id}/decide`, {
    method: "POST",
    body: JSON.stringify({ approve, note }),
  });
}

export function decideBatch(ids: number[], approve: boolean, note = "") {
  return request<MoneyRecord[]>("/records/decide-batch", {
    method: "POST",
    body: JSON.stringify({ ids, approve, note }),
  });
}

export function orgReport(days?: number) {
  const suffix = days ? `?days=${days}` : "";
  return request<OrgReport>(`/reports/org${suffix}`);
}

export function myReport(days?: number) {
  const suffix = days ? `?days=${days}` : "";
  return request<MyReport>(`/reports/me${suffix}`);
}

export function exportReportCsv(days?: number) {
  const suffix = days ? `?days=${days}` : "";
  return `${API_URL}/reports/export.csv${suffix}`;
}

export function commentRecord(id: number, note: string) {
  return request<MoneyRecord>(`/records/${id}/comment`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
}

export function cancelRecord(id: number) {
  return request<MoneyRecord>(`/records/${id}`, { method: "DELETE" });
}

export function listMyPayouts() {
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
      created_at: string;
    }[]
  >("/payouts/mine");
}

export function listOrgPayouts() {
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
      created_at: string;
    }[]
  >("/payouts/org");
}

export function transferCash(body: { to_email: string; amount: number; comment?: string }) {
  return request<{ sender_record: MoneyRecord; recipient_record: MoneyRecord }>("/transfers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function createPayout(body: {
  user_id: number;
  kind: "expense_payout" | "income_handover";
  amount: number;
  payment_method?: string;
  note?: string;
  overpayment?: number;
}) {
  return request("/payouts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function batchPaySpendings(payment_method = "cash") {
  return request(`/payouts/batch-spendings?payment_method=${encodeURIComponent(payment_method)}`, {
    method: "POST",
  });
}

export function requestSettlement(body: {
  kind: "expense_payout" | "income_handover";
  amount: number;
  note?: string;
}) {
  return request("/payouts/requests", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listSettlementRequests() {
  return request<
    {
      id: number;
      user_id: number;
      user_name: string;
      kind: string;
      amount: number;
      note: string;
      status: string;
      created_at: string;
    }[]
  >("/payouts/requests");
}

export function approveSettlementRequest(id: number) {
  return request(`/payouts/requests/${id}/approve`, { method: "POST" });
}

export function cancelSettlementRequest(id: number) {
  return request(`/payouts/requests/${id}/cancel`, { method: "POST" });
}

export async function uploadPhoto(uri: string, name = "receipt.jpg") {
  const form = new FormData();
  form.append("file", {
    uri,
    name,
    type: "image/jpeg",
  } as unknown as Blob);
  return request<{ photo_url: string }>("/media/photo", {
    method: "POST",
    body: form,
  });
}

export function mediaUrl(path: string) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return `${API_URL}${path}`;
}
