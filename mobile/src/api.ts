import * as SecureStore from "expo-secure-store";

/** Change to your machine LAN IP when testing on a phone. */
export const API_URL = process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000";

const TOKEN_KEY = "fos_token";

export type User = {
  id: number;
  email: string;
  full_name: string;
  role: "owner" | "manager" | "employee";
  organization_id: number;
};

export type MoneyRecord = {
  id: number;
  kind: "expense" | "fuel" | "income";
  status: "pending" | "approved" | "rejected";
  amount: number;
  currency: string;
  category: string;
  comment: string;
  created_at: string;
};

async function authHeaders(): Promise<Record<string, string>> {
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function saveToken(token: string) {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearToken() {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}

export async function getToken() {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
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
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data as T;
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

export function myBalance() {
  return request<{ cash_on_hand: number; currency: string; pending_count: number }>(
    "/records/balance/me",
  );
}

export function myRecords() {
  return request<MoneyRecord[]>("/records/mine");
}

export function createRecord(body: {
  kind: "expense" | "fuel" | "income";
  amount: number;
  category?: string;
  comment?: string;
  payment_method?: string;
  client_name?: string;
  liters?: number;
  odometer?: number;
}) {
  return request<MoneyRecord>("/records", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function pendingRecords() {
  return request<MoneyRecord[]>("/records/pending");
}

export function decideRecord(id: number, approve: boolean) {
  return request<MoneyRecord>(`/records/${id}/decide`, {
    method: "POST",
    body: JSON.stringify({ approve }),
  });
}
