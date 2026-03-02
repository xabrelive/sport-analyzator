// В браузере — относительный путь (Next.js rewrites проксирует на backend). На сервере — BACKEND_URL или localhost.
function getApiBase(): string {
  if (typeof window !== "undefined") return "";
  return process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}
const API_BASE = getApiBase();

/** URL для запроса к API (в браузере — относительный /api/v1/..., без хоста). */
function apiUrl(path: string): string {
  const base = getApiBase();
  return base ? `${base.replace(/\/$/, "")}/api/v1/${path}` : `/api/v1/${path}`;
}
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

const AUTH_TOKEN_KEY = "sport_analyzator_token";

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const t = getAuthToken();
  if (!t) return {};
  return { Authorization: `Bearer ${t}` };
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

export async function fetchMatches(
  path: "matches" | "matches/live" | "matches/upcoming" | "matches/finished",
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
      : new URL(pathWithQuery, "http://localhost:3000").toString();
  const res = await fetch(url, { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
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
    typeof window !== "undefined" ? window.location.origin : "http://localhost:3000"
  );
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchMatchesByLeague(leagueId: string, status?: string): Promise<Match[]> {
  const url = new URL(apiUrl("matches"), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  url.searchParams.set("league_id", leagueId);
  if (status) url.searchParams.set("status", status);
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchMatch(id: string): Promise<Match> {
  const res = await fetch(apiUrl(`matches/${id}`), { next: { revalidate: 0 } });
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
  const res = await fetch(apiUrl(`matches/${matchId}/analytics`), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

/** Рекомендации по матчам (на основе истории и статистики). Только если у обоих игроков ≥2 матчей. */
export async function fetchMatchRecommendations(matchIds: string[]): Promise<Record<string, string | null>> {
  if (matchIds.length === 0) return {};
  const params = new URLSearchParams({ match_ids: matchIds.join(",") });
  const res = await fetch(apiUrl("matches/recommendations") + "?" + params.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

/** Сохранённая рекомендация из таблицы линии/лайва (та же, что в колонке «Рекомендация»). */
export async function fetchStoredRecommendation(matchId: string): Promise<string | null> {
  const res = await fetch(apiUrl(`matches/${matchId}/stored-recommendation`), { next: { revalidate: 0 } });
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

/** Рекомендации в моменте (только лайв): на будущие сеты, кф ≥ 1.3. */
export async function fetchLiveRecommendations(matchId: string): Promise<LiveRecommendationsResponse> {
  const res = await fetch(apiUrl(`matches/${matchId}/live-recommendations`), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchLeagues(params?: Record<string, string | number>): Promise<League[]> {
  const url = new URL(apiUrl("leagues"), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
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
  const res = await fetch(apiUrl(`players/${id}`), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchPlayers(params?: { search?: string; limit?: number; offset?: number }): Promise<Player[]> {
  const url = new URL(apiUrl("players"), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchPlayerStats(id: string): Promise<PlayerStats> {
  const res = await fetch(apiUrl(`players/${id}/stats`), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchPlayerMatches(
  id: string,
  params?: { status?: string; limit?: number; offset?: number }
): Promise<Match[]> {
  const url = new URL(apiUrl(`players/${id}/matches`), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export function getWsUrl(): string {
  const envWs = process.env.NEXT_PUBLIC_WS_URL || "";
  const base =
    typeof window !== "undefined"
      ? (envWs ? envWs.replace(/^http/, "ws") : "")
      : (envWs ? envWs.replace(/^http/, "ws") : "ws://localhost:8000");
  if (base) {
    return base.endsWith("/ws") ? base : `${base.replace(/\/$/, "")}/ws`;
  }
  return typeof window !== "undefined"
    ? `${(window as unknown as { location: { origin: string } }).location.origin.replace(/^http/, "ws")}/ws`
    : "ws://localhost:8000/ws";
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
  const url = new URL(apiUrl("signals"), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export async function fetchSignalsStats(days?: number): Promise<SignalStatsResponse> {
  const url = new URL(apiUrl("signals/stats"), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  if (days != null) url.searchParams.set("days", String(days));
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export interface RecommendationStatsItem {
  match_id: string;
  league_name: string;
  start_time: string;
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
  cancelled_or_no_data_count?: number;
  cancelled_or_no_data_pct?: number;
  items: RecommendationStatsItem[];
  page: number;
  per_page: number;
  total_filtered: number;
  total_pages: number;
}

export type RecommendationResultFilter = "all" | "correct" | "wrong" | "pending";

export interface FetchRecommendationsStatsParams {
  page?: number;
  per_page?: number;
  result_filter?: RecommendationResultFilter;
  odds_min?: number;
  odds_max?: number;
}

export async function fetchRecommendationsStats(params?: FetchRecommendationsStatsParams): Promise<RecommendationStatsResponse> {
  const url = new URL(apiUrl("statistics/recommendations"), typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  if (params?.page != null) url.searchParams.set("page", String(params.page));
  if (params?.per_page != null) url.searchParams.set("per_page", String(params.per_page));
  if (params?.result_filter != null && params.result_filter !== "all") url.searchParams.set("result_filter", params.result_filter);
  if (params?.odds_min != null) url.searchParams.set("odds_min", String(params.odds_min));
  if (params?.odds_max != null) url.searchParams.set("odds_max", String(params.odds_max));
  const res = await fetch(url.toString(), { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
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
}

export interface SportOption {
  id: string;
  name: string;
}

export async function fetchMeAccess(): Promise<AccessSummaryResponse> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/access")
      : new URL(apiUrl("me/access"), "http://localhost:3000").toString();
  const res = await fetch(url, { headers: { ...authHeaders() }, cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function fetchMySubscriptions(): Promise<SubscriptionOut[]> {
  const url =
    typeof window !== "undefined"
      ? apiUrl("me/subscriptions")
      : new URL(apiUrl("me/subscriptions"), "http://localhost:3000").toString();
  const res = await fetch(url, { headers: { ...authHeaders() }, cache: "no-store" });
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

export async function fetchSports(): Promise<SportOption[]> {
  const res = await fetch(
    typeof window !== "undefined" ? apiUrl("sports") : new URL(apiUrl("sports"), "http://localhost:3000").toString(),
    { next: { revalidate: 60 } }
  );
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}
