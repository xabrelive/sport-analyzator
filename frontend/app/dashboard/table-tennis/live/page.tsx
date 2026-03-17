"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getTableTennisLive,
  subscribeTableTennisLiveStream,
  type TableTennisLiveEvent,
  type TableTennisLiveResponse,
} from "@/lib/api";

const STORAGE_KEY_LIVE_COMPACT = "tt_live_compact_mode_v1";

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

function secondsUntilStart(timeUnix: number | undefined): number | null {
  if (timeUnix == null) return null;
  return timeUnix - Math.floor(Date.now() / 1000);
}

function formatAgo(ts?: number | null): string {
  if (!ts) return "нет данных";
  const diffSec = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (diffSec < 60) return `${diffSec} сек назад`;
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins} мин назад`;
  return `${Math.floor(mins / 60)} ч назад`;
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

function getMlForecastText(ev: TableTennisLiveEvent): string | null {
  const raw = ev.forecast_ml ?? ev.forecast;
  return hasVisibleForecast(raw) ? cleanForecastText(raw) : null;
}

function getNoMlForecastText(ev: TableTennisLiveEvent): string | null {
  return hasVisibleForecast(ev.forecast_no_ml) ? cleanForecastText(ev.forecast_no_ml) : null;
}

function getNnForecastText(ev: TableTennisLiveEvent): string | null {
  return hasVisibleForecast(ev.forecast_nn) ? cleanForecastText(ev.forecast_nn) : null;
}

function hasAnyVisibleForecast(ev: TableTennisLiveEvent): boolean {
  return Boolean(getMlForecastText(ev) || getNoMlForecastText(ev) || getNnForecastText(ev));
}

type StartFilter = "all" | "under_hour" | "over_hour";

export default function TableTennisLivePage() {
  const [data, setData] = useState<TableTennisLiveResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStart, setFilterStart] = useState<StartFilter>("all");
  const [filterLeagueId, setFilterLeagueId] = useState("");
  const [filterPlayerId, setFilterPlayerId] = useState("");
  const [filterMinOdds, setFilterMinOdds] = useState("");
  const [filterWithForecastOnly, setFilterWithForecastOnly] = useState(false);
  const [compactMode, setCompactMode] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [sortByTime, setSortByTime] = useState<"asc" | "desc">("asc");

  useEffect(() => {
    if (typeof window === "undefined") return;
    setCompactMode(localStorage.getItem(STORAGE_KEY_LIVE_COMPACT) === "1");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(STORAGE_KEY_LIVE_COMPACT, compactMode ? "1" : "0");
  }, [compactMode]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await getTableTennisLive();
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки лайва");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const unsubscribe = subscribeTableTennisLiveStream(
      (next) => !cancelled && setData(next),
      (err) => !cancelled && setError(err.message)
    );
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const { filteredEvents, leaguesForFilter, playersForFilter } = useMemo(() => {
    if (!data) return { filteredEvents: [], leaguesForFilter: [], playersForFilter: [] as { id: string; name: string }[] };
    const all = [...data.events];
    const oneHourSec = 3600;
    const minOddsNum = filterMinOdds.trim() === "" ? null : parseFloat(filterMinOdds);
    let filtered = all.filter((ev) => {
      const secs = secondsUntilStart(ev.time);
      if (filterStart === "under_hour" && (secs == null || secs >= oneHourSec)) return false;
      if (filterStart === "over_hour" && (secs == null || secs < oneHourSec)) return false;
      if (filterLeagueId && ev.league_id !== filterLeagueId) return false;
      if (filterPlayerId && ev.home_id !== filterPlayerId && ev.away_id !== filterPlayerId) return false;
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
    filtered.sort((a, b) => {
      const ta = a.time ?? 0;
      const tb = b.time ?? 0;
      return sortByTime === "asc" ? ta - tb : tb - ta;
    });
    const leagueMap = new Map<string, string>();
    const playerMap = new Map<string, string>();
    all.forEach((ev) => {
      if (ev.league_id) leagueMap.set(ev.league_id, ev.league_name);
      if (ev.home_id) playerMap.set(ev.home_id, ev.home_name);
      if (ev.away_id) playerMap.set(ev.away_id, ev.away_name);
    });
    return {
      filteredEvents: filtered,
      leaguesForFilter: Array.from(leagueMap.entries()).map(([id, name]) => ({ id, name })),
      playersForFilter: Array.from(playerMap.entries()).map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name)),
    };
  }, [data, filterStart, filterLeagueId, filterPlayerId, filterMinOdds, filterWithForecastOnly, sortByTime]);

  const nowSec = Math.floor(Date.now() / 1000);
  const playingEvents = filteredEvents.filter((e) => e.status === "live");
  const recentlyFinishedEvents = filteredEvents.filter((e) => e.status === "finished");
  const cellPadClass = compactMode ? "px-2 py-2" : "px-4 py-3";
  const tableTextClass = compactMode ? "text-xs" : "text-sm";

  if (loading) {
    return <div className="p-6 md:p-8"><h1 className="font-display text-2xl font-bold text-white mb-2">Настольный теннис — лайв</h1><p className="text-slate-400">Загрузка лайв-матчей…</p></div>;
  }
  if (error) {
    return <div className="p-6 md:p-8"><h1 className="font-display text-2xl font-bold text-white mb-2">Настольный теннис — лайв</h1><p className="text-rose-400">{error}</p></div>;
  }

  return (
    <div className="p-6 md:p-8">
      <div className="mb-4">
        <h1 className="font-display text-2xl font-bold text-white mb-1">Настольный теннис — лайв</h1>
        <p className="text-slate-400 text-sm">
          Сейчас играют и недавно завершены (до 5 минут). {data?.updated_at != null && <>Обновлено: {new Date(data.updated_at * 1000).toLocaleString("ru-RU")}</>}
        </p>
        <p className="text-slate-500 text-xs mt-1">Сейчас играют: {playingEvents.length} · Недавно завершены: {recentlyFinishedEvents.length}</p>
      </div>

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
          <label className="flex items-center gap-2 text-slate-300"><span className="text-slate-500">Начало:</span>
            <select value={filterStart} onChange={(e) => setFilterStart(e.target.value as StartFilter)} className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1">
              <option value="all">Все</option><option value="under_hour">Менее часа</option><option value="over_hour">Более часа</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-300"><span className="text-slate-500">Лига:</span>
            <select value={filterLeagueId} onChange={(e) => setFilterLeagueId(e.target.value)} className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 min-w-[140px]">
              <option value="">Все лиги</option>{leaguesForFilter.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-300"><span className="text-slate-500">Игрок:</span>
            <select value={filterPlayerId} onChange={(e) => setFilterPlayerId(e.target.value)} className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 min-w-[160px]">
              <option value="">Все игроки</option>{playersForFilter.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-300"><span className="text-slate-500">Кф &gt;</span>
            <input type="number" min={1} step={0.01} value={filterMinOdds} onChange={(e) => setFilterMinOdds(e.target.value)} className="w-16 rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 tabular-nums" />
          </label>
          <label className="flex items-center gap-1 text-slate-300">
            <input
              type="checkbox"
              className="rounded border-slate-600 bg-slate-700"
              checked={filterWithForecastOnly}
              onChange={(e) => setFilterWithForecastOnly(e.target.checked)}
            />
            <span className="text-slate-500">Только с прогнозом</span>
          </label>
          <label className="flex items-center gap-1 text-slate-300">
            <input
              type="checkbox"
              className="rounded border-slate-600 bg-slate-700"
              checked={compactMode}
              onChange={(e) => setCompactMode(e.target.checked)}
            />
            <span className="text-slate-500">Компактный режим</span>
          </label>
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

      <div className="space-y-6">
        <div>
          <h2 className="text-sm font-semibold text-emerald-300 mb-2">Сейчас играют</h2>
          <div className="md:hidden space-y-2">
            {playingEvents.map((ev) => {
              const setsLine = ev.sets ? Object.keys(ev.sets).sort((a,b)=>Number(a)-Number(b)).map((k)=>{const s=ev.sets?.[k]; if(!s || (s.home==null&&s.away==null)) return null; return `${s.home}-${s.away}`;}).filter(Boolean).join(" ") : "";
              return (
                <div key={String(ev.id)} className="rounded-lg border border-slate-700 bg-slate-800/40 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-xs text-emerald-300 hover:text-emerald-200">
                      {formatDateTime(ev.time)}
                    </Link>
                    <span className="inline-flex items-center rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">LIVE</span>
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
                  <div className="mt-2 text-center">
                    <div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>
                    {setsLine && <div className="text-[11px] text-slate-400">({setsLine})</div>}
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
                          {getNnForecastText(ev) && (
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                              className="inline-flex items-center rounded-md border border-fuchsia-400/40 bg-fuchsia-500/10 px-2 py-1 text-fuchsia-200 hover:border-fuchsia-300/70 hover:text-fuchsia-100 w-fit"
                            >
                              <span className="mr-1.5 inline-flex rounded bg-fuchsia-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fuchsia-100">
                                NN
                              </span>
                              <span className="text-fuchsia-100">{getNnForecastText(ev)}</span>
                            </Link>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400">Недостаточно данных для расчёта</span>
                      )
                    ) : "—"}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="hidden md:block rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
            <div className="overflow-x-auto">
              <table className={`w-full ${tableTextClass}`}>
                <thead><tr className="border-b border-slate-700 bg-slate-700/60 text-slate-300">
                  <th
                    className={`${cellPadClass} text-left font-medium cursor-pointer hover:text-white select-none`}
                    onClick={() => setSortByTime((d) => (d === "asc" ? "desc" : "asc"))}
                    title="Сортировка по дате и времени начала матча"
                  >
                    Дата и время начала {sortByTime === "asc" ? "↑" : "↓"}
                  </th>
                  <th className={`${cellPadClass} text-left font-medium`}>
                    Лига
                  </th>
                  <th className={`${cellPadClass} text-left font-medium`}>
                    Игрок 1
                  </th>
                  <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>
                    П1
                  </th>
                  <th className={`${cellPadClass} text-center font-medium`}>Счёт</th>
                  <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>
                    П2
                  </th>
                  <th className={`${cellPadClass} text-left font-medium`}>
                    Игрок 2
                  </th>
                  <th className={`${cellPadClass} text-left font-medium min-w-[220px]`}>Прогноз</th>
                </tr></thead>
                <tbody>
                  {playingEvents.map((ev, idx) => {
                    const setsLine = ev.sets ? Object.keys(ev.sets).sort((a,b)=>Number(a)-Number(b)).map((k)=>{const s=ev.sets?.[k]; if(!s || (s.home==null&&s.away==null)) return null; return `${s.home}-${s.away}`;}).filter(Boolean).join(" ") : "";
                    const changedAgo = ev.last_score_changed_at ? nowSec - ev.last_score_changed_at : null;
                    const activityClass = changedAgo != null && changedAgo < 180 ? "bg-emerald-900/15" : changedAgo != null && changedAgo < 600 ? "bg-slate-700/10" : "bg-slate-900/20";
                    return (
                      <tr key={String(ev.id)} className={`border-b border-slate-700/60 hover:bg-slate-700/30 transition ${activityClass} ${idx % 2 === 0 ? "bg-slate-900/10" : ""}`}>
                        <td className={`${cellPadClass} text-slate-300 tabular-nums whitespace-nowrap`}>
                          <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-emerald-300 hover:text-emerald-200">
                            {formatDateTime(ev.time)}
                          </Link>
                        </td>
                        <td className={`${cellPadClass} text-slate-400 whitespace-nowrap`}>
                          <Link
                            href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`}
                            className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-xs hover:border-emerald-500/40 hover:text-emerald-200"
                          >
                            {ev.league_name}
                          </Link>
                        </td>
                        <td className={`${cellPadClass} text-white whitespace-nowrap font-semibold`}>
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="hover:text-emerald-200">{ev.home_name}</Link>
                        </td>
                        <td className={`${cellPadClass} text-center text-slate-200 tabular-nums whitespace-nowrap`}>{ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}</td>
                        <td className={`${cellPadClass} text-center`}>
                          <div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>
                          {setsLine && <div className="text-[11px] text-slate-400">({setsLine})</div>}
                        </td>
                        <td className={`${cellPadClass} text-center text-slate-200 tabular-nums whitespace-nowrap`}>{ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}</td>
                        <td className={`${cellPadClass} text-white whitespace-nowrap font-semibold`}>
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="hover:text-emerald-200">{ev.away_name}</Link>
                        </td>
                        <td className={`${cellPadClass} ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}>
                          {ev.odds_1 != null && ev.odds_2 != null ? (
                            data?.forecast_locked && data?.forecast_purchase_url ? (
                              <Link
                                href={data.forecast_purchase_url}
                                className="inline-flex items-center rounded-md border border-amber-500/35 bg-amber-500/10 px-2 py-1 text-amber-200 hover:border-amber-400/70 hover:text-amber-100"
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
                                {getNnForecastText(ev) && (
                                  <Link
                                    href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                                    className={`inline-flex items-center rounded-md border border-fuchsia-400/35 bg-fuchsia-500/10 px-2 py-1 text-fuchsia-200 hover:border-fuchsia-300/70 hover:text-fuchsia-100 w-fit ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}
                                  >
                                    <span className="mr-1.5 inline-flex rounded bg-fuchsia-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fuchsia-100">
                                      NN
                                    </span>
                                    <span className="text-fuchsia-100">{getNnForecastText(ev)}</span>
                                  </Link>
                                )}
                              </div>
                            ) : (
                              <span className="text-slate-400">Недостаточно данных для расчёта</span>
                            )
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-2">Недавно завершены</h2>
          <div className="md:hidden space-y-2">
            {recentlyFinishedEvents.map((ev) => {
              const setsLine = ev.sets ? Object.keys(ev.sets).sort((a,b)=>Number(a)-Number(b)).map((k)=>{const s=ev.sets?.[k]; if(!s || (s.home==null&&s.away==null)) return null; return `${s.home}-${s.away}`;}).filter(Boolean).join(" ") : "";
              return (
                <div key={String(ev.id)} className="rounded-lg border border-slate-700 bg-slate-800/30 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-xs text-emerald-300 hover:text-emerald-200">
                      {formatDateTime(ev.time)}
                    </Link>
                    <span className="inline-flex items-center rounded-md border border-slate-500/40 bg-slate-500/10 px-2 py-0.5 text-[11px] text-slate-200">FIN</span>
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
                  <div className="mt-2 text-center">
                    <div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>
                    {setsLine && <div className="text-[11px] text-slate-400">({setsLine})</div>}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="hidden md:block rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden">
            <div className="overflow-x-auto">
              <table className={`w-full ${tableTextClass}`}>
                <thead><tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300">
                  <th
                    className={`${cellPadClass} text-left font-medium cursor-pointer hover:text-white select-none`}
                    onClick={() => setSortByTime((d) => (d === "asc" ? "desc" : "asc"))}
                    title="Сортировка по дате и времени начала матча"
                  >
                    Дата и время начала {sortByTime === "asc" ? "↑" : "↓"}
                  </th>
                  <th className={`${cellPadClass} text-left font-medium`}>Лига</th>
                  <th className={`${cellPadClass} text-left font-medium`}>Игрок 1</th>
                  <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>П1</th>
                  <th className={`${cellPadClass} text-center font-medium`}>Счёт</th>
                  <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>П2</th>
                  <th className={`${cellPadClass} text-left font-medium`}>Игрок 2</th>
                  <th className={`${cellPadClass} text-left font-medium min-w-[220px]`}>Прогноз</th>
                </tr></thead>
                <tbody>
                  {recentlyFinishedEvents.map((ev, idx) => {
                    const setsLine = ev.sets ? Object.keys(ev.sets).sort((a,b)=>Number(a)-Number(b)).map((k)=>{const s=ev.sets?.[k]; if(!s || (s.home==null&&s.away==null)) return null; return `${s.home}-${s.away}`;}).filter(Boolean).join(" ") : "";
                    const [p1, p2] = (ev.sets_score || "").split("-", 2);
                    const homeWin = Number(p1) > Number(p2);
                    const awayWin = Number(p2) > Number(p1);
                    return (
                      <tr key={String(ev.id)} className={`border-b border-slate-700/60 ${idx % 2 === 0 ? "bg-slate-900/10" : "bg-slate-900/25"}`}>
                        <td className={`${cellPadClass} text-slate-300 tabular-nums whitespace-nowrap`}>
                          <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-emerald-300 hover:text-emerald-200">
                            {formatDateTime(ev.time)}
                          </Link>
                        </td>
                        <td className={`${cellPadClass} text-slate-400 whitespace-nowrap`}>
                          <Link
                            href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`}
                            className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-xs hover:border-emerald-500/40 hover:text-emerald-200"
                          >
                            {ev.league_name}
                          </Link>
                        </td>
                        <td className={`${cellPadClass} text-white whitespace-nowrap font-semibold`}>
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="hover:text-emerald-200">{ev.home_name}</Link>
                          {homeWin && <span className="text-emerald-300 text-[10px] font-semibold ml-1">WIN</span>}
                        </td>
                        <td className={`${cellPadClass} text-center text-slate-200 tabular-nums whitespace-nowrap`}>{ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}</td>
                        <td className={`${cellPadClass} text-center`}><div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>{setsLine && <div className="text-[11px] text-slate-400">({setsLine})</div>}</td>
                        <td className={`${cellPadClass} text-center text-slate-200 tabular-nums whitespace-nowrap`}>{ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}</td>
                        <td className={`${cellPadClass} text-white whitespace-nowrap font-semibold`}>
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="hover:text-emerald-200">{ev.away_name}</Link>
                          {awayWin && <span className="text-emerald-300 text-[10px] font-semibold ml-1">WIN</span>}
                        </td>
                        <td className={`${cellPadClass} ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}>
                          {ev.odds_1 != null && ev.odds_2 != null ? (
                            data?.forecast_locked && data?.forecast_purchase_url ? (
                              <Link
                                href={data.forecast_purchase_url}
                                className="inline-flex items-center rounded-md border border-amber-500/35 bg-amber-500/10 px-2 py-1 text-amber-200 hover:border-amber-400/70 hover:text-amber-100"
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
                                {getNnForecastText(ev) && (
                                  <Link
                                    href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                                    className={`inline-flex items-center rounded-md border border-fuchsia-400/35 bg-fuchsia-500/10 px-2 py-1 text-fuchsia-200 hover:border-fuchsia-300/70 hover:text-fuchsia-100 w-fit ${compactMode ? "text-[11px] leading-4" : "text-xs leading-5"}`}
                                  >
                                    <span className="mr-1.5 inline-flex rounded bg-fuchsia-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fuchsia-100">
                                      NN
                                    </span>
                                    <span className="text-fuchsia-100">{getNnForecastText(ev)}</span>
                                  </Link>
                                )}
                              </div>
                            ) : (
                              <span className="text-slate-400">Недостаточно данных для расчёта</span>
                            )
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}

