"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getTableTennisLine,
  subscribeTableTennisLineStream,
  type TableTennisLineResponse,
  type TableTennisLineEvent,
} from "@/lib/api";

function formatDateTime(ts: number | undefined): string {
  if (ts == null) return "—";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function formatCountdown(timeUnix: number | undefined): string {
  if (timeUnix == null) return "—";
  const now = Math.floor(Date.now() / 1000);
  const diff = timeUnix - now;
  if (diff < 0) return "начался";
  if (diff < 60) return "через < 1 мин";
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `через ${mins} мин`;
  const hours = Math.floor(mins / 60);
  const restMins = mins % 60;
  if (restMins === 0) return `через ${hours} ч`;
  return `через ${hours} ч ${restMins} мин`;
}

function secondsUntilStart(timeUnix: number | undefined): number | null {
  if (timeUnix == null) return null;
  return timeUnix - Math.floor(Date.now() / 1000);
}

type StartFilter = "all" | "under_hour" | "over_hour";
type SortKey =
  | "time"
  | "league_name"
  | "home_name"
  | "odds_1"
  | "odds_2"
  | "away_name"
  | "forecast";
type SortDir = "asc" | "desc";

const SORT_KEYS: { key: SortKey; label: string }[] = [
  { key: "time", label: "Через сколько начало" },
  { key: "league_name", label: "Лига" },
  { key: "home_name", label: "Игрок 1" },
  { key: "odds_1", label: "Кф П1" },
  { key: "odds_2", label: "Кф П2" },
  { key: "away_name", label: "Игрок 2" },
  { key: "forecast", label: "Прогноз" },
];

function getEventValue(ev: TableTennisLineEvent, key: SortKey): string | number | null {
  switch (key) {
    case "time":
      return ev.time ?? 0;
    case "league_name":
      return ev.league_name ?? "";
    case "home_name":
      return ev.home_name ?? "";
    case "odds_1":
      return ev.odds_1 ?? -1;
    case "odds_2":
      return ev.odds_2 ?? -1;
    case "away_name":
      return ev.away_name ?? "";
    case "forecast":
      return (ev.forecast && ev.forecast !== "—" ? ev.forecast : "") || "";
    default:
      return null;
  }
}

export default function TableTennisLinePage() {
  const [data, setData] = useState<TableTennisLineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);

  // Фильтры
  const [filterStart, setFilterStart] = useState<StartFilter>("all");
  const [filterLeagueId, setFilterLeagueId] = useState<string>("");
  const [filterPlayerId, setFilterPlayerId] = useState<string>("");
  const [filterMinOdds, setFilterMinOdds] = useState<string>("");
  const [filterWithForecastOnly, setFilterWithForecastOnly] = useState(false);

  // Сортировка: null = сброс, иначе { key, dir }; по клику: нет -> asc -> desc -> нет
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);

  const cycleSort = useCallback((key: SortKey) => {
    setSort((prev) => {
      if (prev?.key !== key) return { key, dir: "asc" as SortDir };
      if (prev.dir === "asc") return { key, dir: "desc" as SortDir };
      return null;
    });
  }, []);

  // Обновление обратного отсчёта раз в минуту
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisLine()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    const unsubscribe = subscribeTableTennisLineStream(
      (next) => {
        if (!cancelled) setData(next);
      },
      (err) => {
        if (!cancelled) setError(err.message);
      }
    );

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const { filteredAndSortedEvents, leaguesForFilter, playersForFilter } = useMemo(() => {
    if (!data) {
      return { filteredAndSortedEvents: [], leaguesForFilter: [], playersForFilter: [] };
    }
    const events = [...data.events];
    const oneHourSec = 3600;
    const minOddsNum = filterMinOdds.trim() === "" ? null : parseFloat(filterMinOdds);

    let filtered = events.filter((ev) => {
      const secs = secondsUntilStart(ev.time);
      if (filterStart === "under_hour" && (secs == null || secs >= oneHourSec)) return false;
      if (filterStart === "over_hour" && (secs == null || secs < oneHourSec)) return false;
      if (filterLeagueId && ev.league_id !== filterLeagueId) return false;
      if (filterPlayerId && ev.home_id !== filterPlayerId && ev.away_id !== filterPlayerId)
        return false;
      if (minOddsNum != null && !Number.isNaN(minOddsNum)) {
        const o1 = ev.odds_1 ?? 0;
        const o2 = ev.odds_2 ?? 0;
        if (o1 < minOddsNum && o2 < minOddsNum) return false;
      }
      if (filterWithForecastOnly) {
        const hasOdds = ev.odds_1 != null && ev.odds_2 != null;
        const hasForecastText =
          typeof ev.forecast === "string" && ev.forecast.trim() !== "" && ev.forecast !== "Недостаточно данных для расчёта";
        if (!(hasOdds && hasForecastText)) return false;
      }
      return true;
    });

    if (sort) {
      filtered = [...filtered].sort((a, b) => {
        const va = getEventValue(a, sort.key);
        const vb = getEventValue(b, sort.key);
        const cmp =
          typeof va === "number" && typeof vb === "number"
            ? va - vb
            : String(va).localeCompare(String(vb));
        return sort.dir === "asc" ? cmp : -cmp;
      });
    } else {
      filtered.sort((a, b) => (a.time ?? 0) - (b.time ?? 0));
    }

    const leaguesForFilter = data.leagues ?? [];
    const playerMap = new Map<string, string>();
    events.forEach((ev) => {
      if (ev.home_id) playerMap.set(ev.home_id, ev.home_name ?? "");
      if (ev.away_id) playerMap.set(ev.away_id, ev.away_name ?? "");
    });
    const playersForFilter = Array.from(playerMap.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));

    return { filteredAndSortedEvents: filtered, leaguesForFilter, playersForFilter };
  }, [
    data,
    filterStart,
    filterLeagueId,
    filterPlayerId,
    filterMinOdds,
    filterWithForecastOnly,
    sort,
  ]);

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <h1 className="font-display text-2xl font-bold text-white mb-2">
          Настольный теннис — линия
        </h1>
        <p className="text-slate-400">Загрузка…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 md:p-8">
        <h1 className="font-display text-2xl font-bold text-white mb-2">
          Настольный теннис — линия
        </h1>
        <p className="text-rose-400">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="p-6 md:p-8">
      <div className="mb-4">
        <h1 className="font-display text-2xl font-bold text-white mb-1">
          Настольный теннис — линия
        </h1>
        <p className="text-slate-400 text-sm">
          Данные из BetsAPI. Обновляется автоматически без перезагрузки страницы.
          {data.updated_at != null && (
            <> Обновлено: {new Date(data.updated_at * 1000).toLocaleString("ru-RU")}</>
          )}
        </p>
        <p className="text-slate-500 text-xs mt-1">
          Показано: {filteredAndSortedEvents.length}
          {data.events.length !== filteredAndSortedEvents.length &&
            ` из ${data.events.length}`}
        </p>
      </div>

      {/* Фильтры */}
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-slate-500">Фильтры:</span>
        <label className="flex items-center gap-2 text-slate-300">
          <span className="text-slate-500">Начало:</span>
          <select
            value={filterStart}
            onChange={(e) => setFilterStart(e.target.value as StartFilter)}
            className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1"
          >
            <option value="all">Все</option>
            <option value="under_hour">Менее часа</option>
            <option value="over_hour">Более часа</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-slate-300">
          <span className="text-slate-500">Лига:</span>
          <select
            value={filterLeagueId}
            onChange={(e) => setFilterLeagueId(e.target.value)}
            className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 min-w-[140px]"
          >
            <option value="">Все лиги</option>
            {leaguesForFilter.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-slate-300">
          <span className="text-slate-500">Игрок:</span>
          <select
            value={filterPlayerId}
            onChange={(e) => setFilterPlayerId(e.target.value)}
            className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 min-w-[160px]"
          >
            <option value="">Все игроки</option>
            {playersForFilter.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-slate-300">
          <span className="text-slate-500">Кф &gt;</span>
          <input
            type="number"
            min={1}
            step={0.01}
            placeholder="—"
            value={filterMinOdds}
            onChange={(e) => setFilterMinOdds(e.target.value)}
            className="w-16 rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 tabular-nums"
          />
        </label>
        <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={filterWithForecastOnly}
            onChange={(e) => setFilterWithForecastOnly(e.target.checked)}
            className="rounded border-slate-500 text-emerald-500 focus:ring-slate-500"
          />
          <span>Только с прогнозом</span>
        </label>
        {(
          filterStart !== "all" ||
          filterLeagueId ||
          filterPlayerId ||
          filterMinOdds.trim() !== "" ||
          filterWithForecastOnly
        ) && (
          <button
            type="button"
            onClick={() => {
              setFilterStart("all");
              setFilterLeagueId("");
              setFilterPlayerId("");
              setFilterMinOdds("");
              setFilterWithForecastOnly(false);
            }}
            className="text-slate-400 hover:text-white text-xs underline"
          >
            Сбросить фильтры
          </button>
        )}
      </div>

      {filteredAndSortedEvents.length === 0 ? (
        <p className="text-slate-500">Нет матчей по выбранным фильтрам.</p>
      ) : (
        <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300 text-left">
                  <th className="px-4 py-3 font-medium">
                    <button
                      type="button"
                      onClick={() => cycleSort("time")}
                      className="flex items-center gap-1 hover:text-white transition"
                    >
                      Через сколько начало
                      {sort?.key === "time" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-medium text-left">Дата и время начала</th>
                  <th className="px-4 py-3 font-medium">
                    <button
                      type="button"
                      onClick={() => cycleSort("league_name")}
                      className="flex items-center gap-1 hover:text-white transition"
                    >
                      Лига
                      {sort?.key === "league_name" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <button
                      type="button"
                      onClick={() => cycleSort("home_name")}
                      className="flex items-center gap-1 hover:text-white transition"
                    >
                      Игрок 1
                      {sort?.key === "home_name" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-medium text-center tabular-nums">
                    <button
                      type="button"
                      onClick={() => cycleSort("odds_1")}
                      className="inline-flex items-center gap-1 hover:text-white transition"
                    >
                      Кф П1
                      {sort?.key === "odds_1" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-medium text-center tabular-nums">
                    <button
                      type="button"
                      onClick={() => cycleSort("odds_2")}
                      className="inline-flex items-center gap-1 hover:text-white transition"
                    >
                      Кф П2
                      {sort?.key === "odds_2" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <button
                      type="button"
                      onClick={() => cycleSort("away_name")}
                      className="flex items-center gap-1 hover:text-white transition"
                    >
                      Игрок 2
                      {sort?.key === "away_name" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <button
                      type="button"
                      onClick={() => cycleSort("forecast")}
                      className="flex items-center gap-1 hover:text-white transition"
                    >
                      Прогноз
                      {sort?.key === "forecast" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredAndSortedEvents.map((ev) => (
                  <tr
                    key={String(ev.id)}
                    className="border-b border-slate-700/60 hover:bg-slate-700/30 transition"
                  >
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                      {formatCountdown(ev.time)}
                    </td>
                    <td className="px-4 py-3 text-slate-300 whitespace-nowrap tabular-nums">
                      <Link
                        href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                        className="text-emerald-300 hover:text-emerald-200"
                      >
                        {formatDateTime(ev.time)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      <Link
                        href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`}
                        className="hover:text-emerald-200"
                      >
                        {ev.league_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-white">
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`}
                        className="hover:text-emerald-200"
                      >
                        {ev.home_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">
                      {ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">
                      {ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}
                    </td>
                    <td className="px-4 py-3 text-white">
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`}
                        className="hover:text-emerald-200"
                      >
                        {ev.away_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {ev.odds_1 != null && ev.odds_2 != null ? (
                        <Link
                          href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                          className="text-emerald-300 hover:text-emerald-200 text-xs"
                        >
                          {ev.forecast && String(ev.forecast).trim() !== ""
                            ? ev.forecast
                            : "Недостаточно данных для расчёта"}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {sort && (
        <p className="mt-2 text-slate-500 text-xs">
          Сортировка: {SORT_KEYS.find((s) => s.key === sort.key)?.label ?? sort.key}{" "}
          {sort.dir === "asc" ? "по возрастанию" : "по убыванию"}. Клик по заголовку — сменить,
          третий клик — сброс.
        </p>
      )}
    </div>
  );
}
