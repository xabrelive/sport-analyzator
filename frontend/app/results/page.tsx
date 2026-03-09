"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchFinishedMatches,
  fetchLeagues,
  fetchPlayers,
  type League,
  type Match,
  type Player,
} from "@/lib/api";
import { ResultsMatchRow } from "@/components/ResultsMatchRow";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";

const PAGE_SIZE = 50;
const RESULTS_CACHE_KEY = "view:results";
const RESULTS_CACHE_MAX_AGE_MS = 90_000;

/** Сегодня в формате YYYY-MM-DD для фильтра по умолчанию. */
function todayISO(): string {
  const d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

function groupByDate(matches: Match[]): Map<string, Match[]> {
  const map = new Map<string, Match[]>();
  for (const m of matches) {
    const d = new Date(m.start_time);
    const key = d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(m);
  }
  return map;
}

/** Сортировка матчей внутри группы: от новых к старым (по start_time desc). */
function sortMatchesNewestFirst(matches: Match[]): Match[] {
  return [...matches].sort((a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime());
}

/** Ключи дат от новых к старым (сегодня первый, затем вчера и т.д.). */
function sortDateKeysNewestFirst(byDate: Map<string, Match[]>): string[] {
  return Array.from(byDate.keys()).sort((a, b) => {
    const matchesA = byDate.get(a) ?? [];
    const matchesB = byDate.get(b) ?? [];
    const tA = Math.max(...matchesA.map((m) => new Date(m.start_time).getTime()), 0);
    const tB = Math.max(...matchesB.map((m) => new Date(m.start_time).getTime()), 0);
    return tB - tA;
  });
}

export default function ResultsPage() {
  const [items, setItems] = useState<Match[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState<string>(() => todayISO());
  const [dateTo, setDateTo] = useState<string>(() => todayISO());
  const [leagueId, setLeagueId] = useState<string>("");
  const [playerId, setPlayerId] = useState<string>("");
  const [playerQuery, setPlayerQuery] = useState("");
  const [playerSuggestions, setPlayerSuggestions] = useState<Player[]>([]);
  const [selectedPlayerName, setSelectedPlayerName] = useState<string>("");

  const [leagues, setLeagues] = useState<League[]>([]);
  const [leagueOpen, setLeagueOpen] = useState<Record<string, boolean>>({});
  const [isHydratedFromCache, setIsHydratedFromCache] = useState(false);

  const loadLeagues = useCallback(async () => {
    try {
      const data = await fetchLeagues({ limit: 300 });
      setLeagues(data);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadLeagues();
  }, [loadLeagues]);

  const loadResults = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number> = {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      };
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (leagueId) params.league_id = leagueId;
      if (playerId) params.player_id = playerId;
      const data = await fetchFinishedMatches(params);
      setItems(data.items);
      setTotal(data.total);
      setCached(RESULTS_CACHE_KEY, {
        items: data.items,
        total: data.total,
        page,
        dateFrom,
        dateTo,
        leagueId,
        playerId,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, dateFrom, dateTo, leagueId, playerId]);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") void loadResults();
  });

  useEffect(() => {
    const cached = getCached<{
      items: Match[];
      total: number;
      page: number;
      dateFrom: string;
      dateTo: string;
      leagueId: string;
      playerId: string;
    }>(RESULTS_CACHE_KEY, RESULTS_CACHE_MAX_AGE_MS);
    if (!cached) return;
    setItems(cached.items);
    setTotal(cached.total);
    setPage(cached.page);
    setDateFrom(cached.dateFrom);
    setDateTo(cached.dateTo);
    setLeagueId(cached.leagueId);
    setPlayerId(cached.playerId);
    setLoading(false);
    setIsHydratedFromCache(true);
  }, []);

  useEffect(() => {
    if (isHydratedFromCache) {
      setIsHydratedFromCache(false);
      void loadResults();
      return;
    }
    void loadResults();
  }, [loadResults, isHydratedFromCache]);

  useEffect(() => {
    if (!playerQuery.trim()) {
      setPlayerSuggestions([]);
      return;
    }
    let cancelled = false;
    fetchPlayers({ search: playerQuery.trim(), limit: 15 })
      .then((list) => {
        if (!cancelled) setPlayerSuggestions(list);
      })
      .catch(() => {
        if (!cancelled) setPlayerSuggestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [playerQuery]);

  const applyFilters = () => setPage(0);

  const byDate = groupByDate(items);
  const sortedDates = sortDateKeysNewestFirst(byDate);
  const start = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const end = Math.min((page + 1) * PAGE_SIZE, total);
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  const toggleDate = (dateStr: string) => {
    setLeagueOpen((prev) => ({ ...prev, [dateStr]: !prev[dateStr] }));
  };
  const isDateOpen = (dateStr: string) => leagueOpen[dateStr] !== false;

  return (
    <main className="max-w-5xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-white mb-2">Результаты</h1>
      <p className="text-slate-500 text-sm mb-4">
        Завершённые матчи от новых к старым. Фильтры по дате, лиге, игроку.
      </p>

      <div className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-4 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 items-end">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Дата с</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Дата по</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Лига</label>
            <select
              value={leagueId}
              onChange={(e) => setLeagueId(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm"
            >
              <option value="">Все лиги</option>
              {leagues.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}{l.country ? ` (${l.country})` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="relative">
            <label className="block text-xs text-slate-500 mb-1">Игрок</label>
            <input
              type="text"
              value={playerId ? selectedPlayerName : playerQuery}
              onChange={(e) => {
                setPlayerQuery(e.target.value);
                if (playerId) {
                  setPlayerId("");
                  setSelectedPlayerName("");
                }
              }}
              onFocus={() => playerQuery && setPlayerSuggestions([])}
              placeholder="Поиск по имени..."
              className="w-full rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm"
            />
            {playerId && (
              <button
                type="button"
                onClick={() => {
                  setPlayerId("");
                  setSelectedPlayerName("");
                  setPlayerQuery("");
                }}
                className="absolute right-2 bottom-2 text-slate-400 hover:text-white text-xs"
              >
                ✕
              </button>
            )}
            {playerSuggestions.length > 0 && (
              <ul className="absolute z-10 left-0 right-0 top-full mt-1 rounded-lg border border-slate-600 bg-slate-800 shadow-xl max-h-48 overflow-auto">
                {playerSuggestions.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      className="w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700"
                      onClick={() => {
                        setPlayerId(p.id);
                        setSelectedPlayerName(p.name);
                        setPlayerQuery("");
                        setPlayerSuggestions([]);
                      }}
                    >
                      {p.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <button
              type="button"
              onClick={applyFilters}
              className="w-full rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-medium py-2 text-sm"
            >
              Применить
            </button>
          </div>
        </div>
      </div>

      {error && <p className="text-rose-400 mb-4">{error}</p>}

      {loading ? (
        <p className="text-slate-500">Загрузка...</p>
      ) : (
        <>
          <div className="flex items-center justify-between gap-4 mb-4">
            <p className="text-slate-400 text-sm">
              Показано {start}–{end} из {total}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800"
              >
                Назад
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800"
              >
                Вперёд
              </button>
            </div>
          </div>

          <div className="space-y-4">
            {sortedDates.map((dateStr) => {
              const dayMatches = byDate.get(dateStr) ?? [];
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
            {items.length === 0 && (
              <p className="text-slate-500 py-8">Нет завершённых матчей по выбранным фильтрам</p>
            )}
          </div>
        </>
      )}
    </main>
  );
}
