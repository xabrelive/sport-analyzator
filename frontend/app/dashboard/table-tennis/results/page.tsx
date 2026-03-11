"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getTableTennisResults, type TableTennisResultsResponse } from "@/lib/api";

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

function cleanForecastText(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "Недостаточно данных для расчёта";
  return text
    .replace(/\s*\(\d+(?:[.,]\d+)?%\)/g, "")
    .replace(/%/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export default function TableTennisResultsPage() {
  const [data, setData] = useState<TableTennisResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [leagueId, setLeagueId] = useState("");
  const [playerInput, setPlayerInput] = useState("");
  const [appliedPlayerQuery, setAppliedPlayerQuery] = useState("");
  const [dateMode, setDateMode] = useState<"single" | "range">("single");
  const [singleDateInput, setSingleDateInput] = useState("");
  const [rangeFromInput, setRangeFromInput] = useState("");
  const [rangeToInput, setRangeToInput] = useState("");
  const [appliedDateFrom, setAppliedDateFrom] = useState("");
  const [appliedDateTo, setAppliedDateTo] = useState("");
  const [onlyWithForecast, setOnlyWithForecast] = useState(false);
  const [sortByTime, setSortByTime] = useState<"asc" | "desc">("desc");
  const pageSize = 30;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisResults(
      page,
      pageSize,
      leagueId,
      appliedPlayerQuery,
      appliedDateFrom,
      appliedDateTo
    )
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки результатов");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, leagueId, appliedPlayerQuery, appliedDateFrom, appliedDateTo]);

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const displayItems = useMemo(() => {
    const raw = (data?.items ?? []).filter((ev) => {
      const hasOdds = ev.odds_1 != null && ev.odds_2 != null;
      if (onlyWithForecast) return hasOdds;
      return true;
    });
    return [...raw].sort((a, b) => {
      const ta = a.time ?? 0;
      const tb = b.time ?? 0;
      return sortByTime === "desc" ? tb - ta : ta - tb;
    });
  }, [data?.items, onlyWithForecast, sortByTime]);

  return (
    <div className="p-6 md:p-8">
      <h1 className="font-display text-2xl font-bold text-white mb-2">
        Настольный теннис — результаты
      </h1>
      <p className="text-slate-400 text-sm mb-4">Список завершённых матчей с фильтрами и пагинацией.</p>

      <div className="mb-4 rounded-lg border border-slate-700/70 bg-slate-800/40 p-4">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <label className="flex items-center gap-2 text-slate-300 text-sm">
            <span className="text-slate-500">Лига:</span>
            <select
              value={leagueId}
              onChange={(e) => {
                setLeagueId(e.target.value);
                setPage(1);
              }}
              className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 min-w-[180px]"
            >
              <option value="">Все лиги</option>
              {(data?.leagues ?? []).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-slate-300 text-sm">
            <span className="text-slate-500">Игрок:</span>
            <input
              value={playerInput}
              onChange={(e) => setPlayerInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setAppliedPlayerQuery(playerInput.trim());
                  setPage(1);
                }
              }}
              placeholder="Имя игрока"
              className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1 min-w-[200px]"
            />
          </label>

          <button
            type="button"
            onClick={() => {
              setAppliedPlayerQuery(playerInput.trim());
              setPage(1);
            }}
            className="rounded-md bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 text-sm text-white"
          >
            Применить поиск
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3 mb-3">
          <span className="text-slate-400 text-sm">Дата:</span>
          <button
            type="button"
            onClick={() => setDateMode("single")}
            className={`rounded-md px-3 py-1.5 text-sm border ${
              dateMode === "single"
                ? "bg-emerald-600/20 border-emerald-500 text-emerald-200"
                : "border-slate-600 text-slate-300"
            }`}
          >
            Одна дата
          </button>
          <button
            type="button"
            onClick={() => setDateMode("range")}
            className={`rounded-md px-3 py-1.5 text-sm border ${
              dateMode === "range"
                ? "bg-emerald-600/20 border-emerald-500 text-emerald-200"
                : "border-slate-600 text-slate-300"
            }`}
          >
            Период
          </button>
        </div>

        {dateMode === "single" ? (
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-slate-300">
              Дата:{" "}
              <input
                type="date"
                value={singleDateInput}
                onChange={(e) => setSingleDateInput(e.target.value)}
                className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1"
              />
            </label>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-slate-300">
              С:{" "}
              <input
                type="date"
                value={rangeFromInput}
                onChange={(e) => setRangeFromInput(e.target.value)}
                className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1"
              />
            </label>
            <label className="text-sm text-slate-300">
              По:{" "}
              <input
                type="date"
                value={rangeToInput}
                onChange={(e) => setRangeToInput(e.target.value)}
                className="rounded bg-slate-700 border border-slate-600 text-slate-200 px-2 py-1"
              />
            </label>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              if (dateMode === "single") {
                const d = singleDateInput.trim();
                setAppliedDateFrom(d);
                setAppliedDateTo(d);
              } else {
                const from = rangeFromInput.trim();
                const to = rangeToInput.trim();
                if (from && to && from > to) {
                  setError("Некорректный период: дата 'С' позже даты 'По'.");
                  return;
                }
                setError(null);
                setAppliedDateFrom(from);
                setAppliedDateTo(to);
              }
              setPage(1);
            }}
            className="rounded-md bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 text-sm text-white"
          >
            Применить дату
          </button>
          <button
            type="button"
            onClick={() => {
              setLeagueId("");
              setPlayerInput("");
              setAppliedPlayerQuery("");
              setSingleDateInput("");
              setRangeFromInput("");
              setRangeToInput("");
              setAppliedDateFrom("");
              setAppliedDateTo("");
              setPage(1);
              setError(null);
            }}
            className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:text-white"
          >
            Сбросить фильтры
          </button>
          {!data?.forecast_locked && (
            <label className="flex items-center gap-2 text-slate-300 text-sm ml-auto">
              <input
                type="checkbox"
                checked={onlyWithForecast}
                onChange={(e) => {
                  setOnlyWithForecast(e.target.checked);
                  setPage(1);
                }}
                className="rounded border-slate-500 text-emerald-500 focus:ring-slate-500"
              />
              <span>Только с прогнозом</span>
            </label>
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

      {loading ? <p className="text-slate-400">Загрузка…</p> : null}
      {error ? <p className="text-rose-400 mb-3">{error}</p> : null}

      {!loading && !error && (
        <>
          {displayItems.length === 0 ? (
            <p className="text-slate-500">По выбранным фильтрам завершённых матчей нет.</p>
          ) : (
            <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300 text-left">
                      <th
                        className="px-4 py-3 font-medium cursor-pointer hover:text-white select-none"
                        onClick={() => setSortByTime((d) => (d === "desc" ? "asc" : "desc"))}
                        title="Сортировка по дате и времени начала матча"
                      >
                        Дата и время {sortByTime === "desc" ? "↓" : "↑"}
                      </th>
                      <th className="px-4 py-3 font-medium">Лига</th>
                      <th className="px-4 py-3 font-medium">Игрок 1</th>
                      <th className="px-4 py-3 font-medium text-center tabular-nums">Кф П1</th>
                      <th className="px-4 py-3 font-medium text-center">Счёт</th>
                      <th className="px-4 py-3 font-medium text-center tabular-nums">Кф П2</th>
                      <th className="px-4 py-3 font-medium">Игрок 2</th>
                      {!data?.forecast_locked && <th className="px-4 py-3 font-medium">Прогноз</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {displayItems.map((ev) => {
                      const setsLine = ev.sets
                        ? Object.keys(ev.sets)
                            .sort((a, b) => Number(a) - Number(b))
                            .map((k) => {
                              const s = ev.sets?.[k];
                              if (!s || (s.home == null && s.away == null)) return null;
                              return `${s.home}-${s.away}`;
                            })
                            .filter(Boolean)
                            .join(" ")
                        : "";
                      return (
                        <tr key={String(ev.id)} className="border-b border-slate-700/60 hover:bg-slate-700/30 transition">
                          <td className="px-4 py-3 text-slate-300 whitespace-nowrap tabular-nums">
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                              className="text-emerald-300 hover:text-emerald-200"
                            >
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
                            <Link
                              href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`}
                              className="hover:text-emerald-200"
                            >
                              {ev.home_name}
                            </Link>
                          </td>
                          <td className="px-4 py-3 text-center text-slate-200 tabular-nums">{ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}</td>
                          <td className="px-4 py-3 text-center">
                            <div className="text-emerald-300 font-semibold tabular-nums">{ev.sets_score ?? "—"}</div>
                            {setsLine ? <div className="text-[11px] text-slate-400">({setsLine})</div> : null}
                          </td>
                          <td className="px-4 py-3 text-center text-slate-200 tabular-nums">{ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}</td>
                          <td className="px-4 py-3 text-white whitespace-nowrap">
                            <Link
                              href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`}
                              className="hover:text-emerald-200"
                            >
                              {ev.away_name}
                            </Link>
                          </td>
                          {!data?.forecast_locked && (
                            <td className="px-4 py-3 text-xs text-slate-400">
                              {ev.odds_1 != null && ev.odds_2 != null ? (
                                <Link
                                  href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                                  className="text-emerald-300 hover:text-emerald-200"
                                >
                                  {cleanForecastText(ev.forecast)}
                                </Link>
                              ) : (
                                "—"
                              )}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="mt-4 flex items-center gap-2">
            <button
              className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
              disabled={page <= 1}
              onClick={() => setPage((v) => Math.max(1, v - 1))}
            >
              Назад
            </button>
            <span className="text-slate-400 text-sm">
              Страница {page} из {totalPages} · матчей {total}
            </span>
            <button
              className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
              disabled={page >= totalPages}
              onClick={() => setPage((v) => Math.min(totalPages, v + 1))}
            >
              Вперёд
            </button>
          </div>
        </>
      )}
    </div>
  );
}

