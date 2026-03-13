// В браузере — относительный путь (Next.js rewrites проксирует на backend). На сервере — BACKEND_URL или localhost.
function getApiBase(): string {
  if (typeof window !== "undefined") return "";
  return process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:12000";
}
const API_BASE = getApiBase();

/** URL для запроса к API (в браузере — относительный /api/v1/..., без хоста). */
function apiUrl(path: string): string {
  const base = getApiBase();
  return base ? `${base.replace(/\/$/, "")}/api/v1/${path}` : `/api/v1/${path}`;
}
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:12000";

const AUTH_TOKEN_KEY = "sport_analyzator_token";
const REQUEST_TIMEOUT_MS = 12_000;
const inFlightGetRequests = new Map<string, Promise<unknown>>();

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const t = getAuthToken();
  if (!t) return {};
  return { Authorization: `Bearer ${t}` };
}

type FetchJsonOptions = {
  headers?: Record<string, string>;
  dedupeKey?: string;
  timeoutMs?: number;
  cache?: RequestCache;
};

async function fetchJson<T>(url: string, options?: FetchJsonOptions): Promise<T> {
  const dedupeKey = options?.dedupeKey ?? `GET:${url}`;
  const existing = inFlightGetRequests.get(dedupeKey);
  if (existing) return existing as Promise<T>;

  const promise = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options?.timeoutMs ?? REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(url, {
        signal: controller.signal,
        headers: options?.headers,
        cache: options?.cache ?? "no-store",
      });
      if (!res.ok) throw new Error(res.statusText);
      return (await res.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  })();

  inFlightGetRequests.set(dedupeKey, promise);
  try {
    return await promise;
  } finally {
    inFlightGetRequests.delete(dedupeKey);
  }
}

export interface Player {
  id: string;
  name: string;
  /** BetsAPI/b365 image_id для построения URL аватарки */
  image_id?: string | null;
  country?: string | null;
}

/** URL аватарки игрока по image_id (BetsAPI/b365 assets). Без image_id возвращает null. */
export function getPlayerImageUrl(imageId: string | null | undefined): string | null {
  if (!imageId?.trim()) return null;
  return `https://assets.b365api.com/images/team/s/${encodeURIComponent(imageId.trim())}.png`;
}

export interface League {
  id: string;
  name: string;
  country: string | null;
}

export interface MatchScore {
  set_number: number;
  home_score: number;
  away_score: number;
  /** Заполняется бэкендом: сет завершён (учтён в счёте по сетам). */
  is_completed?: boolean;
}

export interface OddsSnapshot {
  bookmaker: string;
  market: string;
  selection: string;
  odds: string;
  implied_probability?: string | null;
  line_value?: string | null;
  phase?: string | null;
  timestamp?: string | null;
  snapshot_time?: string | null;
  score_at_snapshot?: string | null;
}

export interface MatchResult {
  final_score: string;
  winner_id: string | null;
  winner_name: string | null;
  finished_at: string | null;
}

export interface Match {
  id: string;
  provider_match_id: string;
  status: string;
  start_time: string;
  started_at?: string | null;
  finished_at?: string | null;
  /** Обновлён в БД — для сравнения «новее/старше», чтобы не подменять счёт старым ответом */
  updated_at?: string | null;
  league: League | null;
  home_player: Player | null;
  away_player: Player | null;
  scores: MatchScore[];
  /** Выиграно сетов (только завершённые). Заполняется бэкендом. */
  home_sets_won?: number;
  away_sets_won?: number;
  odds_snapshots?: OddsSnapshot[];
  result?: MatchResult | null;
}

/** Список матчей (фильтр по лиге и т.д.). Для линии/лайва — fetchMatchesOverview, для завершённых — fetchFinishedMatches. */
export async function fetchMatches(
  path: "matches",
  params?: Record<string, string | number>
): Promise<Match[]> {
  let pathWithQuery = apiUrl(path);
  if (params && Object.keys(params).length > 0) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => search.set(k, String(v)));
    pathWithQuery += `?${search.toString()}`;
  }
  const url =
    typeof window !== "undefined"
      ? pathWithQuery
      : new URL(pathWithQuery, "http://localhost:12000").toString();
  return fetchJson<Match[]>(url);
}

