"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getTableTennisLine,
  subscribeTableTennisLineStream,
  type TableTennisLineResponse,
  type TableTennisLineEvent,
} from "@/lib/api";

const STORAGE_KEY_LINE_COMPACT = "tt_line_compact_mode_v1";

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

function cleanForecastText(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "Недостаточно данных для расчёта";
  return text
    .replace(/\s*\(\d+(?:[.,]\d+)?%\)/g, "")
    .replace(/%/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function hasVisibleForecast(value: string | null | undefined): boolean {
  const cleaned = cleanForecastText(value);
  return cleaned !== "" && cleaned !== "—" && cleaned !== "Недостаточно данных для расчёта";
}

function getMlForecastText(ev: TableTennisLineEvent): string | null {
  const raw = ev.forecast_ml ?? ev.forecast;
  return hasVisibleForecast(raw) ? cleanForecastText(raw) : null;
}

function getNoMlForecastText(ev: TableTennisLineEvent): string | null {
  return hasVisibleForecast(ev.forecast_no_ml) ? cleanForecastText(ev.forecast_no_ml) : null;
}

function hasAnyVisibleForecast(ev: TableTennisLineEvent): boolean {
  return Boolean(getMlForecastText(ev) || getNoMlForecastText(ev));
}

function getForecastSortValue(ev: TableTennisLineEvent): string {
  const ml = getMlForecastText(ev);
  const noMl = getNoMlForecastText(ev);
  if (ml && noMl) return `${ml}/${noMl}`;
  return ml || noMl || "";
}

type StartFilter = "all" | "upcoming" | "live";
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
  { key: "odds_1", label: "П1" },
  { key: "odds_2", label: "П2" },
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
      return getForecastSortValue(ev);
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
  const [compactMode, setCompactMode] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setCompactMode(localStorage.getItem(STORAGE_KEY_LINE_COMPACT) === "1");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(STORAGE_KEY_LINE_COMPACT, compactMode ? "1" : "0");
  }, [compactMode]);

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
    const minOddsNum = filterMinOdds.trim() === "" ? null : parseFloat(filterMinOdds);

    let filtered = events.filter((ev) => {
      if (filterStart === "upcoming" && ev.status !== "scheduled") return false;
      if (filterStart === "live" && ev.status !== "live") return false;
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
        const hasForecastText = hasAnyVisibleForecast(ev);
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

  const cellPadClass = compactMode ? "px-2 py-2" : "px-4 py-3";
  const tableTextClass = compactMode ? "text-xs" : "text-sm";

  return (
    <div className="p-6 md:p-8">
      <div className="mb-4">
        <h1 className="font-display text-2xl font-bold text-white mb-1">
          Настольный теннис — линия
        </h1>
        <p className="text-slate-400 text-sm">
          {data.updated_at != null && (
            <> Обновлено: {new Date(data.updated_at * 1000).toLocaleString("ru-RU")}</>
          )}
        </p>
        <p className="text-slate-500 text-xs mt-1">
          Показано: {filteredAndSortedEvents.length}
          {data.events.length !== filteredAndSortedEvents.length &&
            ` из ${data.events.length}`}
        </p>
        <div className="mt-2">
          <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={compactMode}
              onChange={(e) => setCompactMode(e.target.checked)}
              className="rounded border-slate-500 text-emerald-500 focus:ring-slate-500"
            />
            <span>Компактный режим таблицы</span>
          </label>
        </div>
      </div>

      {/* Фильтры */}
      <div className="mb-4 text-sm md:static md:bg-transparent md:px-0 md:py-0 md:border-0 sticky top-[57px] z-20 bg-[var(--bg)]/95 backdrop-blur border-y border-slate-800 px-2 py-2 -mx-2">
        <div className="flex items-center justify-between md:hidden">
          <span className="text-slate-400 font-medium">Фильтры</span>
          <button
            type="button"
            onClick={() => setMobileFiltersOpen((v) => !v)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-300"
          >
            {mobileFiltersOpen ? "Скрыть" : "Показать"}
          </button>
        </div>
        <div className={`${mobileFiltersOpen ? "flex" : "hidden"} md:flex flex-wrap items-center gap-3 mt-2 md:mt-0`}>
          <span className="hidden md:inline text-slate-500">Фильтры:</span>
          <label className="flex items-center gap-2 text-slate-300">
            <span className="text-slate-500">Матчи:</span>
            <select
              value={filterStart}
              onChange={(e) => setFilterStart(e.target.value as StartFilter)}
              className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1"
            >
              <option value="all">Все</option>
              <option value="upcoming">Ещё не начались</option>
              <option value="live">Уже идут</option>
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
      </div>

      {data?.forecast_locked && data?.forecast_purchase_url && (
        <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3">
          <Link
            href={data.forecast_purchase_url}
            className="text-amber-200 hover:text-amber-100 font-medium"
          >
            {data.forecast_locked_message ?? "Для просмотра прогнозов приобретите подписку на аналитику"}
          </Link>
        </div>
      )}
      {filteredAndSortedEvents.length === 0 ? (
        <p className="text-slate-500">Нет матчей по выбранным фильтрам.</p>
      ) : (
        <>
          <div className="md:hidden space-y-2">
            {filteredAndSortedEvents.map((ev) => (
              <div key={String(ev.id)} className="rounded-lg border border-slate-700 bg-slate-800/40 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-200">
                    {formatCountdown(ev.time)}
                  </span>
                  <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-xs text-emerald-300 hover:text-emerald-200">
                    {formatDateTime(ev.time)}
                  </Link>
                </div>
                <div className="mt-2">
                  <Link href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`} className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-[11px] text-slate-300">
                    {ev.league_name}
                  </Link>
                </div>
                <div className="mt-2 grid grid-cols-[1fr_auto] gap-2 text-sm">
                  <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="font-semibold text-white hover:text-emerald-200">{ev.home_name}</Link>
                  <span className="tabular-nums text-slate-200">{ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}</span>
                  <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="font-semibold text-white hover:text-emerald-200">{ev.away_name}</Link>
                  <span className="tabular-nums text-slate-200">{ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}</span>
                </div>
                <div className="mt-2 text-xs leading-5">
                  {ev.odds_1 != null && ev.odds_2 != null ? (
                    data?.forecast_locked && data?.forecast_purchase_url ? (
                      <Link
                        href={data.forecast_purchase_url}
                        className="block rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-amber-200 hover:border-amber-400/70 hover:text-amber-100"
                      >
                        {data.forecast_locked_message ?? "Для просмотра приобретите подписку"}
                      </Link>
                    ) : hasAnyVisibleForecast(ev) ? (
                      <div className="flex flex-col gap-1.5">
                        {getMlForecastText(ev) && (
                          <Link
                            href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                            className="inline-flex items-center rounded-md border border-sky-400/40 bg-sky-500/10 px-2 py-1 text-sky-200 hover:border-sky-300/70 hover:text-sky-100 w-fit"
                          >
                            <span className="mr-1.5 inline-flex rounded bg-sky-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-100">
                              ML
                            </span>
                            <span className="text-sky-100">{getMlForecastText(ev)}</span>
                          </Link>
                        )}
                        {getNoMlForecastText(ev) && (
                          <Link
                            href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                            className="inline-flex items-center rounded-md border border-amber-400/40 bg-amber-500/10 px-2 py-1 text-amber-200 hover:border-amber-300/70 hover:text-amber-100 w-fit"
                          >
                            <span className="mr-1.5 inline-flex rounded bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-100">
                              no_ML
                            </span>
                            <span className="text-amber-100">{getNoMlForecastText(ev)}</span>
                          </Link>
                        )}
                      </div>
                    ) : (
                      <span className="text-slate-400">Недостаточно данных для расчёта</span>
                    )
                  ) : "—"}
                </div>
              </div>
            ))}
          </div>

          <div className="hidden md:block rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
            <div className="overflow-x-auto">
            <table className={`w-full ${tableTextClass}`}>
              <thead>
                <tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300 text-left">
                  <th className={`${cellPadClass} font-medium`}>
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
                  <th className={`${cellPadClass} font-medium`}>
                    <button
                      type="button"
                      onClick={() => cycleSort("time")}
                      className="flex items-center gap-1 hover:text-white transition text-left whitespace-nowrap"
                      title="Сортировка по дате и времени начала матча"
                    >
                      Дата и время начала
                      {sort?.key === "time" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className={`${cellPadClass} font-medium`}>
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
                  <th className={`${cellPadClass} font-medium`}>
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
                  <th className={`${cellPadClass} font-medium text-center tabular-nums whitespace-nowrap`}>
                    <button
                      type="button"
                      onClick={() => cycleSort("odds_1")}
                      className="inline-flex items-center gap-1 hover:text-white transition"
                    >
                      П1
                      {sort?.key === "odds_1" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className={`${cellPadClass} font-medium text-center tabular-nums whitespace-nowrap`}>
                    <button
                      type="button"
                      onClick={() => cycleSort("odds_2")}
                      className="inline-flex items-center gap-1 hover:text-white transition"
                    >
                      П2
                      {sort?.key === "odds_2" && (
                        <span className="text-emerald-400">
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  </th>
                  <th className={`${cellPadClass} font-medium`}>
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
                  <th className={`${cellPadClass} font-medium min-w-[220px]`}>
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
                {filteredAndSortedEvents.map((ev, idx) => (
                  <tr
                    key={String(ev.id)}
                    className={`border-b border-slate-700/60 transition ${
                      idx % 2 === 0 ? "bg-slate-900/10" : "bg-slate-900/30"
                    } hover:bg-slate-700/35`}
                  >
                    <td className={`${cellPadClass} whitespace-nowrap`}>
                      <span className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-200">
                        {formatCountdown(ev.time)}
                      </span>
                    </td>
                    <td className={`${cellPadClass} text-slate-300 whitespace-nowrap tabular-nums`}>
                      <Link
                        href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                        className="text-emerald-300 hover:text-emerald-200"
                      >
                        {formatDateTime(ev.time)}
                      </Link>
                    </td>
                    <td className={`${cellPadClass} text-slate-400`}>
                      <Link
                        href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`}
                        className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-xs hover:border-emerald-500/40 hover:text-emerald-200"
                      >
                        {ev.league_name}
                      </Link>
                    </td>
                    <td className={`${cellPadClass} text-white font-semibold whitespace-nowrap`}>
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`}
                        className="hover:text-emerald-200"
                      >
                        {ev.home_name}
                      </Link>
                    </td>
                    <td className={`${cellPadClass} text-center tabular-nums text-slate-300 whitespace-nowrap`}>
                      {ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}
                    </td>
                    <td className={`${cellPadClass} text-center tabular-nums text-slate-300 whitespace-nowrap`}>
                      {ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}
                    </td>
                    <td className={`${cellPadClass} text-white font-semibold whitespace-nowrap`}>
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`}
                        className="hover:text-emerald-200"
                      >
                        {ev.away_name}
                      </Link>
                    </td>
                    <td className={`${cellPadClass}`}>
                      {ev.odds_1 != null && ev.odds_2 != null ? (
                        data?.forecast_locked && data?.forecast_purchase_url ? (
                          <Link
                            href={data.forecast_purchase_url}
                            className={`inline-flex items-center rounded-md border border-amber-500/35 bg-amber-500/10 px-2 py-1 text-amber-200 hover:border-amber-400/70 hover:text-amber-100 ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}
                          >
                            {data.forecast_locked_message ?? "Для просмотра приобретите подписку"}
                          </Link>
                        ) : hasAnyVisibleForecast(ev) ? (
                          <div className={`flex flex-col gap-1 ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}>
                            {getMlForecastText(ev) && (
                              <Link
                                href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                                className={`inline-flex items-center rounded-md border border-sky-400/35 bg-sky-500/10 px-2 py-1 text-sky-200 hover:border-sky-300/70 hover:text-sky-100 w-fit ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}
                              >
                                <span className="mr-1.5 inline-flex rounded bg-sky-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-100">
                                  ML
                                </span>
                                <span className="text-sky-100">{getMlForecastText(ev)}</span>
                              </Link>
                            )}
                            {getNoMlForecastText(ev) && (
                              <Link
                                href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                                className={`inline-flex items-center rounded-md border border-amber-400/35 bg-amber-500/10 px-2 py-1 text-amber-200 hover:border-amber-300/70 hover:text-amber-100 w-fit ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}
                              >
                                <span className="mr-1.5 inline-flex rounded bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-100">
                                  no_ML
                                </span>
                                <span className="text-amber-100">{getNoMlForecastText(ev)}</span>
                              </Link>
                            )}
                          </div>
                        ) : (
                          <span className={`text-slate-400 ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}>
                            Недостаточно данных для расчёта
                          </span>
                        )
                      ) : (
                        <span className={`text-slate-500 ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </div>
        </>
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
