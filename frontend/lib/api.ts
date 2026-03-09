/**
 * API для авторизации и данных.
 * Бэкенд пока не подключён — функции делают запросы на /api/v1/... (rewrites на backend когда он будет готов).
 */

function getApiBase(): string {
  if (typeof window !== "undefined") return "";
  return process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:11001";
}

function apiUrl(path: string): string {
  const base = getApiBase();
  const prefix = base ? `${base.replace(/\/$/, "")}` : "";
  return prefix ? `${prefix}/api/v1/${path}` : `/api/v1/${path}`;
}

const AUTH_TOKEN_KEY = "sport_analytics_token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function authHeaders(): Record<string, string> {
  const t = getAuthToken();
  if (!t) return {};
  return { Authorization: `Bearer ${t}` };
}

// ——— Auth ———

export interface TelegramAuthPayload {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

export async function login(
  email: string,
  password: string
): Promise<{ access_token: string }> {
  const res = await fetch(apiUrl("auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function register(
  email: string,
  password: string,
  acceptTerms: boolean,
  acceptPrivacy: boolean
): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      accept_terms: acceptTerms,
      accept_privacy: acceptPrivacy,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function verifyEmail(
  email: string,
  code: string
): Promise<{ access_token: string }> {
  const res = await fetch(apiUrl("auth/verify-email"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function verifyTelegramCode(
  code: string,
  acceptTerms: boolean,
  acceptPrivacy: boolean
): Promise<{ access_token: string }> {
  const res = await fetch(apiUrl("auth/telegram/verify-code"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      accept_terms: acceptTerms,
      accept_privacy: acceptPrivacy,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function loginWithTelegram(
  payload: TelegramAuthPayload
): Promise<{ access_token: string }> {
  const res = await fetch(apiUrl("auth/login-telegram"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export const AUTH_TOKEN_STORAGE_KEY = AUTH_TOKEN_KEY;