export interface MatchesOverviewResponse {
  live: Match[];
  upcoming: Match[];
}

/** Один запрос вместо двух: лайв + линия. Всегда без кэша браузера — актуальные данные. */
export async function fetchMatchesOverview(params?: {
  limit_live?: number;
  limit_upcoming?: number;
}): Promise<MatchesOverviewResponse> {
  const search = new URLSearchParams();
  if (params?.limit_live != null) search.set("limit_live", String(params.limit_live));
  if (params?.limit_upcoming != null) search.set("limit_upcoming", String(params.limit_upcoming));
  const path = `${apiUrl("matches/overview")}?${search.toString()}`;
  const url =
    typeof window !== "undefined"
      ? path
      : new URL(path, "http://localhost:12000").toString();
  return fetchJson<MatchesOverviewResponse>(url, { cache: "no-store" });
}

export interface FinishedMatchesResponse {
  total: number;
  items: Match[];
}

export async function fetchFinishedMatches(params?: {
  limit?: number;
  offset?: number;
  date_from?: string;
  date_to?: string;
  league_id?: string;
  player_id?: string;
}): Promise<FinishedMatchesResponse> {
  const url = new URL(
    apiUrl("matches/finished"),
    typeof window !== "undefined" ? window.location.origin : "http://localhost:12000"
  );
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    });
  }
  return fetchJson<FinishedMatchesResponse>(url.toString());
}

export async function fetchMatchesByLeague(leagueId: string, status?: string): Promise<Match[]> {
  const url = new URL(
    apiUrl("matches"),
    typeof window !== "undefined" ? window.location.origin : "http://localhost:12000"
  );
  url.searchParams.set("league_id", leagueId);
  if (status) url.searchParams.set("status", status);
  return fetchJson<Match[]>(url.toString());
}

