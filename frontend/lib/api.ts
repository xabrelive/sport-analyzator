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
  const data = (await res.json().catch(() => ({}))) as {
    detail?: string;
    code?: string;
    email?: string;
    access_token?: string;
  };
  if (res.status === 403 && data.code === "email_not_verified" && data.email) {
    const e = new Error(data.detail || "Подтвердите почту") as Error & { code?: string; email?: string };
    e.code = "email_not_verified";
    e.email = data.email;
    throw e;
  }
  if (!res.ok) {
    throw new Error(data.detail || res.statusText);
  }
  return { access_token: data.access_token! };
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
  notify_telegram: boolean;
  notify_email: boolean;
  notification_tz_offset_minutes: number;
  is_telegram_only: boolean;
  is_superadmin: boolean;
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
  notify_telegram?: boolean | null;
  notify_email?: boolean | null;
  notification_tz_offset_minutes?: number | null;
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
  forecast_ml?: string | null;
  forecast_no_ml?: string | null;
  forecast_nn?: string | null;
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
  forecast_locked?: boolean;
  forecast_locked_message?: string;
  forecast_purchase_url?: string;
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
  forecast_ml?: string | null;
  forecast_no_ml?: string | null;
  forecast_nn?: string | null;
  sets_score?: string | null; // общий счёт по сетам, например "2-1"
  sets?: Record<string, { home: string; away: string }>; // счёт по каждому сету
  last_score_changed_at?: number | null;
  is_stale?: boolean;
  forecast_confidence?: number | null;
}

export interface TableTennisLiveResponse {
  events: TableTennisLiveEvent[];
  updated_at: number | null;
  forecast_locked?: boolean;
  forecast_locked_message?: string;
  forecast_purchase_url?: string;
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
  id?: number;
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
  market?: string | null;
  pick_side?: string | null;
  probability_pct?: number | null;
  confidence_score?: number | null;
  edge_pct?: number | null;
  odds_used?: number | null;
  starts_at: number | null;
  odds_1: number | null;
  odds_2: number | null;
  channel?: string | null;
  event_status?: string | null;
  sets_score?: string | null;
  live_score?: Record<string, { home: string | number | null; away: string | number | null }> | null;
  forecast_odds?: number | null;
  forecast_lead_seconds?: number | null;
  explanation_summary?: string | null;
  factors?: Array<{
    factor_key: string;
    factor_label: string;
    factor_value?: string | null;
    contribution?: number | null;
    direction?: string | null;
    rank?: number | null;
  }>;
}

export interface TableTennisForecastsResponse {
  items: TableTennisForecastItem[];
  page: number;
  page_size: number;
  total: number;
  forecast_locked?: boolean;
  forecast_locked_message?: string;
  forecast_purchase_url?: string;
  allowed_channels?: string[];
  only_resolved?: boolean;
}

export interface TableTennisForecastStats {
  total: number;
  by_status: Record<string, number>;
  hit_rate: number | null;
  avg_odds?: number | null;
  forecast_locked?: boolean;
  forecast_locked_message?: string;
  forecast_purchase_url?: string;
  allowed_channels?: string[];
  only_resolved?: boolean;
  kpi_runtime?: {
    dynamic_min_confidence_pct: number;
    dynamic_min_edge_pct: number;
    dynamic_min_odds: number;
    last_hit_rate: number;
    last_picks_per_day: number;
    last_updated_at: number;
  };
}

export interface TableTennisForecastsStreamPayload {
  stats: TableTennisForecastStats;
  forecasts: TableTennisForecastsResponse;
  updated_at?: number;
}

function normalizeForecastItem(it: TableTennisForecastItem): TableTennisForecastItem {
  return {
    ...it,
    confidence_pct: it.confidence_pct ?? it.probability_pct ?? it.confidence_score ?? null,
    forecast_odds: it.forecast_odds ?? it.odds_used ?? null,
  };
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
  forecast_locked?: boolean;
  forecast_locked_message?: string;
  forecast_purchase_url?: string;
}

