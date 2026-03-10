"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  getTableTennisLeagueCard,
  type TableTennisLeagueCard,
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

export default function TableTennisLeaguePage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";

  const [card, setCard] = useState<TableTennisLeagueCard | null>(null);
  const [upcomingPage, setUpcomingPage] = useState(1);
  const [finishedPage, setFinishedPage] = useState(1);
  const [dateMode, setDateMode] = useState<"single" | "range">("single");
  const [singleDateInput, setSingleDateInput] = useState("");
  const [rangeFromInput, setRangeFromInput] = useState("");
  const [rangeToInput, setRangeToInput] = useState("");
  const [appliedDateFrom, setAppliedDateFrom] = useState("");
  const [appliedDateTo, setAppliedDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisLeagueCard(
      id,
      upcomingPage,
      finishedPage,
      pageSize,
      appliedDateFrom,
      appliedDateTo
    )
      .then((res) => {
        if (cancelled) return;
        setCard(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, upcomingPage, finishedPage, appliedDateFrom, appliedDateTo]);

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <p className="text-slate-400">Загрузка…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 md:p-8">
        <p className="text-rose-400">{error}</p>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8">
      <div className="mb-4">
        <Link
          href="/dashboard/table-tennis/leagues"
          className="text-slate-400 hover:text-white text-sm mb-2 inline-block"
        >
          ← Лиги
        </Link>
        <h1 className="font-display text-2xl font-bold text-white">
          {card?.league?.name || "Лига"}
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Предстоящие и завершённые матчи лиги
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <span className="text-slate-400 text-sm">Всего матчей</span>
          <p className="text-white font-semibold tabular-nums">{card?.stats?.total_matches ?? 0}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <span className="text-slate-400 text-sm">Предстоит</span>
          <p className="text-white font-semibold tabular-nums">{card?.stats?.upcoming_matches ?? 0}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <span className="text-slate-400 text-sm">Завершено</span>
          <p className="text-white font-semibold tabular-nums">{card?.stats?.finished_matches ?? 0}</p>
        </div>
      </div>

      <div className="mb-6 rounded-lg border border-slate-700/70 bg-slate-800/40 p-4">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <span className="text-slate-400 text-sm">Фильтр по дате:</span>
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
                const date = singleDateInput.trim();
                setAppliedDateFrom(date);
                setAppliedDateTo(date);
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
              setUpcomingPage(1);
              setFinishedPage(1);
            }}
            className="rounded-md bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 text-sm text-white"
          >
            Применить
          </button>
          <button
            type="button"
            onClick={() => {
              setSingleDateInput("");
              setRangeFromInput("");
              setRangeToInput("");
              setAppliedDateFrom("");
              setAppliedDateTo("");
              setUpcomingPage(1);
              setFinishedPage(1);
              setError(null);
            }}
            className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:text-white"
          >
            Сбросить
          </button>
          {(appliedDateFrom || appliedDateTo) && (
            <span className="text-xs text-slate-400">
              Активный фильтр: {appliedDateFrom || "…"} — {appliedDateTo || "…"}
            </span>
          )}
        </div>
      </div>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-white mb-3">Предстоящие</h2>
        <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300 text-left">
                  <th className="px-4 py-3 font-medium">Дата и время</th>
                  <th className="px-4 py-3 font-medium">Матч</th>
                  <th className="px-4 py-3 font-medium text-center tabular-nums">П1</th>
                  <th className="px-4 py-3 font-medium text-center tabular-nums">П2</th>
                </tr>
              </thead>
              <tbody>
                {(card?.upcoming_matches ?? []).map((ev) => (
                  <tr
                    key={String(ev.id)}
                    className="border-b border-slate-700/60 hover:bg-slate-700/30 transition"
                  >
                    <td className="px-4 py-3 text-slate-300 whitespace-nowrap tabular-nums">
                      <Link
                        href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                        className="hover:text-white"
                      >
                        {formatDateTime(ev.time)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-white">
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`}
                        className="hover:text-emerald-300"
                      >
                        {ev.home_name}
                      </Link>
                      {" — "}
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`}
                        className="hover:text-emerald-300"
                      >
                        {ev.away_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">
                      {ev.odds_1 != null ? ev.odds_1.toFixed(2) : "—"}
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">
                      {ev.odds_2 != null ? ev.odds_2.toFixed(2) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <button
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
            disabled={upcomingPage <= 1}
            onClick={() => setUpcomingPage((v) => Math.max(1, v - 1))}
          >
            Назад
          </button>
          <span className="text-slate-400 text-sm">
            Страница {upcomingPage} из{" "}
            {Math.max(
              1,
              Math.ceil(
                (card?.pagination?.upcoming.total ?? 0) /
                  (card?.pagination?.upcoming.page_size ?? pageSize)
              )
            )}
          </span>
          <button
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
            disabled={
              upcomingPage >=
              Math.max(
                1,
                Math.ceil(
                  (card?.pagination?.upcoming.total ?? 0) /
                    (card?.pagination?.upcoming.page_size ?? pageSize)
                )
              )
            }
            onClick={() => setUpcomingPage((v) => v + 1)}
          >
            Вперёд
          </button>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3">Прошедшие</h2>
        <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300 text-left">
                  <th className="px-4 py-3 font-medium">Дата и время</th>
                  <th className="px-4 py-3 font-medium">Матч</th>
                  <th className="px-4 py-3 font-medium text-center">Счёт по сетам</th>
                </tr>
              </thead>
              <tbody>
                {(card?.finished_matches ?? []).map((ev) => (
                  <tr key={String(ev.id)} className="border-b border-slate-700/60 hover:bg-slate-700/30 transition">
                    <td className="px-4 py-3 text-slate-300 whitespace-nowrap tabular-nums">
                      <Link
                        href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`}
                        className="hover:text-white"
                      >
                        {formatDateTime(ev.time)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-white">
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`}
                        className="hover:text-emerald-300"
                      >
                        {ev.home_name}
                      </Link>
                      {" — "}
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`}
                        className="hover:text-emerald-300"
                      >
                        {ev.away_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-emerald-300">{ev.sets_score ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <button
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
            disabled={finishedPage <= 1}
            onClick={() => setFinishedPage((v) => Math.max(1, v - 1))}
          >
            Назад
          </button>
          <span className="text-slate-400 text-sm">
            Страница {finishedPage} из{" "}
            {Math.max(
              1,
              Math.ceil(
                (card?.pagination?.finished.total ?? 0) /
                  (card?.pagination?.finished.page_size ?? pageSize)
              )
            )}
          </span>
          <button
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
            disabled={
              finishedPage >=
              Math.max(
                1,
                Math.ceil(
                  (card?.pagination?.finished.total ?? 0) /
                    (card?.pagination?.finished.page_size ?? pageSize)
                )
              )
            }
            onClick={() => setFinishedPage((v) => v + 1)}
          >
            Вперёд
          </button>
        </div>
      </section>
    </div>
  );
}
