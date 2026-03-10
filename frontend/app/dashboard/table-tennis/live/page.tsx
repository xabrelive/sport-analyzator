"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getTableTennisLive,
  subscribeTableTennisLiveStream,
  type TableTennisLiveEvent,
  type TableTennisLiveResponse,
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
        const hasForecastText =
          typeof ev.forecast === "string" && ev.forecast.trim() !== "" && ev.forecast !== "Недостаточно данных для расчёта";
        if (!(hasOdds && hasForecastText)) return false;
      }
      return true;
    });
    // В лайве всегда держим стабильный порядок по времени начала, чтобы строки не "прыгали".
    filtered.sort((a, b) => (a.time ?? 0) - (b.time ?? 0));
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
  }, [data, filterStart, filterLeagueId, filterPlayerId, filterMinOdds, filterWithForecastOnly]);

  const nowSec = Math.floor(Date.now() / 1000);
  const playingEvents = filteredEvents.filter((e) => e.status === "live");
  const recentlyFinishedEvents = filteredEvents.filter((e) => e.status === "finished");

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

      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-slate-500">Фильтры:</span>
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
      </div>

      <div className="space-y-6">
        <div>
          <h2 className="text-sm font-semibold text-emerald-300 mb-2">Сейчас играют</h2>
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-slate-700 bg-slate-700/60 text-slate-300">
                  <th className="px-4 py-3 text-left font-medium">
                    Дата и время начала
                  </th>
                  <th className="px-4 py-3 text-left font-medium">
                    Лига
                  </th>
                  <th className="px-4 py-3 text-left font-medium">
                    Игрок 1
                  </th>
                  <th className="px-4 py-3 text-center font-medium">
                    Кф П1 (старт)
                  </th>
                  <th className="px-4 py-3 text-center font-medium">Счёт</th>
                  <th className="px-4 py-3 text-center font-medium">
                    Кф П2 (старт)
                  </th>
                  <th className="px-4 py-3 text-left font-medium">
                    Игрок 2
                  </th>
                  <th className="px-4 py-3 text-left font-medium">Прогноз</th>
                </tr></thead>
                <tbody>
                  {playingEvents.map((ev) => {
                    const setsLine = ev.sets ? Object.keys(ev.sets).sort((a,b)=>Number(a)-Number(b)).map((k)=>{const s=ev.sets?.[k]; if(!s || (s.home==null&&s.away==null)) return null; return `${s.home}-${s.away}`;}).filter(Boolean).join(" ") : "";
                    const changedAgo = ev.last_score_changed_at ? nowSec - ev.last_score_changed_at : null;
                    const activityClass = changedAgo != null && changedAgo < 180 ? "bg-emerald-900/15" : changedAgo != null && changedAgo < 600 ? "bg-slate-700/10" : "bg-slate-900/20";
                    return (
                      <tr key={String(ev.id)} className={`border-b border-slate-700/60 hover:bg-slate-700/30 transition ${activityClass}`}>
                        <td className="px-4 py-3 text-slate-300 tabular-nums whitespace-nowrap">
                          <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-emerald-300 hover:text-emerald-200">
                            {formatDateTime(ev.time)}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                          <Link
                            href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`}
                            className="hover:text-emerald-200"
                          >
                            {ev.league_name}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-white whitespace-nowrap">
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="hover:text-emerald-200">{ev.home_name}</Link>
                        </td>
                        <td className="px-4 py-3 text-center text-slate-200 tabular-nums">{ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}</td>
                        <td className="px-4 py-3 text-center">
                          <div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>
                          {setsLine && <div className="text-[11px] text-slate-400">({setsLine})</div>}
                        </td>
                        <td className="px-4 py-3 text-center text-slate-200 tabular-nums">{ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}</td>
                        <td className="px-4 py-3 text-white whitespace-nowrap">
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="hover:text-emerald-200">{ev.away_name}</Link>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {ev.odds_1 != null && ev.odds_2 != null ? (
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                              className="text-emerald-300 hover:text-emerald-200"
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
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-2">Недавно завершены</h2>
          <div className="rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300">
                  <th className="px-4 py-3 text-left font-medium">Дата и время начала</th>
                  <th className="px-4 py-3 text-left font-medium">Лига</th>
                  <th className="px-4 py-3 text-left font-medium">Игрок 1</th>
                  <th className="px-4 py-3 text-center font-medium">Кф П1 (старт)</th>
                  <th className="px-4 py-3 text-center font-medium">Счёт</th>
                  <th className="px-4 py-3 text-center font-medium">Кф П2 (старт)</th>
                  <th className="px-4 py-3 text-left font-medium">Игрок 2</th>
                  <th className="px-4 py-3 text-left font-medium">Прогноз</th>
                </tr></thead>
                <tbody>
                  {recentlyFinishedEvents.map((ev) => {
                    const setsLine = ev.sets ? Object.keys(ev.sets).sort((a,b)=>Number(a)-Number(b)).map((k)=>{const s=ev.sets?.[k]; if(!s || (s.home==null&&s.away==null)) return null; return `${s.home}-${s.away}`;}).filter(Boolean).join(" ") : "";
                    const [p1, p2] = (ev.sets_score || "").split("-", 2);
                    const homeWin = Number(p1) > Number(p2);
                    const awayWin = Number(p2) > Number(p1);
                    return (
                      <tr key={String(ev.id)} className="border-b border-slate-700/60">
                        <td className="px-4 py-3 text-slate-300 tabular-nums whitespace-nowrap">
                          <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-emerald-300 hover:text-emerald-200">
                            {formatDateTime(ev.time)}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                          <Link
                            href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`}
                            className="hover:text-emerald-200"
                          >
                            {ev.league_name}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-white whitespace-nowrap">
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="hover:text-emerald-200">{ev.home_name}</Link>
                          {homeWin && <span className="text-emerald-300 text-[10px] font-semibold ml-1">WIN</span>}
                        </td>
                        <td className="px-4 py-3 text-center text-slate-200 tabular-nums">{ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}</td>
                        <td className="px-4 py-3 text-center"><div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>{setsLine && <div className="text-[11px] text-slate-400">({setsLine})</div>}</td>
                        <td className="px-4 py-3 text-center text-slate-200 tabular-nums">{ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}</td>
                        <td className="px-4 py-3 text-white whitespace-nowrap">
                          <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="hover:text-emerald-200">{ev.away_name}</Link>
                          {awayWin && <span className="text-emerald-300 text-[10px] font-semibold ml-1">WIN</span>}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {ev.odds_1 != null && ev.odds_2 != null ? (
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                              className="text-emerald-300 hover:text-emerald-200"
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