export async function fetchMatch(id: string): Promise<Match> {
  const path = apiUrl(`matches/${id}`);
  const url =
    typeof window !== "undefined" ? path : new URL(path, "http://localhost:12000").toString();
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export interface MatchAnalytics {
  recommendations: { text: string; confidence_pct: number }[];
  home_strengths: string[];
  home_weaknesses: string[];
  away_strengths: string[];
  away_weaknesses: string[];
  justification: string;
}

export async function fetchMatchAnalytics(matchId: string): Promise<MatchAnalytics> {
  const res = await fetch(apiUrl(`matches/${matchId}/analytics`), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

/** Прогнозы по матчам (на основе истории и статистики). Только если у обоих игроков ≥2 матчей. */
export async function fetchMatchRecommendations(matchIds: string[]): Promise<Record<string, string | null>> {
  if (matchIds.length === 0) return {};
  const params = new URLSearchParams({ match_ids: matchIds.join(",") });
  return fetchJson<Record<string, string | null>>(apiUrl("matches/recommendations") + "?" + params.toString());
}

/** Сохранённый прогноз из таблицы линии/лайва (та же, что в колонке «Прогноз»). */
export async function fetchStoredRecommendation(matchId: string): Promise<string | null> {
  const res = await fetch(apiUrl(`matches/${matchId}/stored-recommendation`), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  const data = await res.json();
  return data.recommendation ?? null;
}

export interface LiveRecommendationItem {
  text: string;
  confidence_pct: number;
  odds: number;
  set_number: number;
}

export interface LiveRecommendationsResponse {
  items: LiveRecommendationItem[];
}

/** Прогнозы в моменте (только лайв): на будущие сеты, кф ≥ 1.3. */
export async function fetchLiveRecommendations(matchId: string): Promise<LiveRecommendationsResponse> {
  const res = await fetch(apiUrl(`matches/${matchId}/live-recommendations`), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchLeagues(params?: Record<string, string | number>): Promise<League[]> {
  const url = new URL(
    apiUrl("leagues"),
    typeof window !== "undefined" ? window.location.origin : "http://localhost:12000"
  );
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  return fetchJson<League[]>(url.toString(), { timeoutMs: 9_000 });
}

export interface PlayerStats {
  total_matches: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  wins_first_set?: number;
  matches_with_first_set?: number;
  win_first_set_pct?: number | null;
  wins_second_set?: number;
  matches_with_second_set?: number;
  win_second_set_pct?: number | null;
  total_sets_played?: number;
  avg_sets_per_match?: number | null;
  set_win_pct_by_position?: { set_number: number; wins: number; total: number; pct: number | null }[];
  set_patterns?: { pattern: string; count: number; pct: number | null }[];
}

export async function fetchPlayer(id: string): Promise<Player> {
  const res = await fetch(apiUrl(`players/${id}`), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchPlayers(params?: { search?: string; limit?: number; offset?: number }): Promise<Player[]> {
  const url = new URL(
    apiUrl("players"),
    typeof window !== "undefined" ? window.location.origin : "http://localhost:12000"
  );
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    });
  }
  return fetchJson<Player[]>(url.toString());
}

export async function fetchPlayerStats(id: string): Promise<PlayerStats> {
  const res = await fetch(apiUrl(`players/${id}/stats`), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchPlayerMatches(
  id: string,
  params?: { status?: string; limit?: number; offset?: number }
): Promise<Match[]> {
  const url = new URL(
    apiUrl(`players/${id}/matches`),
    typeof window !== "undefined" ? window.location.origin : "http://localhost:12000"
  );
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  return fetchJson<Match[]>(url.toString());
}

export function getWsUrl(): string {
  const envWsRaw = (process.env.NEXT_PUBLIC_WS_URL || "").trim();

  const normalizeEnvWs = (raw: string): URL | null => {
    if (!raw) return null;
    let candidate = raw.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
    if (/^wss?:[^/]/i.test(candidate)) {
      candidate = candidate.replace(/^wss?:/i, (m) => `${m}//`);
    }
    try {
      const parsed = new URL(candidate);
      if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") return null;
      if (!parsed.pathname || parsed.pathname === "/") parsed.pathname = "/ws";
      return parsed;
    } catch {
      return null;
    }
  };

  if (typeof window !== "undefined") {
    const parsedEnv = normalizeEnvWs(envWsRaw);
    if (parsedEnv) {
      const pageHost = window.location.hostname;
      const isPageLocal = pageHost === "localhost" || pageHost === "127.0.0.1";
      const isEnvLocal = parsedEnv.hostname === "localhost" || parsedEnv.hostname === "127.0.0.1";
      // If frontend opened remotely, never keep localhost for WS.
      if (!isPageLocal && isEnvLocal) parsedEnv.hostname = pageHost;
      return parsedEnv.toString();
    }
    // Same origin: WebSocket по тому же домену (проксирует nginx на бэкенд)
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/ws`;
  }

  return normalizeEnvWs(envWsRaw)?.toString() || "ws://localhost:12000/ws";
}

export async function login(email: string, password: string): Promise<{ access_token: string }> {
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
): Promise<{ message: string; detail: string }> {
  const res = await fetch(apiUrl("auth/register"), {
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

/** Payload from Telegram Login Widget callback */
export interface TelegramAuthPayload {
  id: number;
  first_name: string;
  last_name: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

export async function loginWithTelegram(
  payload: TelegramAuthPayload,
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

export interface SignalItem {
  id: string;
  match_id: string;
  market_type: string;
  selection: string;
  outcome: string;
  created_at: string;
}

export interface SignalStatsDay {
  date: string;
  total: number;
  won: number;
  lost: number;
  pending: number;
}

export interface SignalStatsResponse {
  total: number;
  won: number;
  lost: number;
  pending: number;
  by_day: SignalStatsDay[];
}

export async function fetchSignals(params?: {
  match_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}): Promise<SignalItem[]> {
  const url = new URL(apiUrl("signals"), typeof window !== "undefined" ? window.location.origin : "http://localhost:12000");
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  return fetchJson<SignalItem[]>(url.toString());
}

export type SignalsStatsParams = {
  days?: number;
  date_from?: string;
  date_to?: string;
};

export async function fetchSignalsStats(params?: number | SignalsStatsParams): Promise<SignalStatsResponse> {
  const url = new URL(apiUrl("signals/stats"), typeof window !== "undefined" ? window.location.origin : "http://localhost:12000");
  if (typeof params === "number") {
    url.searchParams.set("days", String(params));
  } else if (params) {
    if (params.days != null) url.searchParams.set("days", String(params.days));
    if (params.date_from) url.searchParams.set("date_from", params.date_from);
    if (params.date_to) url.searchParams.set("date_to", params.date_to);
  }
  return fetchJson<SignalStatsResponse>(url.toString());
}

export interface RecommendationStatsItem {
  match_id: string;
  league_name: string;
  start_time: string;
  started_at: string | null;
  home_name: string;
  away_name: string;
  recommendation_text: string;
  final_score: string | null;
  winner_name: string | null;
  correct: boolean | null;
  odds_at_recommendation: number | null;
  minutes_before_start: number | null;
  created_at: string | null;
}

export interface RecommendationStatsResponse {
  total: number;
  correct: number;
  wrong: number;
  pending: number;
  bank_profit_rub?: number;
  avg_odds?: number | null;
  cancelled_or_no_data_count?: number;
  cancelled_or_no_data_pct?: number;
  items: RecommendationStatsItem[];
  page: number;
  per_page: number;
  total_filtered: number;
  total_pages: number;
}

export type RecommendationResultFilter = "all" | "correct" | "wrong" | "pending";
export type RecommendationChannelFilter = "all" | "free" | "vip";

export interface FetchRecommendationsStatsParams {
  page?: number;
  per_page?: number;
  result_filter?: RecommendationResultFilter;
  odds_min?: number;
  odds_max?: number;
  days?: number;
  date_from?: string;
  date_to?: string;
  sport_key?: string;
  channel?: RecommendationChannelFilter;
}

export async function fetchRecommendationsStats(params?: FetchRecommendationsStatsParams): Promise<RecommendationStatsResponse> {
  const url = new URL(apiUrl("statistics/recommendations"), typeof window !== "undefined" ? window.location.origin : "http://localhost:12000");
  if (params?.page != null) url.searchParams.set("page", String(params.page));
  if (params?.per_page != null) url.searchParams.set("per_page", String(params.per_page));
  if (params?.result_filter != null && params.result_filter !== "all") url.searchParams.set("result_filter", params.result_filter);
  if (params?.odds_min != null) url.searchParams.set("odds_min", String(params.odds_min));
  if (params?.odds_max != null) url.searchParams.set("odds_max", String(params.odds_max));
  if (params?.days != null) url.searchParams.set("days", String(params.days));
  if (params?.date_from) url.searchParams.set("date_from", params.date_from);
  if (params?.date_to) url.searchParams.set("date_to", params.date_to);
  if (params?.sport_key) url.searchParams.set("sport_key", params.sport_key);
  if (params?.channel && params.channel !== "all") url.searchParams.set("channel", params.channel);
  return fetchJson<RecommendationStatsResponse>(url.toString(), { cache: "no-store" });
}

export interface SignalLandingStatsResponse {
  free_channel: {
    day: { total: number; won: number; lost: number };
    week: { total: number; won: number; lost: number };
    month: { total: number; won: number; lost: number };
  };
  paid_subscription: {
    day: { total: number; won: number; lost: number };
    week: { total: number; won: number; lost: number };
    month: { total: number; won: number; lost: number };
  };
}

export async function fetchSignalsLandingStats(): Promise<SignalLandingStatsResponse> {
  const res = await fetch(apiUrl("signals/stats/landing"), { next: { revalidate: 60 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export interface ServerTimeResponse {
  iso: string;
  timezone: string;
}

export async function fetchServerTime(): Promise<ServerTimeResponse> {
  const res = await fetch(apiUrl("time"), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export interface AccessItem {
  has: boolean;
  valid_until: string | null;
  scope: string | null;
  sport_key: string | null;
  connected_at: string | null;
}

export interface AccessSummaryResponse {
  tg_analytics: AccessItem;
  signals: AccessItem;
}

export interface MyProfile {
  id: string;
  email: string;
  email_verified?: boolean;
  telegram_linked?: boolean;
  telegram_username?: string | null;
  signal_via_telegram?: boolean;
  signal_via_email?: boolean;
  is_admin?: boolean;
  trial_until?: string | null;
}

export async function fetchMyProfile(): Promise<MyProfile> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/profile")
      : new URL(apiUrl("me/profile"), "http://localhost:12000").toString();
  return fetchJson<MyProfile>(url, {
    headers: { ...authHeaders() },
    dedupeKey: `GET:${url}:auth:${getAuthToken() ?? "none"}`,
  });
}

export interface PatchProfileBody {
  signal_via_telegram?: boolean;
  signal_via_email?: boolean;
}

export async function patchMyProfile(body: PatchProfileBody): Promise<MyProfile> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/profile")
      : new URL(apiUrl("me/profile"), "http://localhost:12000").toString();
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface LinkTelegramRequestResponse {
  link: string;
  code: string;
  expires_in_seconds: number;
}

export async function fetchLinkTelegramRequest(): Promise<LinkTelegramRequestResponse> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/link-telegram-request")
      : new URL(apiUrl("me/link-telegram-request"), "http://localhost:12000").toString();
  const res = await fetch(url, {
    method: "POST",
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function unlinkTelegramRequest(): Promise<MyProfile> {
  const res = await fetch(apiUrl("me/unlink-telegram"), {
    method: "POST",
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function requestVerifyEmail(email: string): Promise<{ message: string; detail: string }> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/request-verify-email")
      : new URL(apiUrl("me/request-verify-email"), "http://localhost:12000").toString();
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email }),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface SubscriptionOut {
  id: string;
  access_type: string;
  scope: string;
  sport_key: string | null;
  valid_until: string;
  connected_at: string;
  created_at: string;
}

export interface GrantSubscriptionBody {
  access_type: "tg_analytics" | "signals";
  scope: "one_sport" | "all";
  sport_key?: string | null;
  valid_until: string;
  user_id?: string | null;
  comment?: string | null;
}

export interface SportOption {
  id: string;
  name: string;
}

export async function fetchMeAccess(): Promise<AccessSummaryResponse> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/access")
      : new URL(apiUrl("me/access"), "http://localhost:12000").toString();
  try {
    return await fetchJson<AccessSummaryResponse>(url, {
      headers: { ...authHeaders() },
      dedupeKey: `GET:${url}:auth:${getAuthToken() ?? "none"}`,
    });
  } catch (e) {
    throw e;
  }
}

export async function fetchMySubscriptions(): Promise<SubscriptionOut[]> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/subscriptions")
      : new URL(apiUrl("me/subscriptions"), "http://localhost:12000").toString();
  const res = await fetch(url, { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface MySignalItem {
  match_id: string;
  league_name: string;
  start_time: string;
  home_name: string;
  away_name: string;
  recommendation_text: string;
  outcome: "won" | "lost" | "pending";
  sent_at: string;
  sent_via: string;
  odds_at_recommendation: number | null;
}

export interface MySignalsResponse {
  total: number;
  won: number;
  lost: number;
  pending: number;
  items: MySignalItem[];
  bank_profit_rub?: number;
  avg_odds?: number | null;
}

export interface MySignalsParams {
  days?: number;
  date_from?: string;
  date_to?: string;
}

export async function fetchMySignals(params?: number | MySignalsParams): Promise<MySignalsResponse> {
  const base =
    typeof window !== "undefined"
      ? apiUrl("me/signals")
      : new URL(apiUrl("me/signals"), "http://localhost:12000").toString();
  const url = new URL(base, typeof window !== "undefined" ? window.location.origin : "http://localhost:12000");
  if (typeof params === "number") {
    url.searchParams.set("days", String(params));
  } else if (params) {
    if (params.days != null) url.searchParams.set("days", String(params.days));
    if (params.date_from) url.searchParams.set("date_from", params.date_from);
    if (params.date_to) url.searchParams.set("date_to", params.date_to);
  }
  const res = await fetch(url.toString(), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch my signals");
  return res.json();
}

export interface VipChannelStatsResponse {
  total: number;
  won: number;
  lost: number;
  pending: number;
  missed: number;
   bank_profit_rub?: number;
   avg_odds?: number | null;
}

export async function fetchVipChannelStats(days = 7): Promise<VipChannelStatsResponse> {
  const url =
    typeof window !== "undefined"
      ? `${apiUrl("statistics/vip-channel")}?days=${days}`
      : new URL(apiUrl("statistics/vip-channel"), "http://localhost:12000").toString() + `?days=${days}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch VIP channel stats");
  return res.json();
}

export interface FreeChannelStatsResponse {
  total: number;
  won: number;
  lost: number;
  pending: number;
  missed: number;
  bank_profit_rub?: number;
  avg_odds?: number | null;
}

export async function fetchFreeChannelStats(days = 7): Promise<FreeChannelStatsResponse> {
  const url =
    typeof window !== "undefined"
      ? `${apiUrl("statistics/free-channel")}?days=${days}`
      : new URL(apiUrl("statistics/free-channel"), "http://localhost:12000").toString() + `?days=${days}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch free channel stats");
  return res.json();
}

export interface CheckoutItem {
  access_type: "tg_analytics" | "signals";
  scope: "one_sport" | "all";
  sport_key?: string | null;
  days: number;
}

export interface CheckoutResponse {
  invoice_id: string;
  payment_id: string | null;
  confirmation_url: string | null;
  error: string | null;
}

export async function createCheckout(items: CheckoutItem[]): Promise<CheckoutResponse> {
  const res = await fetch(apiUrl("billing/checkout"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function grantSubscription(body: GrantSubscriptionBody): Promise<SubscriptionOut> {
  const res = await fetch(apiUrl("me/subscriptions"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface TopupHistoryResponse {
  invoices: { id: string; amount: number; currency: string; status: string; created_at: string | null; paid_at: string | null }[];
  subscription_grants: { id: string; access_type: string; scope: string; sport_key: string | null; valid_until: string; comment: string | null; created_at: string | null }[];
}

export async function fetchMyTopupHistory(): Promise<TopupHistoryResponse> {
  const res = await fetch(apiUrl("me/topup-history"), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

// ——— Admin API ———
export interface AdminUserListItem {
  id: string;
  email: string;
  telegram_id: string | null;
  telegram_username: string | null;
  is_admin: boolean;
  is_blocked?: boolean;
  trial_until: string | null;
  last_login_at?: string | null;
  created_at: string | null;
}

export interface AdminUsersResponse {
  total: number;
  items: AdminUserListItem[];
}

export interface AdminUserSubscription {
  id: string;
  access_type: string;
  scope: string;
  sport_key: string | null;
  valid_until: string;
}

export interface AdminUserInvoice {
  id: string;
  amount: number;
  currency: string;
  status: string;
  created_at: string | null;
  paid_at: string | null;
}

export interface AdminUserSubscriptionGrantLog {
  id: string;
  access_type: string;
  scope: string;
  sport_key: string | null;
  valid_until: string;
  comment: string | null;
  created_at: string | null;
}

export interface AdminUserDetail extends AdminUserListItem {
  email_verified?: boolean;
  subscriptions: AdminUserSubscription[];
  invoices: AdminUserInvoice[];
  subscription_grant_logs?: AdminUserSubscriptionGrantLog[];
}

export async function fetchAdminUsers(params: { offset?: number; limit?: number; q?: string }): Promise<AdminUsersResponse> {
  const sp = new URLSearchParams();
  if (params.offset != null) sp.set("offset", String(params.offset));
  if (params.limit != null) sp.set("limit", String(params.limit));
  if (params.q != null && params.q.trim()) sp.set("q", params.q.trim());
  const res = await fetch(apiUrl(`admin/users?${sp}`), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function fetchAdminUser(userId: string): Promise<AdminUserDetail> {
  const res = await fetch(apiUrl(`admin/users/${userId}`), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface AdminUserPatchBody {
  trial_until?: string | null;
  trial_add_days?: number | null;
  trial_clear?: boolean;
  grant_subscriptions_until_trial?: boolean;
  is_admin?: boolean;
  is_blocked?: boolean;
}

export async function patchAdminUser(userId: string, body: AdminUserPatchBody): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/users/${userId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function grantSubscriptionAdmin(body: GrantSubscriptionBody & { user_id: string }): Promise<SubscriptionOut> {
  const res = await fetch(apiUrl("admin/subscriptions"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

// ——— Способы оплаты (публичный список для страницы тарифов) ———
export interface PaymentMethodPublic {
  id: string;
  name: string;
  type: string;
  custom_message: string | null;
}

export async function fetchPaymentMethods(): Promise<PaymentMethodPublic[]> {
  const res = await fetch(apiUrl("billing/payment-methods"), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

// ——— Админ: способы оплаты ———
export interface AdminPaymentMethod {
  id: string;
  name: string;
  type: string;
  enabled: boolean;
  sort_order: number;
  custom_message: string | null;
  created_at: string | null;
}

export async function fetchAdminPaymentMethods(): Promise<AdminPaymentMethod[]> {
  const res = await fetch(apiUrl("admin/payment-methods"), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface AdminPaymentMethodCreate {
  name: string;
  type: string;
  enabled?: boolean;
  sort_order?: number;
  custom_message?: string | null;
}

export async function createAdminPaymentMethod(body: AdminPaymentMethodCreate): Promise<AdminPaymentMethod> {
  const res = await fetch(apiUrl("admin/payment-methods"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      name: body.name,
      type: body.type,
      enabled: body.enabled ?? true,
      sort_order: body.sort_order ?? 0,
      custom_message: body.custom_message ?? null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface AdminPaymentMethodUpdate {
  name?: string;
  type?: string;
  enabled?: boolean;
  sort_order?: number;
  custom_message?: string | null;
}

export async function updateAdminPaymentMethod(id: string, body: AdminPaymentMethodUpdate): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/payment-methods/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function deleteAdminPaymentMethod(id: string): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/payment-methods/${id}`), {
    method: "DELETE",
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

// ——— Услуги (продукты): публичный список для страницы тарифов ———
export interface ProductPublic {
  id: string;
  key: string;
  name: string;
}

export async function fetchProducts(): Promise<ProductPublic[]> {
  const res = await fetch(apiUrl("billing/products"), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

// ——— Админ: услуги ———
export interface AdminProduct {
  id: string;
  key: string;
  name: string;
  enabled: boolean;
  sort_order: number;
  created_at: string | null;
}

export async function fetchAdminProducts(): Promise<AdminProduct[]> {
  const res = await fetch(apiUrl("admin/products"), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface AdminProductUpdate {
  name?: string;
  enabled?: boolean;
  sort_order?: number;
}

export async function updateAdminProduct(id: string, body: AdminProductUpdate): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/products/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

// ——— Отложенные посты (админ) ———

export interface ScheduledPost {
  id: string;
  name: string;
  target: "free_channel" | "paid_channel" | "bot_dm";
  template_type: string | null;
  body: string | null;
  send_at_time_msk: string;
  is_active: boolean;
  last_sent_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScheduledPostsResponse {
  items: ScheduledPost[];
}

export interface ScheduledPostCreate {
  name: string;
  target: string;
  template_type?: string | null;
  body?: string | null;
  send_at_time_msk: string;
  is_active?: boolean;
}

export interface ScheduledPostUpdate {
  name?: string;
  target?: string;
  template_type?: string | null;
  body?: string | null;
  send_at_time_msk?: string;
  is_active?: boolean;
}

export async function fetchAdminScheduledPosts(): Promise<ScheduledPostsResponse> {
  const res = await fetch(apiUrl("admin/scheduled-posts"), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function createAdminScheduledPost(body: ScheduledPostCreate): Promise<ScheduledPost> {
  const res = await fetch(apiUrl("admin/scheduled-posts"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function fetchAdminScheduledPost(id: string): Promise<ScheduledPost> {
  const res = await fetch(apiUrl(`admin/scheduled-posts/${id}`), { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function updateAdminScheduledPost(id: string, body: ScheduledPostUpdate): Promise<ScheduledPost> {
  const res = await fetch(apiUrl(`admin/scheduled-posts/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function deleteAdminScheduledPost(id: string): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/scheduled-posts/${id}`), {
    method: "DELETE",
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function fetchSports(): Promise<SportOption[]> {
  const res = await fetch(
    typeof window !== "undefined" ? apiUrl("sports") : new URL(apiUrl("sports"), "http://localhost:12000").toString(),
    { next: { revalidate: 60 } }
  );
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}