export async function getTableTennisLine(): Promise<TableTennisLineResponse> {
  const res = await fetch(apiUrl("table-tennis/line"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getTableTennisLive(): Promise<TableTennisLiveResponse> {
  const res = await fetch(apiUrl("table-tennis/live"), { headers: authHeaders(), cache: "no-store" });
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

export interface MlAnalyticsFeatures {
  elo_diff: number;
  form_diff: number;
  fatigue_diff: number;
  h2h_count: number;
  h2h_p1_wr: number | null;
  sample_size: number;
  elo_p1: number;
  elo_p2: number;
}

export interface MlAnalyticsValueSignal {
  market: string;
  side: string;
  odds: number;
  probability: number;
  ev: number;
  confidence: number;
}

export interface MlAnalytics {
  p_match: number;
  p_set1: number;
  p_set2: number;
  model_used: boolean;
  value_signals: MlAnalyticsValueSignal[];
  features?: MlAnalyticsFeatures;
}

export interface TableTennisMatchCardV2 {
  match: TableTennisLiveEvent | null;
  forecast_v2: TableTennisForecastItem | null;
  forecast_locked?: boolean;
  forecast_locked_message?: string;
  forecast_purchase_url?: string;
  ml_analytics?: MlAnalytics | null;
  player_context?: {
    home?: {
      played?: number;
      wins?: number;
      losses?: number;
      win_rate?: number | null;
      last5_form?: Array<{
        event_id: string;
        result: "W" | "L";
        opponent_name?: string | null;
        starts_at?: number | null;
        sets_score?: string | null;
      }>;
      h2h_wins?: number;
    };
    away?: {
      played?: number;
      wins?: number;
      losses?: number;
      win_rate?: number | null;
      last5_form?: Array<{
        event_id: string;
        result: "W" | "L";
        opponent_name?: string | null;
        starts_at?: number | null;
        sets_score?: string | null;
      }>;
      h2h_wins?: number;
    };
    h2h?: {
      total?: number;
      home_wins?: number;
      away_wins?: number;
    };
  };
}

export async function getTableTennisMatchCardV2(
  matchId: string,
  channel = "paid"
): Promise<TableTennisMatchCardV2> {
  const qs = new URLSearchParams({ channel }).toString();
  const res = await fetch(apiUrl(`table-tennis/v2/matches/${encodeURIComponent(matchId)}?${qs}`), {
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

export async function getTableTennisPlayerCardV2(
  playerId: string,
  channel = "paid",
  pageUpcoming = 1,
  pageFinished = 1,
  pageSize = 20
): Promise<TableTennisPlayerCard & { v2_channel?: string }> {
  const params = new URLSearchParams({
    channel,
    page_upcoming: String(pageUpcoming),
    page_finished: String(pageFinished),
    page_size: String(pageSize),
  });
  const res = await fetch(
    apiUrl(`table-tennis/v2/players/${encodeURIComponent(playerId)}?${params.toString()}`),
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
  quality_tier?: string;
}): Promise<TableTennisForecastStats> {
  const search = new URLSearchParams();
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.league_id) search.set("league_id", params.league_id);
  if (params?.channel) search.set("channel", params.channel);
  if (params?.quality_tier) search.set("quality_tier", params.quality_tier);
  const qs = search.toString();
  const res = await fetch(apiUrl(`table-tennis/v2/forecasts/stats${qs ? `?${qs}` : ""}`), {
    headers: authHeaders(),
    cache: "no-store",
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
  quality_tier?: string;
}): Promise<TableTennisForecastsResponse> {
  const search = new URLSearchParams();
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  if (params?.status) search.set("status", params.status);
  if (params?.league_id) search.set("league_id", params.league_id);
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.channel) search.set("channel", params.channel);
  if (params?.quality_tier) search.set("quality_tier", params.quality_tier);
  const qs = search.toString();
  const res = await fetch(apiUrl(`table-tennis/v2/forecasts${qs ? `?${qs}` : ""}`), {
    headers: authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  const payload = (await res.json()) as TableTennisForecastsResponse;
  payload.items = payload.items.map(normalizeForecastItem);
  return payload;
}

export function subscribeTableTennisForecastsStream(
  channel: string,
  onData: (data: TableTennisForecastsStreamPayload) => void,
  onError?: (err: Error) => void,
  qualityTier = ""
): () => void {
  const ac = new AbortController();
  (async () => {
    let reconnectDelayMs = 1000;
    while (!ac.signal.aborted) {
      try {
        const qs = new URLSearchParams({ channel, quality_tier: qualityTier }).toString();
        const res = await fetch(apiUrl(`table-tennis/v2/forecasts/stream?${qs}`), {
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
              if (data?.forecasts?.items) {
                data.forecasts.items = data.forecasts.items.map(normalizeForecastItem);
              }
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

// --- Admin & billing ---

export interface AdminUserListItem {
  id: string;
  email: string;
  telegram_id: number | null;
  telegram_username: string | null;
  notification_email: string | null;
  is_active: boolean;
  is_blocked: boolean;
  is_superadmin: boolean;
  last_login_at: string | null;
  created_at: string | null;
}

export interface AdminUsersResponse {
  total: number;
  items: AdminUserListItem[];
}

export async function getAdminTelegramBotInfo(): Promise<{ message: string }> {
  const res = await fetch(apiUrl("admin/telegram-bot-info"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function putAdminTelegramBotInfo(message: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(apiUrl("admin/telegram-bot-info"), {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getAdminMe(): Promise<{ id: string; email: string; is_superadmin: boolean }> {
  const res = await fetch(apiUrl("admin/me"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getAdminUsers(params?: {
  q?: string;
  offset?: number;
  limit?: number;
}): Promise<AdminUsersResponse> {
  const sp = new URLSearchParams();
  if (params?.q) sp.set("q", params.q);
  if (params?.offset != null) sp.set("offset", String(params.offset));
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const res = await fetch(apiUrl(`admin/users?${sp.toString()}`), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function patchAdminUser(
  userId: string,
  body: {
    is_active?: boolean;
    is_blocked?: boolean;
    is_superadmin?: boolean;
    notify_telegram?: boolean;
    notify_email?: boolean;
  }
): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/users/${encodeURIComponent(userId)}`), {
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

export interface AdminSubscription {
  id: string;
  service_key: "analytics" | "analytics_no_ml" | "vip_channel";
  duration_days: number;
  valid_until: string;
  source: string;
  comment: string | null;
  created_at: string | null;
}

export async function getAdminUserSubscriptions(userId: string): Promise<{ items: AdminSubscription[] }> {
  const res = await fetch(apiUrl(`admin/users/${encodeURIComponent(userId)}/subscriptions`), {
    headers: authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function upsertAdminSubscription(
  userId: string,
  body: { service_key: "analytics" | "analytics_no_ml" | "vip_channel"; days: number; comment?: string | null }
): Promise<AdminSubscription> {
  const res = await fetch(apiUrl(`admin/users/${encodeURIComponent(userId)}/subscriptions`), {
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

export async function deleteAdminSubscription(userId: string, subscriptionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(
    apiUrl(`admin/users/${encodeURIComponent(userId)}/subscriptions/${encodeURIComponent(subscriptionId)}`),
    { method: "DELETE", headers: authHeaders() }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface AdminProduct {
  id: string;
  code: string;
  name: string;
  service_key: string;
  duration_days: number;
  price_rub: number;
  price_usd: number;
  enabled: boolean;
  sort_order: number;
}

export async function getAdminProducts(): Promise<AdminProduct[]> {
  const res = await fetch(apiUrl("admin/products"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function patchAdminProduct(
  productId: string,
  body: { name?: string; price_rub?: number; price_usd?: number; enabled?: boolean; sort_order?: number }
): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/products/${encodeURIComponent(productId)}`), {
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

export interface AdminPaymentMethod {
  id: string;
  name: string;
  method_type: string;
  enabled: boolean;
  sort_order: number;
  instructions: string | null;
}

export async function getAdminPaymentMethods(): Promise<AdminPaymentMethod[]> {
  const res = await fetch(apiUrl("admin/payment-methods"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function createAdminPaymentMethod(body: {
  name: string;
  method_type: "custom" | "card" | "crypto";
  enabled?: boolean;
  sort_order?: number;
  instructions?: string | null;
}): Promise<{ id: string }> {
  const res = await fetch(apiUrl("admin/payment-methods"), {
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

export async function patchAdminPaymentMethod(
  methodId: string,
  body: { name?: string; method_type?: "custom" | "card" | "crypto"; enabled?: boolean; sort_order?: number; instructions?: string | null }
): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/payment-methods/${encodeURIComponent(methodId)}`), {
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

export async function deleteAdminPaymentMethod(methodId: string): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl(`admin/payment-methods/${encodeURIComponent(methodId)}`), {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function sendAdminMessage(body: {
  target: "free_channel" | "vip_channel" | "no_ml_channel" | "telegram_user" | "telegram_all_users" | "email";
  text: string;
  user_id?: string;
  email?: string;
  subject?: string;
  image_url?: string;
  image_urls?: string[];
}): Promise<{ ok: boolean; total?: number; sent?: number }> {
  const res = await fetch(apiUrl("admin/messages/send"), {
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

export async function getAdminTelegramDispatchConfig(): Promise<{ config: Record<string, unknown> | null }> {
  const res = await fetch(apiUrl("admin/telegram-dispatch-config"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function putAdminTelegramDispatchConfig(config: Record<string, unknown>): Promise<{ ok: boolean }> {
  const res = await fetch(apiUrl("admin/telegram-dispatch-config"), {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ config }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface AdminInvoiceItem {
  id: string;
  user_id: string;
  user_email: string;
  status: "pending" | "paid" | "cancelled" | string;
  amount_rub: number;
  payment_method_id: string | null;
  comment: string | null;
  created_at: string | null;
  paid_at: string | null;
}

export interface AdminInvoicesResponse {
  total: number;
  items: AdminInvoiceItem[];
}

export async function getAdminInvoices(params?: {
  status?: "pending" | "paid" | "cancelled" | "";
  offset?: number;
  limit?: number;
}): Promise<AdminInvoicesResponse> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set("status", params.status);
  if (params?.offset != null) sp.set("offset", String(params.offset));
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString();
  const res = await fetch(apiUrl(`admin/invoices${qs ? `?${qs}` : ""}`), {
    headers: authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

// --- Admin ML (sync, backfill, retrain) ---
export interface AdminMlProgressItem {
  status: "idle" | "running" | "done";
  message: string;
  current: number;
  total: number;
  result?: Record<string, unknown>;
  error?: string;
  updated_at_ts?: number;
  completed_at_ts?: number;
}

export interface AdminMlProgress {
  sync: AdminMlProgressItem;
  backfill: AdminMlProgressItem;
  odds_backfill?: AdminMlProgressItem;
  retrain: AdminMlProgressItem;
  league_performance?: AdminMlProgressItem;
  player_stats?: AdminMlProgressItem;
  full_rebuild?: AdminMlProgressItem;
}

export interface AdminMlDashboard {
  tables: Record<string, number>;
  fill_pct: Record<string, number>;
  main: { matches: number; players: number; leagues: number };
  diff: { matches: number; players: number; leagues: number };
  sync_ok: boolean;
  progress: AdminMlProgress;
  queue_size: number;
  meta?: Record<string, string>;
}

export interface AdminMlV2Status {
  engine: string;
  queue_size: number;
  progress: AdminMlProgress;
  clickhouse_ok: boolean;
  clickhouse_error?: string;
  tables: Record<string, number>;
  main_finished: number;
  delta_main_minus_ch_matches: number;
  delta_ch_matches_minus_features: number;
  delta_ch_matches_minus_match_sets: number;
  match_sets_gap_pct: number;
  match_sets_gap_alert: boolean;
  delta_main_minus_ch_features: number;
  meta?: Record<string, string>;
  kpi?: {
    match_hit_rate?: number;
    set1_hit_rate?: number;
    sample_size?: number;
  };
  v2_config?: {
    ml_v2_use_experience_regimes: boolean;
    ml_v2_experience_regime_min_train: number;
    betsapi_table_tennis_v2_confidence_filter_min_pct: number;
    ml_v2_train_max_league_upset_rate: number;
    ml_v2_enable_nn?: boolean;
    betsapi_table_tennis_forecast_tolerance_minutes?: number;
    betsapi_table_tennis_forecast_window_min_minutes_before?: number;
    betsapi_table_tennis_forecast_ml_max_minutes_before?: number;
    betsapi_table_tennis_nn_forecast_interval_sec?: number;
    betsapi_table_tennis_nn_min_confidence_to_publish?: number;
    betsapi_table_tennis_nn_min_match_confidence_pct?: number;
    betsapi_table_tennis_nn_min_set1_confidence_pct?: number;
    betsapi_table_tennis_nn_allow_hard_confidence_fallback?: boolean;
    ml_v2_nn_hidden_layers?: string;
    ml_v2_nn_learning_rate?: number;
    ml_v2_nn_alpha?: number;
    ml_v2_nn_batch_size?: number;
    ml_v2_nn_max_iter?: number;
  };
  v2_meta?: Record<string, unknown>;
}

export async function getAdminMlDashboard(): Promise<AdminMlDashboard> {
  const res = await fetch(apiUrl("admin/ml/dashboard"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function getAdminMlV2Status(): Promise<AdminMlV2Status> {
  const res = await fetch(apiUrl("admin/ml/v2/status"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function getAdminMlProgress(): Promise<AdminMlProgress> {
  const res = await fetch(apiUrl("admin/ml/progress"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export interface AdminMlStats {
  matches: number;
  match_features: number;
  players?: number;
  leagues?: number;
}

export interface AdminMlVerify {
  main: { matches: number; players: number; leagues: number };
  ml: { matches: number; players: number; leagues: number };
  diff: { matches: number; players: number; leagues: number };
  ok: boolean;
  message: string;
}

export interface AdminMlSyncAudit {
  main_finished_events: number;
  ml_matches: number;
  delta_matches_main_minus_ml: number;
  main_players: number;
  ml_players: number;
  delta_players_main_minus_ml: number;
  main_leagues: number;
  ml_leagues: number;
  delta_leagues_main_minus_ml: number;
  recent_sample_checked: number;
  recent_missing_count: number;
  recent_missing_preview: string[];
}

export interface AdminMlNoMlStatsLeague {
  league_id: string;
  league_name: string;
  hit: number;
  miss: number;
  total?: number;
  hit_rate_pct?: number;
}

export interface AdminMlNoMlStatsStreaks {
  max_streak_miss: number;
  max_streak_hit: number;
  current_streak_miss: number;
  current_streak_hit: number;
}

export interface AdminMlNoMlStats {
  total_hit: number;
  total_miss: number;
  streaks?: AdminMlNoMlStatsStreaks;
  leagues_bad: AdminMlNoMlStatsLeague[];
  leagues_weak: AdminMlNoMlStatsLeague[];
  by_league: AdminMlNoMlStatsLeague[];
}

export async function getAdminMlNoMlStats(): Promise<AdminMlNoMlStats> {
  const res = await fetch(apiUrl("admin/ml/no-ml-stats"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function getAdminMlVerify(): Promise<AdminMlVerify> {
  const res = await fetch(apiUrl("admin/ml/verify"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function getAdminMlStats(): Promise<AdminMlStats> {
  const res = await fetch(apiUrl("admin/ml/stats"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function getAdminMlSyncAudit(params?: {
  sample_limit?: number;
  missing_preview?: number;
}): Promise<AdminMlSyncAudit> {
  const sp = new URLSearchParams();
  if (params?.sample_limit != null) sp.set("sample_limit", String(params.sample_limit));
  if (params?.missing_preview != null) sp.set("missing_preview", String(params.missing_preview));
  const res = await fetch(apiUrl(`admin/ml/sync-audit?${sp}`), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlRequestFullSync(): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(apiUrl("admin/ml/request-full-sync"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminForecastsClearAll(): Promise<{
  ok: boolean;
  message: string;
  deleted: Record<string, number>;
}> {
  const res = await fetch(apiUrl("admin/forecasts/clear-all"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminForecastsClearMl(): Promise<{
  ok: boolean;
  message: string;
  deleted: Record<string, number>;
}> {
  const res = await fetch(apiUrl("admin/forecasts/clear-ml"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminForecastsClearNoMl(): Promise<{
  ok: boolean;
  message: string;
  deleted: Record<string, number>;
}> {
  const res = await fetch(apiUrl("admin/forecasts/clear-no-ml"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminForecastsClearNn(): Promise<{
  ok: boolean;
  message: string;
  deleted: Record<string, number>;
}> {
  const res = await fetch(apiUrl("admin/forecasts/clear-nn"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function putAdminApplyNnEnv(values: Record<string, string>): Promise<{
  ok: boolean;
  message: string;
  path: string;
  updated: number;
  appended: number;
}> {
  const res = await fetch(apiUrl("admin/nn-config/apply-env"), {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ values }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function putAdminApplyNnEnvAndRestart(values: Record<string, string>): Promise<{
  ok: boolean;
  message: string;
  path: string;
  updated: number;
  appended: number;
  restart_output: string;
}> {
  const res = await fetch(apiUrl("admin/nn-config/apply-env-and-restart"), {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ values }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlSyncLeagues(): Promise<{ ok: boolean; added: number; total: number }> {
  const res = await fetch(apiUrl("admin/ml/sync-leagues"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlSyncPlayers(): Promise<{ ok: boolean; added: number; total: number }> {
  const res = await fetch(apiUrl("admin/ml/sync-players"), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlLoadArchive(params?: {
  days?: number;
  date_from?: string;
  date_to?: string;
}): Promise<{ ok: boolean; inserted?: number; updated?: number; skipped?: number }> {
  const sp = new URLSearchParams();
  if (params?.days != null) sp.set("days", String(params.days));
  if (params?.date_from) sp.set("date_from", params.date_from);
  if (params?.date_to) sp.set("date_to", params.date_to);
  const res = await fetch(apiUrl(`admin/ml/load-archive?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlSync(params?: {
  limit?: number;
  days_back?: number;
  full?: boolean;
}): Promise<{ ok: boolean; message?: string; error?: string; synced?: number; skipped?: number }> {
  const sp = new URLSearchParams();
  if (params?.limit != null) sp.set("limit", String(params.limit));
  if (params?.days_back != null) sp.set("days_back", String(params.days_back));
  if (params?.full) sp.set("full", "true");
  const res = await fetch(apiUrl(`admin/ml/sync?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlBackfillFeatures(params?: {
  limit?: number;
}): Promise<{ ok: boolean; message?: string; error?: string; features_added?: number }> {
  const sp = new URLSearchParams();
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const res = await fetch(apiUrl(`admin/ml/backfill-features?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

/** Дозаполняет ml.match_sets из main DB (live_sets_score, live_score). limit 100–20000. */
export async function postAdminMlV2BackfillMatchSets(limit?: number): Promise<{
  ok: boolean;
  filled: number;
  sets_inserted: number;
  remaining: number;
}> {
  const sp = new URLSearchParams();
  if (limit != null) sp.set("limit", String(limit));
  const res = await fetch(apiUrl(`admin/ml/v2/backfill-match-sets?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlOddsBackfillBg(params?: {
  limit?: number;
  batches?: number;
  pause_ms?: number;
}): Promise<{ ok: boolean; message?: string; error?: string }> {
  const sp = new URLSearchParams();
  if (params?.limit != null) sp.set("limit", String(params.limit));
  if (params?.batches != null) sp.set("batches", String(params.batches));
  if (params?.pause_ms != null) sp.set("pause_ms", String(params.pause_ms));
  const res = await fetch(apiUrl(`admin/ml/odds-backfill-bg?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlRetrain(params?: {
  min_rows?: number;
}): Promise<{ ok: boolean; message?: string; error?: string; trained?: boolean; rows?: number; path?: string }> {
  const sp = new URLSearchParams();
  if (params?.min_rows != null) sp.set("min_rows", String(params.min_rows));
  const res = await fetch(apiUrl(`admin/ml/retrain?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlPlayerStats(params?: {
  limit?: number;
}): Promise<{ ok: boolean; message?: string; error?: string }> {
  const sp = new URLSearchParams();
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const res = await fetch(apiUrl(`admin/ml/player-stats?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlResetProgress(op?: string): Promise<{ ok: boolean; message?: string }> {
  const sp = new URLSearchParams();
  if (op) sp.set("op", op);
  const res = await fetch(apiUrl(`admin/ml/reset-progress?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function postAdminMlFullRebuild(params?: {
  sync_limit?: number;
  backfill_limit?: number;
  player_stats_limit?: number;
  league_limit?: number;
  min_rows?: number;
}): Promise<{ ok: boolean; message?: string; error?: string }> {
  const sp = new URLSearchParams();
  if (params?.sync_limit != null) sp.set("sync_limit", String(params.sync_limit));
  if (params?.backfill_limit != null) sp.set("backfill_limit", String(params.backfill_limit));
  if (params?.player_stats_limit != null) sp.set("player_stats_limit", String(params.player_stats_limit));
  if (params?.league_limit != null) sp.set("league_limit", String(params.league_limit));
  if (params?.min_rows != null) sp.set("min_rows", String(params.min_rows));
  const res = await fetch(apiUrl(`admin/ml/full-rebuild?${sp}`), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})) as { detail?: string }).detail || res.statusText);
  return res.json();
}

export async function patchAdminInvoiceStatus(
  invoiceId: string,
  paid: boolean
): Promise<{ ok: boolean; invite_sent?: boolean }> {
  const res = await fetch(apiUrl(`admin/invoices/${encodeURIComponent(invoiceId)}/status`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ paid }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getBillingProducts(): Promise<Array<{
  id: string;
  code: string;
  name: string;
  service_key: string;
  duration_days: number;
  price_rub: number;
  price_usd: number;
}>> {
  const res = await fetch(apiUrl("billing/products"), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export interface BillingCheckoutItem {
  product_code: string;
  quantity?: number;
}

export interface BillingCheckoutResponse {
  invoice_id: string;
  status: string;
  amount_rub: number;
  created_at: string | null;
  detail: string;
}

export async function createBillingCheckout(body: {
  items: BillingCheckoutItem[];
  payment_method_id?: string | null;
  comment?: string | null;
}): Promise<BillingCheckoutResponse> {
  const res = await fetch(apiUrl("billing/checkout"), {
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

export async function getBillingPaymentMethods(): Promise<Array<{
  id: string;
  name: string;
  method_type: string;
  instructions: string | null;
}>> {
  const res = await fetch(apiUrl("billing/payment-methods"), { cache: "no-store" });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export interface BillingVipAccessResponse {
  has_active_subscription: boolean;
  telegram_linked: boolean;
  is_member: boolean;
  can_create_invite: boolean;
  member_status?: string | null;
  valid_until?: string | null;
  channel_url?: string | null;
  message: string;
}

export async function getBillingVipAccess(): Promise<BillingVipAccessResponse> {
  const res = await fetch(apiUrl("billing/vip/access"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface BillingVipCreateInviteResponse {
  already_in_channel: boolean;
  invite_link?: string;
  channel_url?: string | null;
  warning?: string;
  valid_until?: string;
  message?: string;
}

export async function createBillingVipInvite(): Promise<BillingVipCreateInviteResponse> {
  const res = await fetch(apiUrl("billing/vip/create-invite"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface BillingMySubscriptionItem {
  id: string;
  service_key: "analytics" | "vip_channel" | string;
  duration_days: number;
  valid_until: string;
  source: string;
  comment: string | null;
  created_at: string | null;
}

export interface BillingMyServiceSummary {
  service_key: "analytics" | "vip_channel" | string;
  has_subscription: boolean;
  is_active: boolean;
  valid_until: string | null;
  days_left: number;
  source?: string;
}

export interface BillingMySubscriptionsResponse {
  items: BillingMySubscriptionItem[];
  analytics: BillingMyServiceSummary;
  analytics_no_ml: BillingMyServiceSummary;
  vip_channel: BillingMyServiceSummary;
}

export async function getBillingMySubscriptions(): Promise<BillingMySubscriptionsResponse> {
  const res = await fetch(apiUrl("billing/subscriptions/my"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export interface BillingMyInvoiceItem {
  id: string;
  status: "pending" | "paid" | "cancelled" | string;
  amount_rub: number;
  payment_method_id: string | null;
  comment: string | null;
  created_at: string | null;
  paid_at: string | null;
}

export interface BillingMyInvoicesResponse {
  items: BillingMyInvoiceItem[];
}

export async function getBillingMyInvoices(): Promise<BillingMyInvoicesResponse> {
  const res = await fetch(apiUrl("billing/invoices/my"), { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}
