/**
 * API: в браузере — относительные запросы /api/v1/... (один домен pingwin.pro, без localhost).
 * Явный NEXT_PUBLIC_API_URL задаёт прямой URL бэкенда (например для локальной разработки).
 * На сервере (SSR) — BACKEND_URL или fallback localhost:11001.
 */
function getApiBase(): string {
  if (typeof window !== "undefined") {
    return process.env.NEXT_PUBLIC_API_URL ?? "";
  }
  return process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:11001";
}

function apiUrl(path: string): string {
  const base = getApiBase();
  const prefix = base ? base.replace(/\/$/, "") : "";
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
  const data = (await res.json().catch(() => ({}))) as { detail?: string; code?: string; email?: string };
  if (res.status === 403 && data.code === "email_not_verified" && data.email) {
    const e = new Error(data.detail || "Подтвердите почту") as Error & { code?: string; email?: string };
    e.code = "email_not_verified";
    e.email = data.email;
    throw e;
  }
  if (!res.ok) {
    throw new Error(data.detail || res.statusText);
  }
  return res.json();
}

export async function loginByTelegramCode(code: string): Promise<{ access_token: string }> {
  const res = await fetch(apiUrl("auth/telegram/login-by-code"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export type RegisterResult =
  | { ok: true; message: string; detail: string }
  | { ok: false; email_verified: boolean; detail: string };

export async function register(
  email: string,
  password: string,
  acceptTerms: boolean,
  acceptPrivacy: boolean
): Promise<RegisterResult> {
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
  const data = await res.json().catch(() => ({})) as { detail?: string; email_verified?: boolean };
  if (res.status === 409 && typeof data.email_verified === "boolean") {
    return { ok: false, email_verified: data.email_verified, detail: data.detail || "Email уже зарегистрирован" };
  }
  if (!res.ok) {
    throw new Error(data.detail || res.statusText);
  }
  return { ok: true, message: (data as { message?: string }).message ?? "check_email", detail: data.detail ?? "" };
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

export async function resendVerificationCode(email: string): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/resend-verification-code"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function requestPasswordReset(email: string): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/request-password-reset"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function resetPassword(
  email: string,
  code: string,
  newPassword: string
): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/reset-password"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code, new_password: newPassword }),
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

// ——— Me (profile & settings) ———

export interface MeProfile {
  email: string;
  email_masked: string;
  telegram_linked: boolean;
  telegram_username: string | null;
  email_linked: boolean;
  notification_email: string | null;
  notification_email_masked: string | null;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  is_telegram_only: boolean;
}

export async function getMe(): Promise<MeProfile> {
  const res = await fetch(apiUrl("me"), { headers: authHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface MeSettingsUpdate {
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
}

export async function patchMe(data: MeSettingsUpdate): Promise<MeProfile> {
  const res = await fetch(apiUrl("me"), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function requestTelegramLinkCode(): Promise<{
  code: string;
  expires_minutes: number;
  detail: string;
}> {
  const res = await fetch(apiUrl("auth/telegram/request-link-code"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function requestLinkEmail(email: string): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/request-link-email"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function verifyLinkEmail(
  email: string,
  code: string
): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/verify-link-email"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email, code }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function unlinkTelegram(): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("me/unlink-telegram"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function unlinkNotificationEmail(): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("me/unlink-notification-email"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

// ——— Настольный теннис: линия (BetsAPI кэш) ———

export interface TableTennisLineEvent {
  id: string | number;
  league_id: string;
  league_name: string;
  home_id: string;
  home_name: string;
  away_id: string;
  away_name: string;
  time?: number;
  status?: string;  // scheduled | live | finished | postponed | cancelled
  odds_1?: number | null;
  odds_2?: number | null;
  /** Прогноз (если есть); для фильтра «только с прогнозом» */
  forecast?: string | null;
}

export interface TableTennisLeague {
  id: string;
  name: string;
}

export interface TableTennisPlayer {
  id: string;
  name: string;
}

export interface TableTennisPlayersByLeague {
  league_id: string;
  league_name: string;
  players: TableTennisPlayer[];
}

export interface TableTennisLineResponse {
  events: TableTennisLineEvent[];
  leagues: TableTennisLeague[];
  players_by_league: TableTennisPlayersByLeague[];
  updated_at: number | null;
}

export interface TableTennisLiveEvent {
  id: string | number;
  league_id: string;
  league_name: string;
  home_id: string;
  home_name: string;
  away_id: string;
  away_name: string;
  time?: number;
  status?: string;
  odds_1?: number | null;
  odds_2?: number | null;
  forecast?: string | null;
  sets_score?: string | null; // общий счёт по сетам, например "2-1"
  sets?: Record<string, { home: string; away: string }>; // счёт по каждому сету
  last_score_changed_at?: number | null;
  is_stale?: boolean;
  forecast_confidence?: number | null;
}

export interface TableTennisLiveResponse {
  events: TableTennisLiveEvent[];
  updated_at: number | null;
}

export interface TableTennisMatchCard {
  match: TableTennisLiveEvent | null;
  forecast?: string | null;
  forecast_confidence?: number | null;
  analytics?: {
    head_to_head?: {
      total: number;
      home_wins: number;
      away_wins: number;
    };
    justification?: string | null;
    home_strengths?: string[];
    home_weaknesses?: string[];
    away_strengths?: string[];
    away_weaknesses?: string[];
  };
  home_stats?: {
    total_matches: number;
    finished_matches: number;
    wins: number;
    losses: number;
    win_rate: number | null;
    upcoming_matches: number;
    leagues_count: number;
  };
  away_stats?: {
    total_matches: number;
    finished_matches: number;
    wins: number;
    losses: number;
    win_rate: number | null;
    upcoming_matches: number;
    leagues_count: number;
  };
}

export interface TableTennisPlayerCard {
  player: { id: string; name: string } | null;
  stats?: {
    total_matches: number;
    finished_matches: number;
    wins: number;
    losses: number;
    win_rate: number | null;
    upcoming_matches: number;
    leagues_count: number;
  };
  upcoming_matches: TableTennisLiveEvent[];
  finished_matches: TableTennisLiveEvent[];
  pagination?: {
    upcoming: { page: number; page_size: number; total: number };
    finished: { page: number; page_size: number; total: number };
  };
}

export interface TableTennisPlayersPageResponse {
  items: Array<{
    id: string;
    name: string;
    matches_total: number;
    matches_finished: number;
    matches_upcoming: number;
  }>;
  page: number;
  page_size: number;
  total: number;
}

export interface TableTennisLeaguesPageResponse {
  items: Array<{
    id: string;
    name: string;
    matches_total: number;
    matches_finished: number;
    matches_upcoming: number;
  }>;
  page: number;
  page_size: number;
  total: number;
}

export interface TableTennisLeagueCard {
  league: { id: string; name: string } | null;
  stats?: {
    upcoming_matches: number;
    finished_matches: number;
    total_matches: number;
  };
  upcoming_matches: TableTennisLiveEvent[];
  finished_matches: TableTennisLiveEvent[];
  pagination?: {
    upcoming: { page: number; page_size: number; total: number };
    finished: { page: number; page_size: number; total: number };
  };
  filters?: {
    date_from?: string | null;
    date_to?: string | null;
  };
}

export interface TableTennisForecastItem {
  event_id: string;
  league_id: string | null;
  league_name: string | null;
  home_id: string | null;
  home_name: string | null;
  away_id: string | null;
  away_name: string | null;
  forecast_text: string;
  confidence_pct: number | null;
  status: string;
  created_at: number | null;
  resolved_at: number | null;
  final_status: string | null;
  final_sets_score: string | null;
  starts_at: number | null;
  odds_1: number | null;
  odds_2: number | null;
  channel?: string | null;
  event_status?: string | null;
  sets_score?: string | null;
  live_score?: Record<string, { home: string | number | null; away: string | number | null }> | null;
  forecast_odds?: number | null;
  forecast_lead_seconds?: number | null;
}

export interface TableTennisForecastsResponse {
  items: TableTennisForecastItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface TableTennisForecastStats {
  total: number;
  by_status: Record<string, number>;
  hit_rate: number | null;
}

export interface TableTennisForecastsStreamPayload {
  stats: TableTennisForecastStats;
  forecasts: TableTennisForecastsResponse;
}

export interface TableTennisResultsResponse {
  items: TableTennisLiveEvent[];
  page: number;
  page_size: number;
  total: number;
  leagues: Array<{ id: string; name: string }>;
  filters?: {
    league_id?: string | null;
    player_query?: string | null;
    date_from?: string | null;
    date_to?: string | null;
  };
}

export async function getTableTennisLine(): Promise<TableTennisLineResponse> {
  const res = await fetch(apiUrl("table-tennis/line"), { headers: authHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisLive(): Promise<TableTennisLiveResponse> {
  const res = await fetch(apiUrl("table-tennis/live"), { headers: authHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisMatchCard(matchId: string): Promise<TableTennisMatchCard> {
  const res = await fetch(apiUrl(`table-tennis/matches/${encodeURIComponent(matchId)}`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisPlayerCard(playerId: string): Promise<TableTennisPlayerCard> {
  const res = await fetch(apiUrl(`table-tennis/players/${encodeURIComponent(playerId)}/card`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisPlayers(
  page = 1,
  pageSize = 30,
  q = ""
): Promise<TableTennisPlayersPageResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    q,
  });
  const res = await fetch(apiUrl(`table-tennis/players?${params.toString()}`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisLeagues(
  page = 1,
  pageSize = 30,
  q = ""
): Promise<TableTennisLeaguesPageResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    q,
  });
  const res = await fetch(apiUrl(`table-tennis/leagues?${params.toString()}`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisPlayerCardPaged(
  playerId: string,
  pageUpcoming = 1,
  pageFinished = 1,
  pageSize = 20
): Promise<TableTennisPlayerCard> {
  const params = new URLSearchParams({
    page_upcoming: String(pageUpcoming),
    page_finished: String(pageFinished),
    page_size: String(pageSize),
  });
  const res = await fetch(
    apiUrl(`table-tennis/players/${encodeURIComponent(playerId)}/card?${params.toString()}`),
    { headers: authHeaders() }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisLeagueCard(
  leagueId: string,
  pageUpcoming = 1,
  pageFinished = 1,
  pageSize = 20,
  dateFrom = "",
  dateTo = ""
): Promise<TableTennisLeagueCard> {
  const params = new URLSearchParams({
    page_upcoming: String(pageUpcoming),
    page_finished: String(pageFinished),
    page_size: String(pageSize),
    date_from: dateFrom,
    date_to: dateTo,
  });
  const res = await fetch(
    apiUrl(`table-tennis/leagues/${encodeURIComponent(leagueId)}/card?${params.toString()}`),
    { headers: authHeaders() }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisForecastStats(params?: {
  date_from?: string;
  date_to?: string;
  league_id?: string;
  channel?: string;
}): Promise<TableTennisForecastStats> {
  const search = new URLSearchParams();
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.league_id) search.set("league_id", params.league_id);
  if (params?.channel) search.set("channel", params.channel);
  const qs = search.toString();
  const res = await fetch(apiUrl(`table-tennis/forecasts/stats${qs ? `?${qs}` : ""}`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisForecasts(params?: {
  page?: number;
  page_size?: number;
  status?: string;
  league_id?: string;
  date_from?: string;
  date_to?: string;
  channel?: string;
}): Promise<TableTennisForecastsResponse> {
  const search = new URLSearchParams();
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  if (params?.status) search.set("status", params.status);
  if (params?.league_id) search.set("league_id", params.league_id);
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.channel) search.set("channel", params.channel);
  const qs = search.toString();
  const res = await fetch(apiUrl(`table-tennis/forecasts${qs ? `?${qs}` : ""}`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export function subscribeTableTennisForecastsStream(
  channel: string,
  onData: (data: TableTennisForecastsStreamPayload) => void,
  onError?: (err: Error) => void
): () => void {
  const ac = new AbortController();
  (async () => {
    let reconnectDelayMs = 1000;
    while (!ac.signal.aborted) {
      try {
        const qs = new URLSearchParams({ channel }).toString();
        const res = await fetch(apiUrl(`table-tennis/forecasts/stream?${qs}`), {
          headers: authHeaders(),
          cache: "no-store",
          signal: ac.signal,
        });
        if (!res.ok) throw new Error(res.statusText);
        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");
        reconnectDelayMs = 1000;
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split(/\r?\n/);
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6)) as TableTennisForecastsStreamPayload;
              onData(data);
            } catch {
              // ignore malformed json
            }
          }
        }
      } catch (e) {
        if (ac.signal.aborted) break;
        if (onError && e instanceof Error) onError(e);
        await new Promise((r) => setTimeout(r, reconnectDelayMs));
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10000);
      }
    }
  })();
  return () => ac.abort();
}

export async function getTableTennisResults(
  page = 1,
  pageSize = 30,
  leagueId = "",
  playerQuery = "",
  dateFrom = "",
  dateTo = ""
): Promise<TableTennisResultsResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    league_id: leagueId,
    player_query: playerQuery,
    date_from: dateFrom,
    date_to: dateTo,
  });
  const res = await fetch(apiUrl(`table-tennis/results?${params.toString()}`), {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

/**
 * Подписка на SSE-поток лайва: обновления приходят без перезагрузки страницы.
 * Возвращает функцию отписки (вызвать при размонтировании).
 */
export function subscribeTableTennisLiveStream(
  onData: (data: TableTennisLiveResponse) => void,
  onError?: (err: Error) => void
): () => void {
  const ac = new AbortController();
  (async () => {
    let reconnectDelayMs = 1000;
    while (!ac.signal.aborted) {
      try {
        const res = await fetch(apiUrl("table-tennis/live/stream"), {
          headers: authHeaders(),
          cache: "no-store",
          signal: ac.signal,
        });
        if (!res.ok) {
          throw new Error(res.statusText);
        }
        const reader = res.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }
        reconnectDelayMs = 1000;
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split(/\r?\n/);
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6)) as TableTennisLiveResponse;
              onData(data);
            } catch {
              // ignore malformed json
            }
          }
        }
      } catch (e) {
        if ((e as { name?: string }).name === "AbortError" || ac.signal.aborted) return;
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
      await new Promise((r) => setTimeout(r, reconnectDelayMs));
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10000);
    }
  })();
  return () => ac.abort();
}

/**
 * Подписка на SSE-поток линии: обновления приходят без перезагрузки страницы.
 * Возвращает функцию отписки (вызвать при размонтировании).
 */
export function subscribeTableTennisLineStream(
  onData: (data: TableTennisLineResponse) => void,
  onError?: (err: Error) => void
): () => void {
  const ac = new AbortController();
  (async () => {
    let reconnectDelayMs = 1000;
    while (!ac.signal.aborted) {
      try {
        const res = await fetch(apiUrl("table-tennis/line/stream"), {
          headers: authHeaders(),
          cache: "no-store",
          signal: ac.signal,
        });
        if (!res.ok) {
          throw new Error(res.statusText);
        }
        const reader = res.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }
        reconnectDelayMs = 1000;
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split(/\r?\n/);
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6)) as TableTennisLineResponse;
              onData(data);
            } catch {
              // ignore malformed json
            }
          }
        }
      } catch (e) {
        if ((e as { name?: string }).name === "AbortError" || ac.signal.aborted) return;
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
      await new Promise((r) => setTimeout(r, reconnectDelayMs));
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10000);
    }
  })();
  return () => ac.abort();
}
