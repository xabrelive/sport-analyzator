"use client";

import { useEffect, useState, useMemo } from "react";
import { fetchMatches, fetchSignals, fetchMatchRecommendations, type Match } from "@/lib/api";
import { LineMatchRow, formatSignalRecommendation } from "@/components/LineMatchRow";
import { useSubscription } from "@/contexts/SubscriptionContext";

const UPCOMING_LIMIT = 200;
const SIGNALS_LIMIT = 200;

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

/** По списку сигналов строит map: match_id -> одна рекомендация (первый сигнал по матчу). */
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
  const [leagueFilter, setLeagueFilter] = useState<string | null>(null);
  const [onlyWithRecommendations, setOnlyWithRecommendations] = useState(false);
  const { hasFullAccess } = useSubscription();

  const recommendationByMatch = useMemo(() => buildRecommendationByMatch(signals), [signals]);

  const filteredMatches = useMemo(() => {
    let list = matches;
    if (leagueFilter !== null) list = list.filter((m) => (m.league?.id ?? null) === leagueFilter);
    if (onlyWithRecommendations) {
      list = list.filter((m) => Boolean(modelRecs[m.id] ?? recommendationByMatch.get(m.id)));
    }
    return list;
  }, [matches, leagueFilter, onlyWithRecommendations, modelRecs, recommendationByMatch]);

  const byLeague = useMemo(() => groupByLeague(filteredMatches), [filteredMatches]);
  const leagueEntries = useMemo(
    () => sortLeagueEntries(Array.from(byLeague.entries())),
    [byLeague]
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [data, signalsRes] = await Promise.all([
          fetchMatches("matches/upcoming", { limit: UPCOMING_LIMIT }),
          fetchSignals({ limit: SIGNALS_LIMIT }),
        ]);
        if (!cancelled) {
          setMatches(data);
          setSignals(signalsRes);
        }
        const ids = data.map((m) => m.id);
        if (ids.length > 0) {
          const recs = await fetchMatchRecommendations(ids);
          if (!cancelled) setModelRecs(recs);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const t = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

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
              Только с рекомендациями
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
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-700/80 bg-slate-800/40">
                          <th className="text-left py-2.5 pr-3 font-medium">Время</th>
                          <th className="text-left py-2.5 pr-3 font-medium">Участник 1</th>
                          <th className="text-right py-2.5 pr-2 font-medium">Кф. 1</th>
                          <th className="text-center py-2.5 px-1 font-medium w-8"> </th>
                          <th className="text-left py-2.5 pl-2 pr-3 font-medium">Кф. 2</th>
                          <th className="text-right py-2.5 pr-3 font-medium">Участник 2</th>
                          <th className="text-left py-2.5 pr-3 font-medium">Вероятность</th>
                          <th className="text-left py-2.5 pl-2 font-medium">Рекомендация</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortMatchesByStart(leagueMatches).map((m) => (
                          <LineMatchRow
                            key={m.id}
                            match={m}
                            recommendation={modelRecs[m.id] ?? null}
                            showAnalyticsBlur={!hasFullAccess}
                          />
                        ))}
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
