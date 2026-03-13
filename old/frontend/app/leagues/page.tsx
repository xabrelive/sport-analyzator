"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  fetchLeagues,
  fetchMatchesByLeague,
  fetchFinishedMatches,
  fetchMatchesOverview,
  fetchSignals,
  type League,
  type Match,
} from "@/lib/api";
import { ResultsMatchRow } from "@/components/ResultsMatchRow";
import { LineMatchRow, formatSignalRecommendation } from "@/components/LineMatchRow";
import { LiveMatchRow } from "@/components/LiveMatchRow";
import { useSubscription } from "@/contexts/SubscriptionContext";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";

const PAGE_SIZE = 50;
const SIGNALS_LIMIT = 200;
const LEAGUES_CACHE_KEY = "view:leagues";
const LEAGUES_CACHE_MAX_AGE_MS = 90_000;

type Tab = "line" | "live" | "results";

function todayISO(): string {
  const d = new Date();
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0")
  );
}

function groupByDate(matches: Match[]): Map<string, Match[]> {
  const map = new Map<string, Match[]>();
  for (const m of matches) {
    const d = new Date(m.start_time);
    const key = d.toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(m);
  }
  return map;
}

function sortMatchesNewestFirst(matches: Match[]): Match[] {
  return [...matches].sort(
    (a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
  );
}

function sortDateKeysNewestFirst(byDate: Map<string, Match[]>): string[] {
  return Array.from(byDate.keys()).sort((a, b) => {
    const matchesA = byDate.get(a) ?? [];
    const matchesB = byDate.get(b) ?? [];
    const tA = Math.max(
      ...matchesA.map((m) => new Date(m.start_time).getTime()),
      0
    );
    const tB = Math.max(
      ...matchesB.map((m) => new Date(m.start_time).getTime()),
      0
    );
    return tB - tA;
  });
}

function buildRecommendationByMatch(
  signals: { match_id: string; market_type: string; selection: string }[]
): Map<string, string> {
  const byMatch = new Map<string, string>();
  for (const s of signals) {
    if (!byMatch.has(s.match_id)) {
      byMatch.set(s.match_id, formatSignalRecommendation(s.market_type, s.selection));
    }
  }
  return byMatch;
}

function LeaguesPageContent() {
  const searchParams = useSearchParams();
  const leagueIdFromUrl = searchParams.get("league");
  const tabFromUrl = (searchParams.get("tab") as Tab) || "line";

  const [leagues, setLeagues] = useState<League[]>([]);
  const [leagueQuery, setLeagueQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(() => leagueIdFromUrl);
  const [tab, setTab] = useState<Tab>(tabFromUrl);

  const [lineMatches, setLineMatches] = useState<Match[]>([]);
  const [liveMatches, setLiveMatches] = useState<Match[]>([]);
  const [resultsItems, setResultsItems] = useState<Match[]>([]);
  const [resultsTotal, setResultsTotal] = useState(0);
  const [resultsPage, setResultsPage] = useState(0);
  const [resultsDateFrom, setResultsDateFrom] = useState(() => todayISO());
  const [resultsDateTo, setResultsDateTo] = useState(() => todayISO());

  const [loadingLeagues, setLoadingLeagues] = useState(true);
  const [loadingLine, setLoadingLine] = useState(false);
  const [loadingLive, setLoadingLive] = useState(false);
  const [loadingResults, setLoadingResults] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signals, setSignals] = useState<Awaited<ReturnType<typeof fetchSignals>>>([]);
  const [leagueOpen, setLeagueOpen] = useState<Record<string, boolean>>({});
  const [refreshTick, setRefreshTick] = useState(0);

  const { hasFullAccess } = useSubscription();

  useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      setRefreshTick((v) => v + 1);
    }
  });

  useEffect(() => {
    const cached = getCached<{
      selectedId: string | null;
      tab: Tab;
      lineMatches: Match[];
      liveMatches: Match[];
      resultsItems: Match[];
      resultsTotal: number;
      resultsPage: number;
      resultsDateFrom: string;
      resultsDateTo: string;
    }>(LEAGUES_CACHE_KEY, LEAGUES_CACHE_MAX_AGE_MS);
    if (!cached) return;
    setSelectedId(cached.selectedId);
    setTab(cached.tab);
    setLineMatches(cached.lineMatches);
    setLiveMatches(cached.liveMatches);
    setResultsItems(cached.resultsItems);
    setResultsTotal(cached.resultsTotal);
    setResultsPage(cached.resultsPage);
    setResultsDateFrom(cached.resultsDateFrom);
    setResultsDateTo(cached.resultsDateTo);
  }, []);

  const filteredLeagues = useMemo(() => {
    if (!leagueQuery.trim()) return leagues;
    const q = leagueQuery.trim().toLowerCase();
    return leagues.filter(
      (l) =>
        l.name.toLowerCase().includes(q) ||
        (l.country ?? "").toLowerCase().includes(q)
    );
  }, [leagues, leagueQuery]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await fetchLeagues({ limit: 20 });
        if (!cancelled) setLeagues(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки лиг");
      } finally {
        if (!cancelled) setLoadingLeagues(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (leagueIdFromUrl && leagueIdFromUrl !== selectedId) {
      setSelectedId(leagueIdFromUrl);
    }
  }, [leagueIdFromUrl]);

  useEffect(() => {
    if (tabFromUrl && tabFromUrl !== tab) {
      setTab(tabFromUrl);
    }
  }, [tabFromUrl]);

  const selectLeague = useCallback(
    (id: string | null) => {
      setSelectedId(id);
      const params = new URLSearchParams(searchParams.toString());
      if (id) params.set("league", id);
      else params.delete("league");
      window.history.replaceState(null, "", `?${params.toString()}`);
    },
    [searchParams]
  );

  const setTabAndUrl = useCallback(
    (t: Tab) => {
      setTab(t);
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", t);
      if (selectedId) params.set("league", selectedId);
      window.history.replaceState(null, "", `?${params.toString()}`);
    },
    [searchParams, selectedId]
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await fetchSignals({ limit: 100 });
        if (!cancelled) setSignals(data);
      } catch {
        // ignore
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (!selectedId || tab !== "line") return;
    let cancelled = false;
    setLoadingLine(true);
    fetchMatchesByLeague(selectedId, "scheduled")
      .then((data) => {
        if (!cancelled) setLineMatches(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки линии");
      })
      .finally(() => {
        if (!cancelled) setLoadingLine(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, tab, refreshTick]);

  useEffect(() => {
    if (!selectedId || tab !== "live") return;
    let cancelled = false;
    setLoadingLive(true);
    const leagueId: string = selectedId;

    function load() {
      fetchMatchesOverview({ limit_live: 200, limit_upcoming: 0 })
        .then(({ live }) => {
          if (cancelled) return;
          const filtered = (live ?? []).filter((m) => m.league?.id === leagueId);
          setLiveMatches(filtered);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки лайва");
        })
        .finally(() => {
          if (!cancelled) setLoadingLive(false);
        });
    }
    load();
    const t = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [selectedId, tab, refreshTick]);

  useEffect(() => {
    if (!selectedId || tab !== "results") return;
    let cancelled = false;
    setLoadingResults(true);
    fetchFinishedMatches({
      league_id: selectedId,
      date_from: resultsDateFrom,
      date_to: resultsDateTo,
      limit: PAGE_SIZE,
      offset: resultsPage * PAGE_SIZE,
    })
      .then((data) => {
        if (!cancelled) {
          setResultsItems(data.items);
          setResultsTotal(data.total);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки результатов");
      })
      .finally(() => {
        if (!cancelled) setLoadingResults(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, tab, resultsDateFrom, resultsDateTo, resultsPage, refreshTick]);

  useEffect(() => {
    setCached(LEAGUES_CACHE_KEY, {
      selectedId,
      tab,
      lineMatches,
      liveMatches,
      resultsItems,
      resultsTotal,
      resultsPage,
      resultsDateFrom,
      resultsDateTo,
    });
  }, [
    selectedId,
    tab,
    lineMatches,
    liveMatches,
    resultsItems,
    resultsTotal,
    resultsPage,
    resultsDateFrom,
    resultsDateTo,
  ]);

  const selectedLeague = leagues.find((l) => l.id === selectedId);
  const recommendationByMatch = useMemo(
    () => buildRecommendationByMatch(signals),
    [signals]
  );

  const resultsByDate = useMemo(() => groupByDate(resultsItems), [resultsItems]);
  const resultsSortedDates = useMemo(
    () => sortDateKeysNewestFirst(resultsByDate),
    [resultsByDate]
  );

  const toggleDate = (dateStr: string) => {
    setLeagueOpen((prev) => ({ ...prev, [dateStr]: !prev[dateStr] }));
  };
  const isDateOpen = (dateStr: string) => leagueOpen[dateStr] !== false;

  const totalResultsPages = Math.ceil(resultsTotal / PAGE_SIZE) || 1;

  return (
    <main className="max-w-6xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-white mb-1">Лиги</h1>
      <p className="text-slate-500 text-sm mb-6">
        Выберите лигу и смотрите матчи по линии, в лайве или в результатах.
      </p>
      {error && (
        <p className="text-rose-400 mb-4">{error}</p>
      )}

      <div className="flex flex-col lg:flex-row gap-6">
        <aside className="w-full lg:w-64 shrink-0">
          <div className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-3">
            <input
              type="text"
              value={leagueQuery}
              onChange={(e) => setLeagueQuery(e.target.value)}
              placeholder="Поиск по названию или стране..."
              className="w-full rounded-lg border border-slate-600 bg-slate-800 text-white placeholder-slate-500 px-3 py-2 text-sm mb-3"
              aria-label="Поиск лиг"
            />
            <ul className="space-y-0.5 max-h-[320px] overflow-y-auto">
              {loadingLeagues ? (
                <li className="px-3 py-2 text-slate-500 text-sm">Загрузка...</li>
              ) : (
                filteredLeagues.map((l) => (
                  <li key={l.id}>
                    <button
                      type="button"
                      onClick={() => selectLeague(l.id)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors truncate ${
                        selectedId === l.id
                          ? "bg-teal-600/80 text-white"
                          : "text-slate-300 hover:bg-slate-800 hover:text-white"
                      }`}
                      title={l.country ? `${l.name} (${l.country})` : l.name}
                    >
                      {l.name}
                      {l.country ? (
                        <span className="text-slate-500 text-xs ml-1">
                          ({l.country})
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))
              )}
              {!loadingLeagues && filteredLeagues.length === 0 && (
                <li className="px-3 py-2 text-slate-500 text-sm">
                  {leagueQuery.trim() ? "Ничего не найдено" : "Нет лиг"}
                </li>
              )}
            </ul>
          </div>
        </aside>

        <div className="flex-1 min-w-0">
          {!selectedId ? (
            <div className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-8 text-center">
              <p className="text-slate-400 mb-2">Выберите лигу слева</p>
              <p className="text-slate-500 text-sm">
                Или начните вводить название или страну в поиске.
              </p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <h2 className="text-lg font-semibold text-white">
                  {selectedLeague?.name ?? selectedId}
                  {selectedLeague?.country ? (
                    <span className="text-slate-500 font-normal text-base ml-1">
                      ({selectedLeague.country})
                    </span>
                  ) : null}
                </h2>
                <nav
                  className="flex gap-1 rounded-lg border border-slate-700/80 bg-slate-900/40 p-1"
                  aria-label="Разделы матчей"
                >
                  {(
                    [
                      ["line", "Линия"],
                      ["live", "Лайв"],
                      ["results", "Результаты"],
                    ] as const
                  ).map(([t, label]) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTabAndUrl(t)}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                        tab === t
                          ? "bg-teal-600 text-white"
                          : "text-slate-400 hover:text-white hover:bg-slate-800"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </nav>
              </div>

              {tab === "line" && (
                <>
                  {loadingLine ? (
                    <p className="text-slate-500">Загрузка матчей линии...</p>
                  ) : lineMatches.length === 0 ? (
                    <p className="text-slate-500 py-8">
                      В этой лиге нет матчей в линии
                    </p>
                  ) : (
                    <div className="rounded-xl border border-slate-700/80 bg-slate-900/40 overflow-hidden">
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
                              <th className="text-left py-2.5 pl-2 font-medium">Прогноз</th>
                            </tr>
                          </thead>
                          <tbody>
                            {lineMatches.map((m) => (
                              <LineMatchRow
                                key={m.id}
                                match={m}
                                recommendation={recommendationByMatch.get(m.id) ?? null}
                                showAnalyticsBlur={!hasFullAccess}
                              />
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {tab === "live" && (
                <>
                  {loadingLive ? (
                    <p className="text-slate-500">Загрузка лайв-матчей...</p>
                  ) : liveMatches.length === 0 ? (
                    <p className="text-slate-500 py-8">
                      В этой лиге нет матчей в прямом эфире
                    </p>
                  ) : (
                    <div className="rounded-xl border border-slate-700/80 bg-slate-900/40 overflow-hidden">
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-slate-500 border-b border-slate-700/80 bg-slate-800/40">
                              <th className="text-left py-2.5 pr-3 font-medium w-16">Время</th>
                              <th className="text-left py-2.5 pr-3 font-medium">Участник 1</th>
                              <th className="text-right py-2.5 pr-2 font-medium">Кф. 1</th>
                              <th className="text-center py-2.5 px-2 font-medium">Счёт</th>
                              <th className="text-left py-2.5 pl-2 pr-3 font-medium">Кф. 2</th>
                              <th className="text-right py-2.5 pr-3 font-medium">Участник 2</th>
                              <th className="text-left py-2.5 pr-3 font-medium">Вероятность</th>
                              <th className="text-left py-2.5 pl-2 font-medium">Прогноз</th>
                            </tr>
                          </thead>
                          <tbody>
                            {liveMatches.map((m) => (
                              <LiveMatchRow
                                key={m.id}
                                match={m}
                                recommendation={recommendationByMatch.get(m.id) ?? null}
                                showAnalyticsBlur={!hasFullAccess}
                              />
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {tab === "results" && (
                <>
                  <div className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-4 mb-4">
                    <div className="flex flex-wrap items-end gap-4">
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Дата с</label>
                        <input
                          type="date"
                          value={resultsDateFrom}
                          onChange={(e) => {
                            setResultsDateFrom(e.target.value);
                            setResultsPage(0);
                          }}
                          className="rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Дата по</label>
                        <input
                          type="date"
                          value={resultsDateTo}
                          onChange={(e) => {
                            setResultsDateTo(e.target.value);
                            setResultsPage(0);
                          }}
                          className="rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm"
                        />
                      </div>
                      <p className="text-slate-400 text-sm tabular-nums">
                        Показано {resultsItems.length} из {resultsTotal}
                      </p>
                    </div>
                  </div>

                  {loadingResults ? (
                    <p className="text-slate-500">Загрузка результатов...</p>
                  ) : resultsItems.length === 0 ? (
                    <p className="text-slate-500 py-8">
                      Нет завершённых матчей за выбранный период
                    </p>
                  ) : (
                    <>
                      <div className="flex items-center justify-between gap-4 mb-3">
                        <p className="text-slate-400 text-sm">
                          Страница {resultsPage + 1} из {totalResultsPages}
                        </p>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => setResultsPage((p) => Math.max(0, p - 1))}
                            disabled={resultsPage === 0}
                            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800"
                          >
                            Назад
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setResultsPage((p) =>
                                Math.min(totalResultsPages - 1, p + 1)
                              )
                            }
                            disabled={resultsPage >= totalResultsPages - 1}
                            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800"
                          >
                            Вперёд
                          </button>
                        </div>
                      </div>

                      <div className="space-y-4">
                        {resultsSortedDates.map((dateStr) => {
                          const dayMatches = resultsByDate.get(dateStr) ?? [];
                          const open = isDateOpen(dateStr);
                          return (
                            <section
                              key={dateStr}
                              className="rounded-xl border border-slate-700/80 bg-slate-900/40 overflow-hidden"
                            >
                              <button
                                type="button"
                                onClick={() => toggleDate(dateStr)}
                                className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left bg-slate-800/60 hover:bg-slate-800/80 transition-colors"
                                aria-expanded={open}
                              >
                                <span className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
                                  {dateStr}
                                </span>
                                <span className="text-slate-500 text-sm tabular-nums">
                                  {dayMatches.length} матч. · {open ? "свернуть" : "развернуть"}
                                </span>
                                <span
                                  className="shrink-0 text-slate-500 transition-transform"
                                  style={{
                                    transform: open ? "rotate(0deg)" : "rotate(-90deg)",
                                  }}
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
                                        <th className="text-left py-2 pr-3 font-medium">Время</th>
                                        <th className="text-left py-2 pr-3 font-medium">Участник 1</th>
                                        <th className="text-center py-2 px-2 font-medium">Счёт</th>
                                        <th className="text-right py-2 pl-2 pr-3 font-medium">Участник 2</th>
                                        <th className="text-left py-2 pr-3 font-medium">Победитель</th>
                                        <th className="text-left py-2 pr-3 font-medium">Лига</th>
                                        <th className="text-left py-2 pl-2 font-medium w-20"> </th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {sortMatchesNewestFirst(dayMatches).map((m) => (
                                        <ResultsMatchRow key={m.id} match={m} />
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </section>
                          );
                        })}
                      </div>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}

export default function LeaguesPage() {
  return (
    <Suspense fallback={<main className="max-w-6xl mx-auto px-4 py-6 text-slate-500">Загрузка...</main>}>
      <LeaguesPageContent />
    </Suspense>
  );
}
