"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchMatchesOverview, fetchSignals, fetchMatchRecommendations, type Match } from "@/lib/api";
import { setCachedMatches, invalidateMatchIds, isMatchNewerThan } from "@/lib/matchCache";
import { LineMatchRow, formatSignalRecommendation } from "@/components/LineMatchRow";
import { useSubscription } from "@/contexts/SubscriptionContext";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";

const UPCOMING_LIMIT = 200;
const SIGNALS_LIMIT = 200;
const LINE_CACHE_KEY = "view:line";
/** Показываем кэш при открытии только если он свежее 60 сек — иначе сразу грузим актуальные данные */
const LINE_CACHE_MAX_AGE_MS = 60_000;
const LINE_VIRTUALIZE_FROM = 120;
const LINE_ROW_HEIGHT = 54;
const LINE_VIEWPORT_HEIGHT = 560;
const LINE_OVERSCAN = 8;

type LineCachePayload = {
  matches: Match[];
  signals: Awaited<ReturnType<typeof fetchSignals>>;
  modelRecs: Record<string, string | null>;
};

function groupByLeague(matches: Match[]): Map<string | null, Match[]> {
  const map = new Map<string | null, Match[]>();
  for (const m of matches) {
    const key = m.league?.id ?? null;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(m);
  }
  return map;
}

/** Сортировка лиг по имени (без лиги — в конце). */
function sortLeagueEntries(entries: [string | null, Match[]][]): [string | null, Match[]][] {
  return [...entries].sort(([, matchesA], [, matchesB]) => {
    const nameA = matchesA[0]?.league?.name ?? "\uFFFF";
    const nameB = matchesB[0]?.league?.name ?? "\uFFFF";
    return nameA.localeCompare(nameB, "ru");
  });
}

/** Сортировка матчей по времени начала (сначала самые ранние). */
function sortMatchesByStart(matches: Match[]): Match[] {
  return [...matches].sort((a, b) => (a.start_time || "").localeCompare(b.start_time || ""));
}

function hasWinnerOdds(match: Match): boolean {
  const odds = match.odds_snapshots ?? [];
  let hasHome = false;
  let hasAway = false;
  for (const o of odds) {
    const market = (o.market || "").toLowerCase();
    if (market !== "winner" && market !== "win" && market !== "92_1") continue;
    const sel = (o.selection || "").toLowerCase();
    if (sel === "home" || sel === "1") hasHome = true;
    if (sel === "away" || sel === "2") hasAway = true;
  }
  return hasHome && hasAway;
}

/** По списку сигналов строит map: match_id -> один прогноз (первый сигнал по матчу). */
function buildRecommendationByMatch(signals: { match_id: string; market_type: string; selection: string }[]): Map<string, string> {
  const byMatch = new Map<string, string>();
  for (const s of signals) {
    if (!byMatch.has(s.match_id)) {
      byMatch.set(s.match_id, formatSignalRecommendation(s.market_type, s.selection));
    }
  }
  return byMatch;
}

export default function LinePage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [signals, setSignals] = useState<Awaited<ReturnType<typeof fetchSignals>>>([]);
  const [modelRecs, setModelRecs] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [leagueOpen, setLeagueOpen] = useState<Record<string, boolean>>({});
  const [leagueScrollTop, setLeagueScrollTop] = useState<Record<string, number>>({});
  const [leagueFilter, setLeagueFilter] = useState<string | null>(null);
  const [onlyWithRecommendations, setOnlyWithRecommendations] = useState(false);
  const knownRecIdsRef = useRef<Set<string>>(new Set());
  const lastWsRefreshAtRef = useRef<number>(0);
  const isFetchingMatchesRef = useRef(false);
  const fetchMatchesAgainRef = useRef(false);
  const matchesRef = useRef<Match[]>([]);
  const { hasFullAccess } = useSubscription();

  const recommendationByMatch = useMemo(() => buildRecommendationByMatch(signals), [signals]);
  matchesRef.current = matches;

  const loadRecommendationsFor = useCallback(async (items: Match[]) => {
    const missing = items
      .filter(hasWinnerOdds)
      .map((m) => m.id)
      .filter((id) => !knownRecIdsRef.current.has(id));
    if (missing.length === 0) return;
    const recs = await fetchMatchRecommendations(missing);
    const nonNullEntries = Object.entries(recs).filter(([, value]) => Boolean(value));
    if (nonNullEntries.length === 0) return;
    for (const [id] of nonNullEntries) knownRecIdsRef.current.add(id);
    setModelRecs((prev) => ({ ...prev, ...Object.fromEntries(nonNullEntries) }));
  }, []);

  const loadMatchesOnly = useCallback(async () => {
    if (isFetchingMatchesRef.current) {
      fetchMatchesAgainRef.current = true;
      return;
    }
    isFetchingMatchesRef.current = true;
    try {
      const { upcoming } = await fetchMatchesOverview({ limit_upcoming: UPCOMING_LIMIT, limit_live: 0 });
      const prev = matchesRef.current;
      const byId = new Map(prev.map((x) => [x.id, x]));
      const merged = upcoming.map((m) => {
        const p = byId.get(m.id);
        return p && isMatchNewerThan(p, m) ? p : m;
      });
      setMatches(merged);
      setCachedMatches(merged);
      // Рекомендации догружаем асинхронно, не блокируя отображение таблицы.
      void loadRecommendationsFor(upcoming);
    } finally {
      isFetchingMatchesRef.current = false;
      if (fetchMatchesAgainRef.current) {
        fetchMatchesAgainRef.current = false;
        void loadMatchesOnly();
      }
    }
  }, [loadRecommendationsFor]);

  const loadSignalsOnly = useCallback(async () => {
    const signalsRes = await fetchSignals({ limit: SIGNALS_LIMIT });
    setSignals(signalsRes);
  }, []);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      const ids = Array.isArray(message.match_ids) ? message.match_ids : [];
      if (ids.length) invalidateMatchIds(ids);
      const now = Date.now();
      if (now - lastWsRefreshAtRef.current < 800) return;
      lastWsRefreshAtRef.current = now;
      void loadMatchesOnly();
    }
  });

  const filteredMatches = useMemo(() => {
    let list = matches;
    if (leagueFilter !== null) list = list.filter((m) => (m.league?.id ?? null) === leagueFilter);
    if (onlyWithRecommendations) {
      list = list.filter((m) => hasWinnerOdds(m) && Boolean(modelRecs[m.id] ?? recommendationByMatch.get(m.id)));
    }
    return list;
  }, [matches, leagueFilter, onlyWithRecommendations, modelRecs, recommendationByMatch]);

  const byLeague = useMemo(() => groupByLeague(filteredMatches), [filteredMatches]);
  const leagueEntries = useMemo(
    () => sortLeagueEntries(Array.from(byLeague.entries())),
    [byLeague]
  );

  useEffect(() => {
    const cached = getCached<LineCachePayload>(LINE_CACHE_KEY, LINE_CACHE_MAX_AGE_MS);
    if (cached) {
      setMatches(cached.matches);
      setSignals(cached.signals);
      setModelRecs(cached.modelRecs);
      knownRecIdsRef.current = new Set(Object.keys(cached.modelRecs));
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        await loadMatchesOnly();
        if (!cancelled) setLoading(false);
        void loadSignalsOnly();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void boot();
    const matchesTimer = setInterval(() => void loadMatchesOnly(), 10_000);
    const signalsTimer = setInterval(() => void loadSignalsOnly(), 45000);
    return () => {
      cancelled = true;
      clearInterval(matchesTimer);
      clearInterval(signalsTimer);
    };
  }, [loadMatchesOnly, loadSignalsOnly]);

  useEffect(() => {
    if (loading) return;
    setCached<LineCachePayload>(LINE_CACHE_KEY, { matches, signals, modelRecs });
  }, [matches, signals, modelRecs, loading]);

  const toggleLeague = (key: string) => {
    setLeagueOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const isLeagueOpen = (key: string) => leagueOpen[key] !== false;

  const leagueOptions = useMemo(() => {
    const seen = new Map<string | null, string>();
    for (const m of matches) {
      const id = m.league?.id ?? null;
      if (!seen.has(id)) seen.set(id, m.league?.name ?? "Без лиги");
    }
    return Array.from(seen.entries()).sort((a, b) => a[1].localeCompare(b[1], "ru"));
  }, [matches]);

  return (
    <main className="max-w-5xl mx-auto px-4 py-5">
      <h1 className="text-xl font-bold text-white mb-1">Линия</h1>
      <p className="text-slate-500 text-sm mb-4">
        Предстоящие матчи. Коэффициенты и имплицитная вероятность по букмекеру. Сворачивайте лиги по клику на заголовок.
      </p>
      {error && <p className="text-rose-400 mb-4">{error}</p>}
      {loading ? (
        <p className="text-slate-500">Загрузка...</p>
      ) : matches.length === 0 ? (
        <p className="text-slate-500 py-8">Нет предстоящих матчей</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-4 mb-4">
            <label className="flex items-center gap-2 text-slate-300 text-sm">
              <span>Лига:</span>
              <select
                value={leagueFilter ?? ""}
                onChange={(e) => setLeagueFilter(e.target.value === "" ? null : e.target.value)}
                className="rounded-lg bg-slate-800 border border-slate-600 px-3 py-1.5 text-sm text-white"
              >
                <option value="">Все лиги</option>
                {leagueOptions.map(([id, name]) => (
                  <option key={id ?? "null"} value={id ?? ""}>{name}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-slate-300 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={onlyWithRecommendations}
                onChange={(e) => setOnlyWithRecommendations(e.target.checked)}
                className="rounded border-slate-600 bg-slate-800 text-teal-500"
              />
              Только с прогнозами
            </label>
            {(leagueFilter !== null || onlyWithRecommendations) && (
              <span className="text-slate-500 text-sm">
                Показано матчей: {filteredMatches.length}
              </span>
            )}
          </div>
        {filteredMatches.length === 0 ? (
          <p className="text-slate-500 py-6">Нет матчей по выбранным фильтрам</p>
        ) : (
        <div className="space-y-4">
          {leagueEntries.map(([leagueId, leagueMatches]) => {
            const key = leagueId ?? "no-league";
            const name = leagueMatches[0]?.league?.name ?? "Без лиги";
            const open = isLeagueOpen(key);
            const sortedMatches = sortMatchesByStart(leagueMatches);
            const useVirtualization = sortedMatches.length > LINE_VIRTUALIZE_FROM;
            return (
              <section
                key={key}
                className="rounded-xl border border-slate-700/80 bg-slate-900/40 overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => toggleLeague(key)}
                  className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left bg-slate-800/60 hover:bg-slate-800/80 transition-colors"
                  aria-expanded={open}
                >
                  <span className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
                    {name}
                  </span>
                  <span className="text-slate-500 text-sm tabular-nums">
                    {leagueMatches.length} матч. · {open ? "свернуть" : "развернуть"}
                  </span>
                  <span
                    className="shrink-0 text-slate-500 transition-transform"
                    style={{ transform: open ? "rotate(0deg)" : "rotate(-90deg)" }}
                    aria-hidden
                  >
                    ▼
                  </span>
                </button>
                {open && (
                  <div
                    className={`overflow-x-auto ${useVirtualization ? "max-h-[560px] overflow-y-auto" : ""}`}
                    onScroll={(e) => {
                      if (!useVirtualization) return;
                      setLeagueScrollTop((prev) => ({ ...prev, [key]: e.currentTarget.scrollTop }));
                    }}
                  >
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-700/80 bg-slate-800/40">
                          <th className="text-left py-2.5 pr-3 font-medium">До начала</th>
                          <th className="text-left py-2.5 pr-3 font-medium">Дата и время</th>
                          <th className="text-left py-2.5 pr-3 font-medium">Участник 1</th>
                          <th className="text-right py-2.5 pr-2 font-medium">Кф. 1</th>
                          <th className="text-center py-2.5 px-1 font-medium w-8"> </th>
                          <th className="text-left py-2.5 pl-2 pr-3 font-medium">Кф. 2</th>
                          <th className="text-right py-2.5 pr-3 font-medium">Участник 2</th>
                          <th className="text-left py-2.5 pr-3 font-medium">Вероятность</th>
                          <th className="text-left py-2.5 pl-2 font-medium">Прогноз</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(() => {
                          if (!useVirtualization) {
                            return sortedMatches.map((m) => (
                              <LineMatchRow
                                key={m.id}
                                match={m}
                                recommendation={hasWinnerOdds(m) ? (modelRecs[m.id] ?? null) : null}
                                showAnalyticsBlur={!hasFullAccess}
                              />
                            ));
                          }
                          const scrollTop = leagueScrollTop[key] ?? 0;
                          const start = Math.max(0, Math.floor(scrollTop / LINE_ROW_HEIGHT) - LINE_OVERSCAN);
                          const end = Math.min(
                            sortedMatches.length,
                            Math.ceil((scrollTop + LINE_VIEWPORT_HEIGHT) / LINE_ROW_HEIGHT) + LINE_OVERSCAN,
                          );
                          const topPad = start * LINE_ROW_HEIGHT;
                          const bottomPad = Math.max(0, (sortedMatches.length - end) * LINE_ROW_HEIGHT);
                          const visible = sortedMatches.slice(start, end);
                          return (
                            <>
                              {topPad > 0 && (
                                <tr>
                                  <td colSpan={9} style={{ height: topPad, padding: 0, border: 0 }} />
                                </tr>
                              )}
                              {visible.map((m) => (
                                <LineMatchRow
                                  key={m.id}
                                  match={m}
                                  recommendation={hasWinnerOdds(m) ? (modelRecs[m.id] ?? null) : null}
                                  showAnalyticsBlur={!hasFullAccess}
                                />
                              ))}
                              {bottomPad > 0 && (
                                <tr>
                                  <td colSpan={9} style={{ height: bottomPad, padding: 0, border: 0 }} />
                                </tr>
                              )}
                            </>
                          );
                        })()}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            );
          })}
        </div>
        )}
        </>
      )}
    </main>
  );
}
